package com.evcharge.backend.forecast;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.Objects;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * How a booking slot is mapped to a historical-replay forecast, bound from {@code evcharge.forecast.*}.
 *
 * @param replayWeekStart a Monday in the model's test period
 * @param replayZone time zone of the ACN site (the replay hour uses the slot's local wall-clock hour)
 */
@ConfigurationProperties("evcharge.forecast")
public record ForecastProperties(LocalDate replayWeekStart, ZoneId replayZone) {

	public ForecastProperties {
		Objects.requireNonNull(replayWeekStart, "evcharge.forecast.replay-week-start is required");
		Objects.requireNonNull(replayZone, "evcharge.forecast.replay-zone is required");
		if (replayWeekStart.getDayOfWeek() != DayOfWeek.MONDAY) {
			throw new IllegalArgumentException("evcharge.forecast.replay-week-start must be a Monday");
		}
	}

}
