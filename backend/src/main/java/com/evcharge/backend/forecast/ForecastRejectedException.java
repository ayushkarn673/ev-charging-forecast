package com.evcharge.backend.forecast;

/** The ML service refused the request, e.g. a forecast time outside the replay range (HTTP 422). */
public class ForecastRejectedException extends RuntimeException {

	private final String code;

	public ForecastRejectedException(String code, String message) {
		super(message);
		this.code = code;
	}

	public String getCode() {
		return code;
	}

}
