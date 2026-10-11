package com.evcharge.backend.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Booking rules, bound from {@code evcharge.booking.*}. A booking is always one one-hour slot,
 * matching the only forecast horizon the LSTM was validated for.
 */
@ConfigurationProperties("evcharge.booking")
public record BookingProperties(int maxDaysAhead, String currency) {

	public BookingProperties {
		if (maxDaysAhead < 1) {
			throw new IllegalArgumentException("evcharge.booking.max-days-ahead must be >= 1");
		}
		if (currency == null || !currency.matches("[A-Z]{3}")) {
			throw new IllegalArgumentException("evcharge.booking.currency must be a 3-letter ISO code");
		}
	}

}
