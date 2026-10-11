package com.evcharge.backend.forecast;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;

import org.springframework.stereotype.Component;

/**
 * Maps a booking slot (any future date) to the historical-replay hour whose LSTM forecast is used as
 * its demand signal: same weekday and same local hour, inside the configured test-period week.
 * This is a documented proxy, not a forecast for the slot's real date.
 */
@Component
public class ReplayMapping {

	private final ForecastProperties properties;

	public ReplayMapping(ForecastProperties properties) {
		this.properties = properties;
	}

	public OffsetDateTime replayTimeFor(Instant slotStart, ZoneId stationZone) {
		ZonedDateTime local = slotStart.atZone(stationZone);
		int daysFromMonday = local.getDayOfWeek().getValue() - 1;
		LocalDateTime replayLocal = properties.replayWeekStart().plusDays(daysFromMonday).atTime(local.getHour(), 0);
		return replayLocal.atZone(properties.replayZone()).toOffsetDateTime();
	}

	public String describe(Instant slotStart, ZoneId stationZone) {
		ZonedDateTime local = slotStart.atZone(stationZone);
		return "Demand signal for this " + local.getDayOfWeek() + " " + "%02d:00".formatted(local.getHour())
				+ " slot: LSTM historical-replay forecast for the same weekday and hour of the Caltech ACN "
				+ "test-period week starting " + properties.replayWeekStart() + " (" + properties.replayZone()
				+ "). It is not a live forecast for the slot's own date.";
	}

}
