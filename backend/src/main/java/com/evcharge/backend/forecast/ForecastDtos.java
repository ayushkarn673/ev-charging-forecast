package com.evcharge.backend.forecast;

import java.util.List;

/**
 * Mirrors of the FastAPI ml-service JSON (camelCase). Only fields the backend uses are declared;
 * unknown fields are ignored so FastAPI can evolve without breaking the backend.
 */
public final class ForecastDtos {

	private ForecastDtos() {
	}

	public record NextHourRequest(String siteId, String forecastTime) {
	}

	public record Prediction(double utilization, double utilizationPercent, double estimatedOccupiedSpaces,
			int estimatedOccupiedSpacesRounded, int estimatedAvailableSpacesRounded, double rawUtilization) {
	}

	public record ObservedOutcome(double utilization, double utilizationPercent, double averageOccupiedSpaces,
			String note) {
	}

	public record Warning(String code, String message) {
	}

	public record NextHourResponse(String mode, boolean isSimulation, String notice, String siteId,
			int installedCapacitySpaces, String forecastTime, String forecastTimeUtc, String targetStart,
			String targetEnd, int horizonHours, Prediction prediction, ObservedOutcome observedOutcome, String modelId,
			List<Warning> warnings) {
	}

	public record MlHealth(String status, boolean modelLoaded, String modelId, int observationsLoaded) {
	}

}
