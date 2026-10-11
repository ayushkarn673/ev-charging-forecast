package com.evcharge.backend.forecast;

/** The ML service could not be reached or failed (HTTP 503 to clients). */
public class ForecastUnavailableException extends RuntimeException {

	public ForecastUnavailableException(String message, Throwable cause) {
		super(message, cause);
	}

}
