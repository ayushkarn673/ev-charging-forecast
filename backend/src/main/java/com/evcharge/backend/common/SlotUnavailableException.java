package com.evcharge.backend.common;

/** Every charger is already booked for at least one requested hour (HTTP 409). */
public class SlotUnavailableException extends RuntimeException {

	public SlotUnavailableException(String message) {
		super(message);
	}

}
