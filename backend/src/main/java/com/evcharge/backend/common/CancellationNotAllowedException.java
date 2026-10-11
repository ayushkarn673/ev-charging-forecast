package com.evcharge.backend.common;

/** The booking exists but can no longer be cancelled, e.g. its slot has started (HTTP 409). */
public class CancellationNotAllowedException extends RuntimeException {

	public CancellationNotAllowedException(String message) {
		super(message);
	}

}
