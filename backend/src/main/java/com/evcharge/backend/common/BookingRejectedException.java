package com.evcharge.backend.common;

/** Booking request breaks a business rule (wrong time, too long, too far ahead...) (HTTP 400). */
public class BookingRejectedException extends RuntimeException {

	public BookingRejectedException(String message) {
		super(message);
	}

}
