package com.evcharge.backend.pricing;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

class DemandPricingPolicyTest {

	private static BigDecimal d(String v) {
		return new BigDecimal(v);
	}

	/** Same values as application.yml. */
	static PricingProperties defaults() {
		return new PricingProperties(new PricingProperties.Thresholds(d("0.40"), d("0.70"), d("0.90")),
				new PricingProperties.Multipliers(d("0.90"), d("1.15"), d("1.35"), d("1.60")));
	}

	private final DemandPricingPolicy policy = new DemandPricingPolicy(defaults());

	@ParameterizedTest(name = "utilization {0} -> {1}")
	@CsvSource({
			"0.0,       LOW",
			"0.25,      LOW",
			"0.399999,  LOW",
			"0.40,      MEDIUM",     // lower bound is inclusive
			"0.55,      MEDIUM",
			"0.699999,  MEDIUM",
			"0.70,      HIGH",
			"0.85,      HIGH",
			"0.899999,  HIGH",
			"0.90,      VERY_HIGH",
			"1.0,       VERY_HIGH" })
	void classifiesBandsWithInclusiveLowerBounds(double utilization, CongestionLevel expected) {
		assertThat(policy.classify(utilization)).isEqualTo(expected);
	}

	@ParameterizedTest(name = "base {0}, utilization {1} -> {2} x {3} = {4}")
	@CsvSource({
			"100.00, 0.10, LOW,       0.90, 90.00",
			"100.00, 0.40, MEDIUM,    1.15, 115.00",
			"120.00, 0.55, MEDIUM,    1.15, 138.00",
			"150.00, 0.75, HIGH,      1.35, 202.50",
			"100.00, 0.95, VERY_HIGH, 1.60, 160.00",
			"0.00,   0.95, VERY_HIGH, 1.60, 0.00" })
	void appliesTheBandMultiplier(String base, double utilization, CongestionLevel level, String multiplier,
			String finalPrice) {
		var p = policy.price(d(base), utilization);
		assertThat(p.congestionLevel()).isEqualTo(level);
		assertThat(p.multiplier()).isEqualByComparingTo(multiplier);
		assertThat(p.finalPrice()).isEqualByComparingTo(finalPrice);
		assertThat(p.finalPrice().scale()).isEqualTo(2);
		assertThat(p.basePrice()).isEqualByComparingTo(base);
		assertThat(p.utilization()).isEqualByComparingTo(BigDecimal.valueOf(utilization));
	}

	@Test
	void roundsHalfUpToTwoDecimals() {
		// 99.99 x 1.15 = 114.9885 -> 114.99
		assertThat(policy.price(d("99.99"), 0.5).finalPrice()).isEqualByComparingTo("114.99");
	}

	@Test
	void rejectsInvalidInputs() {
		assertThatThrownBy(() -> policy.price(d("100"), -0.01)).isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> policy.price(d("100"), 1.01)).isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> policy.price(d("100"), Double.NaN)).isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> policy.price(d("-1"), 0.5)).isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> policy.price(null, 0.5)).isInstanceOf(IllegalArgumentException.class);
	}

	@Test
	void rejectsInvalidConfiguration() {
		var m = defaults().multipliers();
		var t = defaults().thresholds();
		// thresholds not strictly increasing
		assertThatThrownBy(() -> new PricingProperties(new PricingProperties.Thresholds(d("0.70"), d("0.40"), d("0.90")), m))
			.isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> new PricingProperties(new PricingProperties.Thresholds(d("0.40"), d("0.40"), d("0.90")), m))
			.isInstanceOf(IllegalArgumentException.class);
		// out of range
		assertThatThrownBy(() -> new PricingProperties(new PricingProperties.Thresholds(d("0"), d("0.70"), d("0.90")), m))
			.isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> new PricingProperties(new PricingProperties.Thresholds(d("0.40"), d("0.70"), d("1.10")), m))
			.isInstanceOf(IllegalArgumentException.class);
		// multipliers decreasing, non-positive, too large, missing
		assertThatThrownBy(() -> new PricingProperties(t, new PricingProperties.Multipliers(d("1.20"), d("1.10"), d("1.35"), d("1.60"))))
			.isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> new PricingProperties(t, new PricingProperties.Multipliers(d("0"), d("1.15"), d("1.35"), d("1.60"))))
			.isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> new PricingProperties(t, new PricingProperties.Multipliers(d("0.9"), d("1.15"), d("1.35"), d("6"))))
			.isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> new PricingProperties(t, new PricingProperties.Multipliers(d("0.9"), null, d("1.35"), d("1.6"))))
			.isInstanceOf(NullPointerException.class);
		assertThatThrownBy(() -> new PricingProperties(null, m)).isInstanceOf(NullPointerException.class);
	}

	@Test
	void customThresholdsAreHonoured() {
		var custom = new DemandPricingPolicy(new PricingProperties(
				new PricingProperties.Thresholds(d("0.20"), d("0.50"), d("0.80")),
				new PricingProperties.Multipliers(d("1.00"), d("1.00"), d("2.00"), d("3.00"))));
		assertThat(custom.classify(0.20)).isEqualTo(CongestionLevel.MEDIUM);
		assertThat(custom.price(d("10"), 0.5).finalPrice()).isEqualByComparingTo("20.00");
	}

}
