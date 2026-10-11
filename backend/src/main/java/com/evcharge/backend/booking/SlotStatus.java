package com.evcharge.backend.booking;

/**
 * Why a slot can or cannot be booked. Uses the same rules as booking creation ({@link SlotRules}):
 * a slot is bookable only if it starts in the future, within the booking window, with a free charger.
 */
public enum SlotStatus {

	/** Starts in the future, inside the booking window, at least one charger free. */
	AVAILABLE,
	/** Starts in the future, inside the booking window, every charger booked. */
	FULL,
	/** Already started (in progress or over); can no longer be booked. */
	STARTED,
	/** Starts after the booking window (max-days-ahead) closes; cannot be booked yet. */
	NOT_OPEN

}
