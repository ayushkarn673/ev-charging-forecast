package com.evcharge.backend.booking;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;

import jakarta.validation.constraints.Positive;

import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.evcharge.backend.common.BookingRejectedException;
import com.evcharge.backend.common.NotFoundException;
import com.evcharge.backend.config.BookingProperties;
import com.evcharge.backend.station.Station;
import com.evcharge.backend.station.StationRepository;

/** Hour-by-hour availability of a station for one local calendar day. */
@RestController
@RequestMapping("/api/slots")
public class SlotAvailabilityController {

	private final StationRepository stations;
	private final BookingRepository bookings;
	private final BookingProperties properties;
	private final Clock clock;

	public SlotAvailabilityController(StationRepository stations, BookingRepository bookings,
			BookingProperties properties, Clock clock) {
		this.stations = stations;
		this.bookings = bookings;
		this.properties = properties;
		this.clock = clock;
	}

	public record SlotResponse(OffsetDateTime startTime, OffsetDateTime endTime, long booked, long available,
			boolean bookable) {
	}

	public record AvailabilityResponse(Long stationId, String stationCode, LocalDate date, String timeZone,
			int capacity, BigDecimal basePricePerHour, String currency, List<SlotResponse> slots) {
	}

	@GetMapping("/availability")
	@Transactional(readOnly = true)
	public AvailabilityResponse availability(@RequestParam @Positive Long stationId,
			@RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date) {
		Station station = stations.findById(stationId)
			.orElseThrow(() -> new NotFoundException("Station " + stationId + " does not exist"));
		ZoneId zone = station.getZoneId();
		Instant now = clock.instant();
		LocalDate today = LocalDate.ofInstant(now, zone);
		if (date.isBefore(today.minusDays(1)) || date.isAfter(today.plusDays(properties.maxDaysAhead()))) {
			throw new BookingRejectedException("date must be between " + today.minusDays(1) + " and "
					+ today.plusDays(properties.maxDaysAhead()) + " (station time zone " + zone + ")");
		}

		Instant dayStart = date.atStartOfDay(zone).toInstant();
		Instant dayEnd = date.plusDays(1).atStartOfDay(zone).toInstant();
		Instant horizon = now.plus(Duration.ofDays(properties.maxDaysAhead()));
		List<Booking> confirmed = bookings.findOverlapping(stationId, BookingStatus.CONFIRMED, dayStart, dayEnd);

		List<SlotResponse> slots = HourlySlots.starts(dayStart, dayEnd).stream().map(start -> {
			long booked = HourlySlots.bookedIn(start, confirmed);
			long available = Math.max(0, station.getCapacity() - booked);
			boolean bookable = available > 0 && start.isAfter(now) && !start.isAfter(horizon);
			return new SlotResponse(start.atZone(zone).toOffsetDateTime(),
					start.plus(HourlySlots.SLOT).atZone(zone).toOffsetDateTime(), booked, available, bookable);
		}).toList();

		return new AvailabilityResponse(station.getId(), station.getCode(), date, zone.getId(), station.getCapacity(),
				station.getBasePricePerHour(), properties.currency(), slots);
	}

}
