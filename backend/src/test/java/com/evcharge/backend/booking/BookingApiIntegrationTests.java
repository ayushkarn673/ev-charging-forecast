package com.evcharge.backend.booking;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowable;
import static org.hamcrest.Matchers.hasItem;
import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.startsWith;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.BDDMockito.willAnswer;
import static org.mockito.BDDMockito.willThrow;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.function.IntFunction;

import com.jayway.jsonpath.JsonPath;
import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationInfo;
import org.flywaydb.core.api.MigrationState;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

import com.evcharge.backend.booking.BookingDtos.CreateBookingRequest;
import com.evcharge.backend.common.DuplicateBookingException;
import com.evcharge.backend.common.SlotUnavailableException;
import com.evcharge.backend.forecast.ForecastDtos.NextHourResponse;
import com.evcharge.backend.forecast.ForecastDtos.Prediction;
import com.evcharge.backend.forecast.ForecastRejectedException;
import com.evcharge.backend.forecast.ForecastUnavailableException;
import com.evcharge.backend.forecast.MlServiceClient;

/**
 * End-to-end API tests against the Docker MySQL. The FastAPI client is mocked so prices are
 * deterministic (the live service is exercised separately). Each test creates its own stations
 * (code prefix IT-) and deletes them and their bookings afterwards; demo data is never modified.
 * The clock is fixed at 2030-01-15T00:00Z (05:30 Asia/Kolkata); 2030-01-16 is a Wednesday.
 */
@SpringBootTest
@AutoConfigureMockMvc
@EnabledIfEnvironmentVariable(named = "DB_PASSWORD", matches = ".+")
class BookingApiIntegrationTests {

	static final Instant NOW = Instant.parse("2030-01-15T00:00:00Z");

	@TestConfiguration
	static class FixedClock {

		@Bean
		@Primary
		Clock fixedClock() {
			return Clock.fixed(NOW, ZoneOffset.UTC);
		}

	}

	@Autowired
	private MockMvc mvc;

	@Autowired
	private JdbcTemplate jdbc;

	@Autowired
	private Flyway flyway;

	@Autowired
	private BookingService service;

	@MockitoBean
	private MlServiceClient ml;

	private final List<Long> testStations = new ArrayList<>();

	static NextHourResponse forecast(OffsetDateTime time, double utilization) {
		return new NextHourResponse("historical_replay", true, "Historical replay: not live data.", "caltech", 54,
				time.toString(), time.toInstant().toString(), time.toString(), time.plusHours(1).toString(), 1,
				new Prediction(utilization, Math.round(utilization * 1000) / 10.0, utilization * 54,
						(int) Math.ceil(utilization * 54), 54 - (int) Math.ceil(utilization * 54), utilization),
				null, "ev_demand_lstm@sha256:test", List.of());
	}

	@BeforeEach
	void mediumDemandByDefault() {
		given(ml.predictNextHour(any())).willAnswer(inv -> forecast(inv.getArgument(0), 0.55));
	}

	private long station(int capacity, String basePrice) {
		String code = "IT-" + UUID.randomUUID().toString().substring(0, 8);
		GeneratedKeyHolder key = new GeneratedKeyHolder();
		jdbc.update(con -> {
			var ps = con.prepareStatement("""
					INSERT INTO stations (code, name, address, capacity, time_zone, base_price_per_hour, created_at)
					VALUES (?, ?, 'integration test', ?, 'Asia/Kolkata', ?, UTC_TIMESTAMP(6))""", new String[] { "id" });
			ps.setString(1, code);
			ps.setString(2, "Integration test " + code);
			ps.setInt(3, capacity);
			ps.setBigDecimal(4, new BigDecimal(basePrice));
			return ps;
		}, key);
		long id = key.getKey().longValue();
		testStations.add(id);
		return id;
	}

	@AfterEach
	void deleteTestData() {
		for (Long id : testStations) {
			jdbc.update("DELETE FROM bookings WHERE station_id = ?", id);
			jdbc.update("DELETE FROM stations WHERE id = ? AND code LIKE 'IT-%'", id);
		}
		testStations.clear();
	}

