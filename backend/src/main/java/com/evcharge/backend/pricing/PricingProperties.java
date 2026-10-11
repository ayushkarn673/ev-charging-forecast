package com.evcharge.backend.pricing;

import java.math.BigDecimal;
import java.util.Objects;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Demand-pricing policy, bound from {@code evcharge.pricing.*}. Thresholds are lower bounds
 * (inclusive) on predicted utilization (0..1); each band has a price multiplier. These rules are a
 * business policy chosen by the operator - they are not learned by the LSTM.
 */
@ConfigurationProperties("evcharge.pricing")
public record PricingProperties(Thresholds thresholds, Multipliers multipliers) {

	/** Utilization at which each band starts. Must satisfy 0 < medium < high < veryHigh <= 1. */
	public record Thresholds(BigDecimal medium, BigDecimal high, BigDecimal veryHigh) {
	}

	/** Price multipliers per band. Must be > 0, <= 5 and non-decreasing from low to veryHigh. */
	public record Multipliers(BigDecimal low, BigDecimal medium, BigDecimal high, BigDecimal veryHigh) {
	}

	public PricingProperties {
		Objects.requireNonNull(thresholds, "evcharge.pricing.thresholds is required");
		Objects.requireNonNull(multipliers, "evcharge.pricing.multipliers is required");
		BigDecimal[] t = { thresholds.medium(), thresholds.high(), thresholds.veryHigh() };
		BigDecimal[] m = { multipliers.low(), multipliers.medium(), multipliers.high(), multipliers.veryHigh() };
		for (BigDecimal v : t) {
			Objects.requireNonNull(v, "every evcharge.pricing.thresholds value is required");
		}
		for (BigDecimal v : m) {
			Objects.requireNonNull(v, "every evcharge.pricing.multipliers value is required");
		}
		if (t[0].signum() <= 0 || t[0].compareTo(t[1]) >= 0 || t[1].compareTo(t[2]) >= 0
				|| t[2].compareTo(BigDecimal.ONE) > 0) {
			throw new IllegalArgumentException(
					"evcharge.pricing.thresholds must satisfy 0 < medium < high < very-high <= 1, got " + thresholds);
		}
		BigDecimal max = BigDecimal.valueOf(5);
		for (int i = 0; i < m.length; i++) {
			if (m[i].signum() <= 0 || m[i].compareTo(max) > 0) {
				throw new IllegalArgumentException("evcharge.pricing.multipliers must be in (0, 5], got " + multipliers);
			}
			if (i > 0 && m[i].compareTo(m[i - 1]) < 0) {
				throw new IllegalArgumentException(
						"evcharge.pricing.multipliers must not decrease as congestion rises, got " + multipliers);
			}
		}
	}

}
