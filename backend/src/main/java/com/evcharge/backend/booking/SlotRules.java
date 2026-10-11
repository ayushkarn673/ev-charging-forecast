package com.evcharge.backend.booking;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;

import org.springframework.stereotype.Component;

import com.evcharge.backend.common.BookingRejectedException;
import com.evcharge.backend.config.BookingProperties;
import com.evcharge.backend.station.Station;

/** Server-side rules for a bookable slot, shared by price quotes and bookings. */
@Component
public class SlotRules {

	private final BookingProperties properties;
	private final Clock clock;

	public SlotRules(BookingProperties properties, Clock clock) {
		this.properties = properties;
		this.clock = clock;
	}

	/** Returns the slot start as an instant, or throws if it is not a bookable one-hour slot. */
	public Instant validateStart(Station station, OffsetDateTime startTime) {
		if (startTime == null) {
			throw new BookingRejectedException("startTime is required");
		}
		ZoneId zone = station.getZoneId();
		Instant start = startTime.toInstant();
		ZonedDateTime local = start.atZone(zone);
		if (local.getMinute() != 0 || local.getSecond() != 0 || local.getNano() != 0) {
			throw new BookingRejectedException("startTime must be on a whole hour in the station time zone (" + zone
					+ "), e.g. " + local.withMinute(0).withSecond(0).withNano(0).plusHours(1).toOffsetDateTime());
		}
		Instant now = clock.instant();
		if (!start.isAfter(now)) {
			throw new BookingRejectedException("startTime must be in the future");
		}
		if (start.isAfter(now.plus(Duration.ofDays(properties.maxDaysAhead())))) {
			throw new BookingRejectedException("startTime must be at most " + properties.maxDaysAhead() + " days ahead");
		}
		return start;
	}

}
