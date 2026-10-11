package com.evcharge.backend.forecast;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import com.evcharge.backend.config.MlServiceProperties;
import com.sun.net.httpserver.HttpServer;

/** Client behaviour against a local stub HTTP server (no FastAPI needed). */
class MlServiceClientTest {

	private HttpServer server;
	private final AtomicReference<String> lastRequestBody = new AtomicReference<>();
	private final AtomicReference<String> lastProtocolUpgrade = new AtomicReference<>();

	private MlServiceClient client(int status, String json) throws IOException {
		server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
		server.createContext("/", exchange -> {
			lastProtocolUpgrade.set(exchange.getRequestHeaders().getFirst("Upgrade"));
			lastRequestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8)
					+ " " + exchange.getRequestURI());
			byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
			exchange.getResponseHeaders().add("Content-Type", "application/json");
			exchange.sendResponseHeaders(status, bytes.length);
			try (OutputStream out = exchange.getResponseBody()) {
				out.write(bytes);
			}
		});
		server.start();
		return new MlServiceClient(new MlServiceProperties(
				URI.create("http://127.0.0.1:" + server.getAddress().getPort()), Duration.ofSeconds(2),
				Duration.ofSeconds(2)));
	}

	@AfterEach
	void stop() {
		if (server != null) {
			server.stop(0);
		}
	}

	@Test
	void parsesNextHourForecast() throws IOException {
		MlServiceClient c = client(200, """
				{"mode":"historical_replay","isSimulation":true,"notice":"Historical replay","siteId":"caltech",
				 "installedCapacitySpaces":54,"forecastTime":"2020-02-05T10:00:00-08:00","forecastTimeUtc":"2020-02-05T18:00:00Z",
				 "targetStart":"2020-02-05T10:00:00-08:00","targetEnd":"2020-02-05T11:00:00-08:00","horizonHours":1,
				 "inputs":{"sequenceLength":24},
				 "prediction":{"utilization":0.4321,"utilizationPercent":43.2,"estimatedOccupiedSpaces":23.33,
				   "estimatedOccupiedSpacesRounded":24,"estimatedAvailableSpacesRounded":30,"rawUtilization":0.4321},
				 "observedOutcome":null,"modelId":"ev_demand_lstm@sha256:abc","warnings":[{"code":"X","message":"y"}],
				 "someNewField":123}""");
		var r = c.predictNextHour(OffsetDateTime.parse("2020-02-05T10:00:00-08:00"));
		assertThat(r.mode()).isEqualTo("historical_replay");
		assertThat(r.isSimulation()).isTrue();
		assertThat(r.horizonHours()).isEqualTo(1);
		assertThat(r.prediction().utilization()).isEqualTo(0.4321);
		assertThat(r.prediction().estimatedAvailableSpacesRounded()).isEqualTo(30);
		assertThat(r.warnings()).extracting(ForecastDtos.Warning::code).containsExactly("X");
		assertThat(lastRequestBody.get()).contains("\"forecastTime\":\"2020-02-05T10:00:00-08:00\"", "\"siteId\":\"caltech\"",
				"/predict/next-hour");
		// uvicorn ignores the body of an h2c upgrade request, so the client must not ask for one
		assertThat(lastProtocolUpgrade.get()).isNull();
	}

	@Test
	void keepsFastApiReasonForRejectedRequests() throws IOException {
		MlServiceClient c = client(422, """
				{"code":"OUT_OF_RANGE","message":"forecastTime is after the historical dataset"}""");
		assertThatThrownBy(() -> c.predictNextHour(OffsetDateTime.parse("2026-01-01T10:00:00Z")))
			.isInstanceOfSatisfying(ForecastRejectedException.class, ex -> {
				assertThat(ex.getCode()).isEqualTo("OUT_OF_RANGE");
				assertThat(ex.getMessage()).contains("after the historical dataset");
			});
	}

	@Test
	void keepsFastApiValidationDetail() throws IOException {
		MlServiceClient c = client(422, """
				{"detail":[{"type":"value_error","msg":"forecastTime must be on an hour boundary"}]}""");
		assertThatThrownBy(() -> c.predictNextHour(OffsetDateTime.parse("2020-02-05T10:30:00-08:00")))
			.isInstanceOf(ForecastRejectedException.class).hasMessageContaining("hour boundary");
	}

	@Test
	void serverErrorMeansUnavailable() throws IOException {
		MlServiceClient c = client(500, "{\"detail\":\"boom\"}");
		assertThatThrownBy(c::health).isInstanceOf(ForecastUnavailableException.class);
	}

	@Test
	void connectionRefusedMeansUnavailable() throws IOException {
		int freePort;
		try (ServerSocket s = new ServerSocket(0)) {
			freePort = s.getLocalPort();
		}
		MlServiceClient c = new MlServiceClient(new MlServiceProperties(URI.create("http://127.0.0.1:" + freePort),
				Duration.ofSeconds(1), Duration.ofSeconds(1)));
		assertThatThrownBy(c::health).isInstanceOf(ForecastUnavailableException.class);
	}

	@Test
	void passesEvaluationRangeAsQueryParameters() throws IOException {
		MlServiceClient c = client(200, "{\"points\":[]}");
		assertThat(c.evaluationSeries(LocalDate.parse("2020-01-06"), LocalDate.parse("2020-01-07"))).containsKey("points");
		assertThat(lastRequestBody.get()).contains("/evaluation/series?start=2020-01-06&end=2020-01-07");
	}

}