	private int bookingsAt(long stationId) {
		return jdbc.queryForObject("SELECT COUNT(*) FROM bookings WHERE station_id = ?", Integer.class, stationId);
	}

	private ResultActions book(long stationId, String start, String name) throws Exception {
		return book(stationId, start, name, null);
	}

	private ResultActions book(long stationId, String start, String name, String quoted) throws Exception {
		String body = """
				{"stationId": %d, "customerName": "%s", "startTime": "%s"%s}""".formatted(stationId, name, start,
				quoted == null ? "" : ", \"quotedFinalPrice\": " + quoted);
		return mvc.perform(post("/api/bookings").contentType(MediaType.APPLICATION_JSON).content(body));
	}

	// ------------------------------------------------------------------ migrations and seed data

	@Test
	void flywayAppliedSchemaAndDemoSeed() {
		MigrationInfo[] applied = flyway.info().applied();
		assertThat(applied).extracting(m -> m.getVersion().getVersion()).contains("1", "2");
		assertThat(applied).allMatch(m -> m.getState() == MigrationState.SUCCESS);
		assertThat(flyway.info().pending()).isEmpty();
		assertThat(jdbc.queryForList("SELECT code FROM stations WHERE code LIKE 'DEMO-%' ORDER BY code", String.class))
			.containsExactly("DEMO-01", "DEMO-02", "DEMO-03");
	}

	@Test
	void databaseConstraintsRejectInvalidRows() {
		long s = station(2, "100.00");
		String insert = """
				INSERT INTO bookings (station_id, customer_name, start_time, end_time, status, base_price, price_multiplier,
				  final_price, currency, predicted_utilization, congestion_level, forecast_mode, forecast_reference_time,
				  model_id, created_at)
				VALUES (?, 'x', ?, ?, 'CONFIRMED', 100, 1, 100, 'INR', ?, ?, 'historical_replay', '2020-02-05 18:00:00', 'm',
				  UTC_TIMESTAMP(6))""";
		assertThat(catchThrowable(() -> jdbc.update(insert, s, "2030-01-16 10:00:00", "2030-01-16 09:00:00", 0.5, "MEDIUM")))
			.as("end before start").isNotNull();
		assertThat(catchThrowable(() -> jdbc.update(insert, s, "2030-01-16 10:00:00", "2030-01-16 11:00:00", 1.5, "MEDIUM")))
			.as("utilization > 1").isNotNull();
		assertThat(catchThrowable(() -> jdbc.update(insert, s, "2030-01-16 10:00:00", "2030-01-16 11:00:00", 0.5, "EXTREME")))
			.as("unknown congestion level").isNotNull();
		assertThat(bookingsAt(s)).isZero();
	}

	// ------------------------------------------------------------------ stations and availability

