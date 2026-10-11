package com.evcharge.backend.forecast;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;

import org.junit.jupiter.api.Test;

class ReplayMappingTest {

	private final ReplayMapping mapping = new ReplayMapping(
			new ForecastProperties(LocalDate.parse("2020-02-03"), ZoneId.of("America/Los_Angeles")));

	private static final ZoneId IST = ZoneId.of("Asia/Kolkata");

	@Test
	void mapsToSameWeekdayAndLocalHourOfTheReplayWeek() {
		// Wednesday 2030-01-16 10:00 IST -> Wednesday 2020-02-05 10:00 PST
		Instant slot = OffsetDateTime.parse("2030-01-16T10:00:00+05:30").toInstant();
		assertThat(mapping.replayTimeFor(slot, IST)).isEqualTo(OffsetDateTime.parse("2020-02-05T10:00:00-08:00"));
		// Monday 00:00 and Sunday 23:00 stay inside the week
		assertThat(mapping.replayTimeFor(OffsetDateTime.parse("2030-01-14T00:00:00+05:30").toInstant(), IST))
			.isEqualTo(OffsetDateTime.parse("2020-02-03T00:00:00-08:00"));
		assertThat(mapping.replayTimeFor(OffsetDateTime.parse("2030-01-20T23:00:00+05:30").toInstant(), IST))
			.isEqualTo(OffsetDateTime.parse("2020-02-09T23:00:00-08:00"));
	}

	@Test
	void descriptionSaysItIsNotALiveForecast() {
		Instant slot = OffsetDateTime.parse("2030-01-16T10:00:00+05:30").toInstant();
		assertThat(mapping.describe(slot, IST)).contains("historical-replay", "not a live forecast", "2020-02-03");
	}

	@Test
	void replayWeekMustStartOnMonday() {
		assertThatThrownBy(() -> new ForecastProperties(LocalDate.parse("2020-02-04"), ZoneId.of("UTC")))
			.isInstanceOf(IllegalArgumentException.class);
	}

}
