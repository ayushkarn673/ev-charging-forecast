package com.evcharge.backend.booking;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneId;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

import com.evcharge.backend.pricing.CongestionLevel;

/** Request and response bodies of the booking API. */
public final class BookingDtos {

	private BookingDtos() {
	}

	/**
	 * @param startTime ISO-8601 with offset, on a whole hour of the station's time zone; the booking
	 * covers one hour
	 * @param quotedFinalPrice optional price the customer was shown; if given and the server-side
	 * price differs, the booking is refused (409) instead of charging a different amount
	 */
	public record CreateBookingRequest(
			@NotNull @Positive Long stationId,
			@NotBlank @Size(max = 100) String customerName,
			@NotNull OffsetDateTime startTime,
			@DecimalMin("0.00") BigDecimal quotedFinalPrice) {
	}

	public record BookingResponse(Long id, Long stationId, String stationCode, String stationName,
			String customerName, OffsetDateTime startTime, OffsetDateTime endTime, BookingStatus status,
			BigDecimal basePrice, BigDecimal priceMultiplier, BigDecimal finalPrice, String currency,
			BigDecimal predictedUtilization, CongestionLevel congestionLevel, String forecastMode,
			Instant forecastReferenceTime, String modelId, Instant createdAt) {

		static BookingResponse of(Booking b) {
			ZoneId zone = b.getStation().getZoneId();
			return new BookingResponse(b.getId(), b.getStation().getId(), b.getStation().getCode(),
					b.getStation().getName(), b.getCustomerName(), b.getStartTime().atZone(zone).toOffsetDateTime(),
					b.getEndTime().atZone(zone).toOffsetDateTime(), b.getStatus(), b.getBasePrice(),
					b.getPriceMultiplier(), b.getFinalPrice(), b.getCurrency(), b.getPredictedUtilization(),
					b.getCongestionLevel(), b.getForecastMode(), b.getForecastReferenceTime(), b.getModelId(),
					b.getCreatedAt());
		}

	}

}
