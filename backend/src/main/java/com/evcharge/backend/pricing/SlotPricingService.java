package com.evcharge.backend.pricing;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;

import org.springframework.stereotype.Service;

import com.evcharge.backend.booking.SlotRules;
import com.evcharge.backend.common.NotFoundException;
import com.evcharge.backend.config.BookingProperties;
import com.evcharge.backend.forecast.ForecastDtos.NextHourResponse;
import com.evcharge.backend.forecast.ForecastDtos.Warning;
import com.evcharge.backend.forecast.MlServiceClient;
import com.evcharge.backend.forecast.ReplayMapping;
import com.evcharge.backend.pricing.DemandPricingPolicy.PriceBreakdown;
import com.evcharge.backend.station.Station;
import com.evcharge.backend.station.StationRepository;

/**
 * Prices one slot: maps it to its historical-replay hour, asks the FastAPI LSTM service for that
 * hour's forecast, and applies the demand-pricing policy to the returned utilization. If the
 * forecast cannot be obtained, no price is produced (no fallback numbers are invented).
 */
@Service
public class SlotPricingService {

	public static final String FORECAST_SOURCE = "LSTM (FastAPI ml-service)";

	/** What the forecast was, where it came from, and how the slot was mapped to it. */
	public record ForecastInfo(String source, String mode, boolean isSimulation, String modelId,
			OffsetDateTime replayForecastTime, String targetStart, String targetEnd, int horizonHours,
			double predictedUtilizationPercent, String mapping, String notice, List<Warning> warnings) {
	}

	public record SlotQuote(Long stationId, String stationCode, OffsetDateTime slotStart, OffsetDateTime slotEnd,
			String currency, PriceBreakdown price, ForecastInfo forecast) {
	}

	private final StationRepository stations;
	private final SlotRules slotRules;
	private final ReplayMapping replayMapping;
	private final MlServiceClient ml;
	private final DemandPricingPolicy policy;
	private final BookingProperties bookingProperties;

	public SlotPricingService(StationRepository stations, SlotRules slotRules, ReplayMapping replayMapping,
			MlServiceClient ml, DemandPricingPolicy policy, BookingProperties bookingProperties) {
		this.stations = stations;
		this.slotRules = slotRules;
		this.replayMapping = replayMapping;
		this.ml = ml;
		this.policy = policy;
		this.bookingProperties = bookingProperties;
	}

	public SlotQuote quote(Long stationId, OffsetDateTime startTime) {
		Station station = stations.findById(stationId)
			.orElseThrow(() -> new NotFoundException("Station " + stationId + " does not exist"));
		return quote(station, slotRules.validateStart(station, startTime));
	}

	public SlotQuote quote(Station station, Instant slotStart) {
		ZoneId zone = station.getZoneId();
		OffsetDateTime replayTime = replayMapping.replayTimeFor(slotStart, zone);
		NextHourResponse forecast = ml.predictNextHour(replayTime);
		PriceBreakdown price = policy.price(station.getBasePricePerHour(), forecast.prediction().utilization());
		ForecastInfo info = new ForecastInfo(FORECAST_SOURCE, forecast.mode(), forecast.isSimulation(),
				forecast.modelId(), replayTime, forecast.targetStart(), forecast.targetEnd(), forecast.horizonHours(),
				forecast.prediction().utilizationPercent(), replayMapping.describe(slotStart, zone), forecast.notice(),
				forecast.warnings() == null ? List.of() : forecast.warnings());
		return new SlotQuote(station.getId(), station.getCode(), slotStart.atZone(zone).toOffsetDateTime(),
				slotStart.plusSeconds(3600).atZone(zone).toOffsetDateTime(), bookingProperties.currency(), price, info);
	}

}
