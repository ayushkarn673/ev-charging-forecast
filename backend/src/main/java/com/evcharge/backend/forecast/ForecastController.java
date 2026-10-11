package com.evcharge.backend.forecast;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.Map;

import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.evcharge.backend.forecast.ForecastDtos.MlHealth;
import com.evcharge.backend.forecast.ForecastDtos.NextHourResponse;
import com.evcharge.backend.pricing.CongestionLevel;
import com.evcharge.backend.pricing.DemandPricingPolicy;
import com.evcharge.backend.pricing.PricingProperties;
import com.evcharge.backend.pricing.SlotPricingService;

/**
 * Dashboard access to the FastAPI LSTM service. Responses are the model service's own output
 * (historical replay, clearly flagged by {@code mode} and {@code isSimulation}); nothing is computed
 * or substituted here except the congestion band from the pricing policy.
 */
@RestController
@RequestMapping("/api/forecast")
public class ForecastController {

	private final MlServiceClient ml;
	private final DemandPricingPolicy policy;
	private final PricingProperties pricingProperties;

	public ForecastController(MlServiceClient ml, DemandPricingPolicy policy, PricingProperties pricingProperties) {
		this.ml = ml;
		this.policy = policy;
		this.pricingProperties = pricingProperties;
	}

	public record ForecastView(String source, NextHourResponse forecast, CongestionLevel congestionLevel,
			PricingProperties pricingPolicy) {
	}

	/** One-hour-ahead forecast for a historical replay time (see /api/forecast/model-info for the range). */
	@GetMapping("/next-hour")
	public ForecastView nextHour(
			@RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime forecastTime) {
		NextHourResponse forecast = ml.predictNextHour(forecastTime);
		return new ForecastView(SlotPricingService.FORECAST_SOURCE, forecast,
				policy.classify(forecast.prediction().utilization()), pricingProperties);
	}

	@GetMapping("/status")
	public MlHealth status() {
		return ml.health();
	}

	@GetMapping("/model-info")
	public Map<String, Object> modelInfo() {
		return ml.modelInfo();
	}

	/** Saved test-set metrics (Phase 3 evaluation), served by the ML service. */
	@GetMapping("/evaluation")
	public Map<String, Object> evaluation() {
		return ml.evaluation();
	}

	/** Saved actual-vs-predicted test-set series for a date range (no new inference). */
	@GetMapping("/evaluation/series")
	public Map<String, Object> evaluationSeries(
			@RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
			@RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to) {
		return ml.evaluationSeries(from, to);
	}

}
