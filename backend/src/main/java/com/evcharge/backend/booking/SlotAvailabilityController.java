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

import com.evcharge.backend.common.InvalidRequestException;
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

	/**
	 * @param booked confirmed bookings in the slot
	 * @param available chargers that can still be booked now: capacity - booked for an AVAILABLE or
	 * FULL slot, and 0 for a STARTED or NOT_OPEN slot (it cannot be booked at all)
	 * @param bookable true only when {@code status} is AVAILABLE
	 */
	public record SlotResponse(OffsetDateTime startTime, OffsetDateTime endTime, long booked, long available,
			boolean bookable, SlotStatus status) {
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
		// "today" is the station's local calendar date: past dates are rejected, today is allowed
		// (its started slots are reported as STARTED).
		LocalDate today = LocalDate.ofInstant(now, zone);
		LocalDate lastDay = today.plusDays(properties.maxDaysAhead());
		if (date.isBefore(today)) {
			throw new InvalidRequestException("date " + date + " is in the past; choose a date from " + today
					+ " to " + lastDay + " (station time zone " + zone + ")");
		}
		if (date.isAfter(lastDay)) {
			throw new InvalidRequestException("date " + date + " is beyond the " + properties.maxDaysAhead()
					+ "-day booking window; choose a date from " + today + " to " + lastDay + " (station time zone "
					+ zone + ")");
		}

		Instant dayStart = date.atStartOfDay(zone).toInstant();
		Instant dayEnd = date.plusDays(1).atStartOfDay(zone).toInstant();
		Instant horizon = now.plus(Duration.ofDays(properties.maxDaysAhead()));
		List<Booking> confirmed = bookings.findOverlapping(stationId, BookingStatus.CONFIRMED, dayStart, dayEnd);

		List<SlotResponse> slots = HourlySlots.starts(dayStart, dayEnd).stream().map(start -> {
			long booked = HourlySlots.bookedIn(start, confirmed);
			long free = Math.max(0, station.getCapacity() - booked);
			SlotStatus status = !start.isAfter(now) ? SlotStatus.STARTED
					: start.isAfter(horizon) ? SlotStatus.NOT_OPEN : free == 0 ? SlotStatus.FULL : SlotStatus.AVAILABLE;
			long available = status == SlotStatus.STARTED || status == SlotStatus.NOT_OPEN ? 0 : free;
			return new SlotResponse(start.atZone(zone).toOffsetDateTime(),
					start.plus(HourlySlots.SLOT).atZone(zone).toOffsetDateTime(), booked, available,
					status == SlotStatus.AVAILABLE, status);
		}).toList();

		return new AvailabilityResponse(station.getId(), station.getCode(), date, zone.getId(), station.getCapacity(),
				station.getBasePricePerHour(), properties.currency(), slots);
	}

}
