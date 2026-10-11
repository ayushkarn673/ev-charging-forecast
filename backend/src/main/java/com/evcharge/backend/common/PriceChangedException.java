package com.evcharge.backend.common;

/** The price the customer was shown no longer matches the server-side price (HTTP 409). */
public class PriceChangedException extends RuntimeException {

	public PriceChangedException(String message) {
		super(message);
	}

}
