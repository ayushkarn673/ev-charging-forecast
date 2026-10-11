package com.evcharge.backend.common;

/** A query parameter is well-formed but outside the allowed range, e.g. a past date (HTTP 400). */
public class InvalidRequestException extends RuntimeException {

	public InvalidRequestException(String message) {
		super(message);
	}

}