	@Test
	void listsStations() throws Exception {
		long s = station(3, "99.50");
		mvc.perform(get("/api/stations"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$[*].code", hasItem("DEMO-01")))
			.andExpect(jsonPath("$[?(@.id == %d)].capacity".formatted(s)).value(3))
			.andExpect(jsonPath("$[?(@.id == %d)].basePricePerHour".formatted(s)).value(99.5))
			.andExpect(jsonPath("$[?(@.id == %d)].currency".formatted(s)).value("INR"));
	}

	@Test
	void availabilityShowsLocalHoursAndBookedCounts() throws Exception {
		long s = station(2, "100.00");
		book(s, "2030-01-16T10:00:00+05:30", "Asha").andExpect(status().isCreated());

		mvc.perform(get("/api/slots/availability").param("stationId", String.valueOf(s)).param("date", "2030-01-16"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.timeZone").value("Asia/Kolkata"))
			.andExpect(jsonPath("$.capacity").value(2))
			.andExpect(jsonPath("$.slots", hasSize(24)))
			.andExpect(jsonPath("$.slots[0].startTime").value("2030-01-16T00:00:00+05:30"))
			.andExpect(jsonPath("$.slots[10].booked").value(1))
			.andExpect(jsonPath("$.slots[10].available").value(1))
			.andExpect(jsonPath("$.slots[11].booked").value(0))
			.andExpect(jsonPath("$.slots[11].bookable").value(true));
	}

	@Test
	void availabilityMarksPastSlotsNotBookable() throws Exception {
		long s = station(2, "100.00");
		// NOW = 05:30 local on 2030-01-15: the 05:00 slot has started, 06:00 has not.
		mvc.perform(get("/api/slots/availability").param("stationId", String.valueOf(s)).param("date", "2030-01-15"))
			.andExpect(jsonPath("$.slots[5].bookable").value(false))
			.andExpect(jsonPath("$.slots[6].bookable").value(true));
	}

	@Test
	void availabilityValidatesParameters() throws Exception {
		long s = station(1, "100.00");
		mvc.perform(get("/api/slots/availability").param("stationId", "999999999").param("date", "2030-01-16"))
			.andExpect(status().isNotFound());
		mvc.perform(get("/api/slots/availability").param("stationId", String.valueOf(s)).param("date", "16-01-2030"))
			.andExpect(status().isBadRequest());
		mvc.perform(get("/api/slots/availability").param("stationId", String.valueOf(s)).param("date", "2030-03-01"))
			.andExpect(status().isBadRequest());
		mvc.perform(get("/api/slots/availability").param("date", "2030-01-16")).andExpect(status().isBadRequest());
	}

	// ------------------------------------------------------------------ pricing quote

	@Test
	void quoteUsesTheForecastForTheMappedReplayHour() throws Exception {
		long s = station(2, "120.00");
		mvc.perform(get("/api/pricing/quote").param("stationId", String.valueOf(s))
			.param("startTime", "2030-01-16T10:00:00+05:30"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.price.basePrice").value(120.0))
			.andExpect(jsonPath("$.price.congestionLevel").value("MEDIUM"))
			.andExpect(jsonPath("$.price.multiplier").value(1.15))
			.andExpect(jsonPath("$.price.finalPrice").value(138.0))
			.andExpect(jsonPath("$.price.utilization").value(0.55))
			.andExpect(jsonPath("$.forecast.mode").value("historical_replay"))
			.andExpect(jsonPath("$.forecast.isSimulation").value(true))
			.andExpect(jsonPath("$.forecast.horizonHours").value(1))
			.andExpect(jsonPath("$.forecast.replayForecastTime").value("2020-02-05T10:00:00-08:00"))
			.andExpect(jsonPath("$.forecast.mapping", startsWith("Demand signal for this WEDNESDAY 10:00 slot")));
		// Wednesday 10:00 IST is mapped to Wednesday 2020-02-05 10:00 Pacific time
		verify(ml).predictNextHour(OffsetDateTime.parse("2020-02-05T10:00:00-08:00"));
	}

	@Test
	void priceFollowsTheForecastCongestionBand() throws Exception {
		long s = station(2, "100.00");
		willAnswer(inv -> forecast(inv.getArgument(0), 0.12)).given(ml).predictNextHour(any());
		mvc.perform(get("/api/pricing/quote").param("stationId", String.valueOf(s))
			.param("startTime", "2030-01-16T03:00:00+05:30"))
			.andExpect(jsonPath("$.price.congestionLevel").value("LOW"))
			.andExpect(jsonPath("$.price.finalPrice").value(90.0));
		willAnswer(inv -> forecast(inv.getArgument(0), 0.70)).given(ml).predictNextHour(any());
		mvc.perform(get("/api/pricing/quote").param("stationId", String.valueOf(s))
			.param("startTime", "2030-01-16T13:00:00+05:30"))
			.andExpect(jsonPath("$.price.congestionLevel").value("HIGH"))
			.andExpect(jsonPath("$.price.finalPrice").value(135.0));
	}

	// ------------------------------------------------------------------ creating and listing bookings

	@Test
	void createsBookingThatPersistsWithItsPricingSnapshot() throws Exception {
		long s = station(2, "120.00");
		String location = book(s, "2030-01-16T10:00:00+05:30", "  Ravi Kumar ", "138.00")
			.andExpect(status().isCreated())
			.andExpect(header().string("Location", startsWith("/api/bookings/")))
			.andExpect(jsonPath("$.status").value("CONFIRMED"))
			.andExpect(jsonPath("$.customerName").value("Ravi Kumar"))
			.andExpect(jsonPath("$.startTime").value("2030-01-16T10:00:00+05:30"))
			.andExpect(jsonPath("$.endTime").value("2030-01-16T11:00:00+05:30"))
			.andExpect(jsonPath("$.basePrice").value(120.0))
			.andExpect(jsonPath("$.priceMultiplier").value(1.15))
			.andExpect(jsonPath("$.finalPrice").value(138.0))
			.andExpect(jsonPath("$.congestionLevel").value("MEDIUM"))
			.andExpect(jsonPath("$.forecastMode").value("historical_replay"))
			.andExpect(jsonPath("$.forecastReferenceTime").value("2020-02-05T18:00:00Z"))
			.andReturn().getResponse().getHeader("Location");

		long id = Long.parseLong(location.substring(location.lastIndexOf('/') + 1));
		var row = jdbc.queryForMap("""
				SELECT start_time, status, final_price, price_multiplier, predicted_utilization, congestion_level,
				       forecast_mode, model_id FROM bookings WHERE id = ?""", id);
		assertThat(row.get("start_time").toString()).startsWith("2030-01-16T04:30");   // stored as UTC
		assertThat(row.get("status")).isEqualTo("CONFIRMED");
		assertThat(row.get("final_price").toString()).isEqualTo("138.00");
		assertThat(row.get("price_multiplier").toString()).isEqualTo("1.150");
		assertThat(row.get("predicted_utilization").toString()).isEqualTo("0.550000");
		assertThat(row.get("congestion_level")).isEqualTo("MEDIUM");
		assertThat(row.get("forecast_mode")).isEqualTo("historical_replay");
		assertThat(row.get("model_id")).isEqualTo("ev_demand_lstm@sha256:test");

		mvc.perform(get(location)).andExpect(status().isOk()).andExpect(jsonPath("$.id").value(id));
		mvc.perform(get("/api/bookings").param("stationId", String.valueOf(s)))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$", hasSize(1)))
			.andExpect(jsonPath("$[0].id").value(id));
		mvc.perform(get("/api/bookings")).andExpect(status().isOk()).andExpect(jsonPath("$[*].id", hasItem((int) id)));
		mvc.perform(get("/api/bookings/999999999")).andExpect(status().isNotFound());
	}

	@Test
	void refusesBookingWhenTheShownPriceIsStale() throws Exception {
		long s = station(2, "120.00");
		book(s, "2030-01-16T10:00:00+05:30", "Stale", "120.00")
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.title").value("Price changed"));
		assertThat(bookingsAt(s)).isZero();
	}

	@Test
	void acceptsWholeLocalHourGivenInAnotherOffset() throws Exception {
		long s = station(1, "100.00");
		// 04:30Z is 10:00 in Asia/Kolkata -> a whole local hour
		book(s, "2030-01-16T04:30:00Z", "Offset").andExpect(status().isCreated())
			.andExpect(jsonPath("$.startTime").value("2030-01-16T10:00:00+05:30"));
		// 05:00Z is 10:30 locally -> rejected
		book(s, "2030-01-16T05:00:00Z", "Offset").andExpect(status().isBadRequest());
	}

	// ------------------------------------------------------------------ capacity and conflicts

	@Test
	void rejectsBookingWhenEveryChargerIsTaken() throws Exception {
		long s = station(2, "100.00");
		book(s, "2030-01-16T10:00:00+05:30", "A").andExpect(status().isCreated());
		book(s, "2030-01-16T10:00:00+05:30", "B").andExpect(status().isCreated());
		book(s, "2030-01-16T10:00:00+05:30", "C")
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.title").value("Slot unavailable"));
		// neighbouring hours are still free (half-open intervals)
		book(s, "2030-01-16T09:00:00+05:30", "D").andExpect(status().isCreated());
		book(s, "2030-01-16T11:00:00+05:30", "E").andExpect(status().isCreated());
		assertThat(bookingsAt(s)).isEqualTo(4);
	}

	@Test
	void concurrentRequestsCannotOverbook() throws Exception {
		long s = station(1, "100.00");
		int threads = 8;
		CountDownLatch ready = new CountDownLatch(threads);
		CountDownLatch go = new CountDownLatch(1);
		ExecutorService pool = Executors.newFixedThreadPool(threads);
		List<Future<Boolean>> results = new ArrayList<>();
		for (int i = 0; i < threads; i++) {
			String name = "Racer " + i;
			Callable<Boolean> task = () -> {
				ready.countDown();
				go.await();
				try {
					service.create(new CreateBookingRequest(s, name, OffsetDateTime.parse("2030-01-16T18:00:00+05:30"),
							null));
					return true;
				}
				catch (SlotUnavailableException ex) {
					return false;
				}
			};
			results.add(pool.submit(task));
		}
		ready.await();
		go.countDown();
		int succeeded = 0;
		for (Future<Boolean> r : results) {
			if (r.get()) {
				succeeded++;
			}
		}
		pool.shutdown();
		assertThat(succeeded).isEqualTo(1);
		assertThat(bookingsAt(s)).isEqualTo(1);
	}

	// ------------------------------------------------------------------ forecast service problems

	@Test
	void noBookingWithoutAForecast() throws Exception {
		long s = station(2, "100.00");
		willThrow(new ForecastUnavailableException("The forecasting service is not available", null)).given(ml).predictNextHour(any());
		book(s, "2030-01-16T10:00:00+05:30", "NoForecast")
			.andExpect(status().isServiceUnavailable())
			.andExpect(jsonPath("$.title").value("Forecast unavailable"));
		willThrow(new ForecastRejectedException("OUT_OF_RANGE", "outside replay range")).given(ml).predictNextHour(any());
		book(s, "2030-01-16T10:00:00+05:30", "NoForecast")
			.andExpect(status().isUnprocessableContent())
			.andExpect(jsonPath("$.code").value("OUT_OF_RANGE"));
		assertThat(bookingsAt(s)).isZero();
	}

	@Test
	void forecastEndpointReturnsModelOutputWithCongestionBand() throws Exception {
		mvc.perform(get("/api/forecast/next-hour").param("forecastTime", "2020-02-05T10:00:00-08:00"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.forecast.mode").value("historical_replay"))
			.andExpect(jsonPath("$.forecast.prediction.utilization").value(0.55))
			.andExpect(jsonPath("$.congestionLevel").value("MEDIUM"))
			.andExpect(jsonPath("$.pricingPolicy.thresholds.medium").value(0.40));
		mvc.perform(get("/api/forecast/next-hour").param("forecastTime", "yesterday")).andExpect(status().isBadRequest());
	}

	// ------------------------------------------------------------------ validation

	@Test
	void validatesBookingRequests() throws Exception {
		long s = station(2, "100.00");
		book(s, "2030-01-16T10:15:00+05:30", "X").andExpect(status().isBadRequest());     // not on the hour
		book(s, "2030-01-15T05:00:00+05:30", "X").andExpect(status().isBadRequest());     // in the past
		book(s, "2030-02-15T10:00:00+05:30", "X").andExpect(status().isBadRequest());     // > 14 days ahead
		book(s, "2030-01-16T10:00:00", "X").andExpect(status().isBadRequest());           // no offset
		book(s, "2030-01-16T10:00:00+05:30", "   ").andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.errors.customerName").exists());
		book(s, "2030-01-16T10:00:00+05:30", "X", "-5").andExpect(status().isBadRequest());
		book(999999999L, "2030-01-16T10:00:00+05:30", "X").andExpect(status().isNotFound());
		mvc.perform(post("/api/bookings").contentType(MediaType.APPLICATION_JSON).content("{}"))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.errors.stationId").exists())
			.andExpect(jsonPath("$.errors.startTime").exists())
			.andExpect(jsonPath("$.errors.customerName").exists());
		mvc.perform(post("/api/bookings").contentType(MediaType.APPLICATION_JSON).content("not json"))
			.andExpect(status().isBadRequest());
		assertThat(bookingsAt(s)).isZero();
	}

	// ------------------------------------------------------------------ Stage 1: lifecycle and robustness

	private long bookId(long stationId, String start, String name) throws Exception {
		String json = book(stationId, start, name).andExpect(status().isCreated()).andReturn().getResponse()
			.getContentAsString();
		return ((Number) JsonPath.read(json, "$.id")).longValue();
	}

	private ResultActions cancel(long bookingId) throws Exception {
		return mvc.perform(post("/api/bookings/{id}/cancel", bookingId));
	}

	private String statusOf(long bookingId) {
		return jdbc.queryForObject("SELECT status FROM bookings WHERE id = ?", String.class, bookingId);
	}

	@Test
	void availabilityRejectsPastDatesButAcceptsTodayAndTheWindow() throws Exception {
		long s = station(2, "100.00");
		// NOW = 2030-01-15 05:30 Asia/Kolkata -> today is 2030-01-15, last bookable day 2030-01-29
		mvc.perform(get("/api/slots/availability").param("stationId", String.valueOf(s)).param("date", "2030-01-14"))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.title").value("Invalid request"))
			.andExpect(jsonPath("$.detail", startsWith("date 2030-01-14 is in the past")));
		mvc.perform(get("/api/slots/availability").param("stationId", String.valueOf(s)).param("date", "2030-01-15"))
			.andExpect(status().isOk());
		mvc.perform(get("/api/slots/availability").param("stationId", String.valueOf(s)).param("date", "2030-01-29"))
			.andExpect(status().isOk());
		mvc.perform(get("/api/slots/availability").param("stationId", String.valueOf(s)).param("date", "2030-01-30"))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.title").value("Invalid request"));
	}

	@Test
	void slotStatusesMatchTheBookingRules() throws Exception {
		long s = station(1, "100.00");
		book(s, "2030-01-15T10:00:00+05:30", "Full slot").andExpect(status().isCreated());

		mvc.perform(get("/api/slots/availability").param("stationId", String.valueOf(s)).param("date", "2030-01-15"))
			// started slots are never reported as having free chargers
			.andExpect(jsonPath("$.slots[0].status").value("STARTED"))
			.andExpect(jsonPath("$.slots[0].available").value(0))
			.andExpect(jsonPath("$.slots[0].bookable").value(false))
			.andExpect(jsonPath("$.slots[5].status").value("STARTED"))      // 05:00-06:00, now 05:30
			.andExpect(jsonPath("$.slots[5].available").value(0))
			.andExpect(jsonPath("$.slots[6].status").value("AVAILABLE"))
			.andExpect(jsonPath("$.slots[6].available").value(1))
			.andExpect(jsonPath("$.slots[6].bookable").value(true))
			.andExpect(jsonPath("$.slots[10].status").value("FULL"))
			.andExpect(jsonPath("$.slots[10].booked").value(1))
			.andExpect(jsonPath("$.slots[10].available").value(0))
			.andExpect(jsonPath("$.slots[10].bookable").value(false));

		// the window closes at NOW + 14 days = 2030-01-29 05:30 local
		mvc.perform(get("/api/slots/availability").param("stationId", String.valueOf(s)).param("date", "2030-01-29"))
			.andExpect(jsonPath("$.slots[5].status").value("AVAILABLE"))
			.andExpect(jsonPath("$.slots[6].status").value("NOT_OPEN"))
			.andExpect(jsonPath("$.slots[6].available").value(0));
		// booking creation applies the same rules as the reported statuses
		book(s, "2030-01-29T06:00:00+05:30", "Too early").andExpect(status().isBadRequest());
		book(s, "2030-01-29T05:00:00+05:30", "In window").andExpect(status().isCreated());
		book(s, "2030-01-15T05:00:00+05:30", "Started").andExpect(status().isBadRequest());
	}

	@Test
	void cancellingFreesTheChargerAndKeepsTheRecord() throws Exception {
		long s = station(1, "120.00");
		long first = bookId(s, "2030-01-16T10:00:00+05:30", "First");
		book(s, "2030-01-16T10:00:00+05:30", "Second").andExpect(status().isConflict())
			.andExpect(jsonPath("$.title").value("Slot unavailable"));

		cancel(first)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.id").value(first))
			.andExpect(jsonPath("$.status").value("CANCELLED"))
			.andExpect(jsonPath("$.finalPrice").value(138.0));
		var row = jdbc.queryForMap("SELECT status, final_price, customer_name FROM bookings WHERE id = ?", first);
		assertThat(row.get("status")).isEqualTo("CANCELLED");                  // not deleted
		assertThat(row.get("final_price").toString()).isEqualTo("138.00");     // snapshot unchanged
		assertThat(row.get("customer_name")).isEqualTo("First");

		mvc.perform(get("/api/slots/availability").param("stationId", String.valueOf(s)).param("date", "2030-01-16"))
			.andExpect(jsonPath("$.slots[10].booked").value(0))
			.andExpect(jsonPath("$.slots[10].status").value("AVAILABLE"));
		book(s, "2030-01-16T10:00:00+05:30", "Second").andExpect(status().isCreated());
		assertThat(bookingsAt(s)).isEqualTo(2);
	}

	@Test
	void cancellingTwiceIsIdempotent() throws Exception {
		long s = station(2, "100.00");
		long id = bookId(s, "2030-01-16T10:00:00+05:30", "Twice");
		cancel(id).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("CANCELLED"));
		cancel(id).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("CANCELLED"));
		assertThat(statusOf(id)).isEqualTo("CANCELLED");
		assertThat(bookingsAt(s)).isEqualTo(1);
	}

	@Test
	void cancellationValidatesTheBooking() throws Exception {
		cancel(999999999L).andExpect(status().isNotFound()).andExpect(jsonPath("$.title").value("Not found"));
		mvc.perform(post("/api/bookings/0/cancel")).andExpect(status().isBadRequest());
		mvc.perform(post("/api/bookings/abc/cancel")).andExpect(status().isBadRequest());
	}

	@Test
	void cannotCancelABookingWhoseSlotHasStarted() throws Exception {
		long s = station(2, "100.00");
		// a booking whose slot started before NOW (inserted directly; the API would refuse to create it)
		jdbc.update("""
				INSERT INTO bookings (station_id, customer_name, start_time, end_time, status, base_price, price_multiplier,
				  final_price, currency, predicted_utilization, congestion_level, forecast_mode, forecast_reference_time,
				  model_id, created_at)
				VALUES (?, 'Earlier', '2030-01-14 23:30:00', '2030-01-15 00:30:00', 'CONFIRMED', 100, 1.15, 115, 'INR',
				  0.5, 'MEDIUM', 'historical_replay', '2020-02-03 22:00:00', 'm', UTC_TIMESTAMP(6))""", s);
		long id = jdbc.queryForObject("SELECT id FROM bookings WHERE station_id = ? AND customer_name = 'Earlier'",
				Long.class, s);
		cancel(id).andExpect(status().isConflict()).andExpect(jsonPath("$.title").value("Cancellation not allowed"));
		assertThat(statusOf(id)).isEqualTo("CONFIRMED");
	}

	@Test
	void concurrentCancellationsLeaveOneConsistentResult() throws Exception {
		long s = station(1, "100.00");
		long id = bookId(s, "2030-01-16T18:00:00+05:30", "Racer");
		List<Future<String>> results = race(6, i -> service.cancel(id).status().name());
		for (Future<String> r : results) {
			assertThat(r.get()).isEqualTo("CANCELLED");
		}
		assertThat(statusOf(id)).isEqualTo("CANCELLED");
		assertThat(bookingsAt(s)).isEqualTo(1);
	}

	@Test
	void sameCustomerCannotBookTheSameSlotTwice() throws Exception {
		long s = station(4, "100.00");
		long other = station(4, "100.00");
		book(s, "2030-01-16T10:00:00+05:30", "Ravi Kumar").andExpect(status().isCreated());
		book(s, "2030-01-16T10:00:00+05:30", "Ravi Kumar")
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.title").value("Duplicate booking"));
		// same person written differently (case and spacing) is still a duplicate
		book(s, "2030-01-16T10:00:00+05:30", "  ravi   KUMAR ").andExpect(status().isConflict());
		// different customer, different hour or different station are allowed
		book(s, "2030-01-16T10:00:00+05:30", "Asha").andExpect(status().isCreated());
		book(s, "2030-01-16T11:00:00+05:30", "Ravi Kumar").andExpect(status().isCreated());
		book(other, "2030-01-16T10:00:00+05:30", "Ravi Kumar").andExpect(status().isCreated());
		assertThat(bookingsAt(s)).isEqualTo(3);
		assertThat(bookingsAt(other)).isEqualTo(1);
	}

	@Test
	void customerNameIsStoredNormalised() throws Exception {
		long s = station(2, "100.00");
		book(s, "2030-01-16T10:00:00+05:30", "  Priya    Sharma ").andExpect(status().isCreated())
			.andExpect(jsonPath("$.customerName").value("Priya Sharma"));
	}

	@Test
	void customerCanRebookAfterCancelling() throws Exception {
		long s = station(2, "100.00");
		long id = bookId(s, "2030-01-16T10:00:00+05:30", "Meena");
		cancel(id).andExpect(status().isOk());
		book(s, "2030-01-16T10:00:00+05:30", "Meena").andExpect(status().isCreated());
		assertThat(jdbc.queryForList("SELECT status FROM bookings WHERE station_id = ? ORDER BY id", String.class, s))
			.containsExactly("CANCELLED", "CONFIRMED");
	}

	@Test
	void concurrentDuplicateRequestsCreateOnlyOneBooking() throws Exception {
		long s = station(4, "100.00");   // capacity is not the limit here; the duplicate rule is
		List<Future<String>> results = race(8, i -> {
			try {
				service.create(new CreateBookingRequest(s, "Same Person",
						OffsetDateTime.parse("2030-01-16T18:00:00+05:30"), null));
				return "created";
			}
			catch (DuplicateBookingException ex) {
				return "duplicate";
			}
		});
		List<String> outcomes = new ArrayList<>();
		for (Future<String> r : results) {
			outcomes.add(r.get());
		}
		assertThat(outcomes).filteredOn("created"::equals).hasSize(1);
		assertThat(outcomes).filteredOn("duplicate"::equals).hasSize(7);
		assertThat(bookingsAt(s)).isEqualTo(1);
	}

	/** Starts {@code threads} tasks at the same moment and returns their futures. */
	private static <T> List<Future<T>> race(int threads, IntFunction<T> task) throws InterruptedException {
		CountDownLatch ready = new CountDownLatch(threads);
		CountDownLatch go = new CountDownLatch(1);
		ExecutorService pool = Executors.newFixedThreadPool(threads);
		List<Future<T>> results = new ArrayList<>();
		for (int i = 0; i < threads; i++) {
			int n = i;
			results.add(pool.submit(() -> {
				ready.countDown();
				go.await();
				return task.apply(n);
			}));
		}
		ready.await();
		go.countDown();
		pool.shutdown();
		return results;
	}

}
