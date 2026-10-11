package com.evcharge.backend.pricing;

import java.math.BigDecimal;
import java.math.RoundingMode;

import org.springframework.stereotype.Component;

/**
 * Turns a forecast utilization into a price: classify the congestion band, then apply that band's
 * multiplier to the base price. Pure and deterministic - no I/O - so it is unit-tested directly.
 */
@Component
public class DemandPricingPolicy {

	public record PriceBreakdown(BigDecimal basePrice, BigDecimal utilization, CongestionLevel congestionLevel,
			BigDecimal multiplier, BigDecimal finalPrice) {
	}

	private final PricingProperties properties;

	public DemandPricingPolicy(PricingProperties properties) {
		this.properties = properties;
	}

	public CongestionLevel classify(double utilization) {
		BigDecimal u = checkedUtilization(utilization);
		PricingProperties.Thresholds t = properties.thresholds();
		if (u.compareTo(t.veryHigh()) >= 0) {
			return CongestionLevel.VERY_HIGH;
		}
		if (u.compareTo(t.high()) >= 0) {
			return CongestionLevel.HIGH;
		}
		if (u.compareTo(t.medium()) >= 0) {
			return CongestionLevel.MEDIUM;
		}
		return CongestionLevel.LOW;
	}

	public BigDecimal multiplierFor(CongestionLevel level) {
		PricingProperties.Multipliers m = properties.multipliers();
		return switch (level) {
			case LOW -> m.low();
			case MEDIUM -> m.medium();
			case HIGH -> m.high();
			case VERY_HIGH -> m.veryHigh();
		};
	}

	public PriceBreakdown price(BigDecimal basePrice, double utilization) {
		if (basePrice == null || basePrice.signum() < 0) {
			throw new IllegalArgumentException("basePrice must be >= 0");
		}
		CongestionLevel level = classify(utilization);
		BigDecimal multiplier = multiplierFor(level);
		BigDecimal finalPrice = basePrice.multiply(multiplier).setScale(2, RoundingMode.HALF_UP);
		return new PriceBreakdown(basePrice.setScale(2, RoundingMode.HALF_UP),
				checkedUtilization(utilization).setScale(6, RoundingMode.HALF_UP), level, multiplier, finalPrice);
	}

	private static BigDecimal checkedUtilization(double utilization) {
		if (!Double.isFinite(utilization) || utilization < 0 || utilization > 1) {
			throw new IllegalArgumentException("utilization must be a number between 0 and 1, got " + utilization);
		}
		return BigDecimal.valueOf(utilization);
	}

}
