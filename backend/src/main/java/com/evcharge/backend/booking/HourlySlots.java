package com.evcharge.backend.booking;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

/** Slot arithmetic shared by availability and booking: slots are consecutive one-hour intervals. */
final class HourlySlots {

	static final Duration SLOT = Duration.ofHours(1);

	private HourlySlots() {
	}

	/** Start instants of the one-hour slots covering [from, to). Instant-based, so DST-safe. */
	static List<Instant> starts(Instant from, Instant to) {
		List<Instant> result = new ArrayList<>();
		for (Instant t = from; t.isBefore(to); t = t.plus(SLOT)) {
			result.add(t);
		}
		return result;
	}

	/** Number of bookings that overlap the slot starting at {@code slotStart}. */
	static long bookedIn(Instant slotStart, Collection<Booking> bookings) {
		Instant slotEnd = slotStart.plus(SLOT);
		return bookings.stream()
			.filter(b -> b.getStartTime().isBefore(slotEnd) && b.getEndTime().isAfter(slotStart))
			.count();
	}

}
