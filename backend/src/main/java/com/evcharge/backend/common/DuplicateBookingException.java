package com.evcharge.backend.common;

/** The same customer already holds a confirmed booking for this station and slot (HTTP 409). */
public class DuplicateBookingException extends RuntimeException {

	public DuplicateBookingException(String message) {
		super(message);
	}

}
