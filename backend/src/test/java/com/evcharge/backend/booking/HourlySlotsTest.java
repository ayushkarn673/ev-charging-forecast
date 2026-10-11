package com.evcharge.backend.booking;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;

import org.junit.jupiter.api.Test;

import com.evcharge.backend.pricing.CongestionLevel;

class HourlySlotsTest {

	private static final Instant T10 = Instant.parse("2030-01-16T10:00:00Z");

	private static Booking booking(String start, String end) {
		return new Booking(null, "x", Instant.parse(start), Instant.parse(end), BigDecimal.ONE, BigDecimal.ONE,
				BigDecimal.ONE, "INR", BigDecimal.ZERO, CongestionLevel.LOW, "historical_replay", T10, "m", T10);
	}

	@Test
	void startsCoverTheRangeInOneHourSteps() {
		assertThat(HourlySlots.starts(T10, T10.plusSeconds(3 * 3600)))
			.containsExactly(T10, T10.plusSeconds(3600), T10.plusSeconds(7200));
		assertThat(HourlySlots.starts(T10, T10)).isEmpty();
	}

	@Test
	void overlapUsesHalfOpenIntervals() {
		List<Booking> bookings = List.of(
				booking("2030-01-16T09:00:00Z", "2030-01-16T10:00:00Z"),   // ends exactly when the slot starts
				booking("2030-01-16T10:00:00Z", "2030-01-16T11:00:00Z"),   // the slot itself
				booking("2030-01-16T11:00:00Z", "2030-01-16T12:00:00Z"));  // starts when the slot ends
		assertThat(HourlySlots.bookedIn(T10, bookings)).isEqualTo(1);
		assertThat(HourlySlots.bookedIn(T10.minusSeconds(3600), bookings)).isEqualTo(1);
		assertThat(HourlySlots.bookedIn(T10.plusSeconds(7200), bookings)).isZero();
	}

}
