package com.evcharge.backend.booking;

import java.math.BigDecimal;
import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;

import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import com.evcharge.backend.pricing.CongestionLevel;
import com.evcharge.backend.station.Station;

/**
 * One charger reserved at a station for [startTime, endTime). Times are UTC instants. The price and
 * the forecast it was derived from are stored as a snapshot.
 */
@Entity
@Table(name = "bookings")
public class Booking {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "station_id", nullable = false)
	private Station station;

	@Column(name = "customer_name", nullable = false, length = 100)
	private String customerName;

	@Column(name = "start_time", nullable = false)
	private Instant startTime;

	@Column(name = "end_time", nullable = false)
	private Instant endTime;

	@Enumerated(EnumType.STRING)
	@JdbcTypeCode(SqlTypes.VARCHAR)
	@Column(nullable = false, length = 16)
	private BookingStatus status;

	@Column(name = "base_price", nullable = false, precision = 10, scale = 2)
	private BigDecimal basePrice;

	@Column(name = "price_multiplier", nullable = false, precision = 5, scale = 3)
	private BigDecimal priceMultiplier;

	@Column(name = "final_price", nullable = false, precision = 10, scale = 2)
	private BigDecimal finalPrice;

	@Column(nullable = false, length = 3)
	private String currency;

	@Column(name = "predicted_utilization", nullable = false, precision = 7, scale = 6)
	private BigDecimal predictedUtilization;

	@Enumerated(EnumType.STRING)
	@JdbcTypeCode(SqlTypes.VARCHAR)
	@Column(name = "congestion_level", nullable = false, length = 16)
	private CongestionLevel congestionLevel;

	@Column(name = "forecast_mode", nullable = false, length = 32)
	private String forecastMode;

	@Column(name = "forecast_reference_time", nullable = false)
	private Instant forecastReferenceTime;

	@Column(name = "model_id", nullable = false, length = 64)
	private String modelId;

	@Column(name = "created_at", nullable = false)
	private Instant createdAt;

	protected Booking() {
	}

	Booking(Station station, String customerName, Instant startTime, Instant endTime, BigDecimal basePrice,
			BigDecimal priceMultiplier, BigDecimal finalPrice, String currency, BigDecimal predictedUtilization,
			CongestionLevel congestionLevel, String forecastMode, Instant forecastReferenceTime, String modelId,
			Instant createdAt) {
		this.station = station;
		this.customerName = customerName;
		this.startTime = startTime;
		this.endTime = endTime;
		this.status = BookingStatus.CONFIRMED;
		this.basePrice = basePrice;
		this.priceMultiplier = priceMultiplier;
		this.finalPrice = finalPrice;
		this.currency = currency;
		this.predictedUtilization = predictedUtilization;
		this.congestionLevel = congestionLevel;
		this.forecastMode = forecastMode;
		this.forecastReferenceTime = forecastReferenceTime;
		this.modelId = modelId;
		this.createdAt = createdAt;
	}

	public Long getId() {
		return id;
	}

	public Station getStation() {
		return station;
	}

	/** Marks the booking cancelled; the row is kept so history and the price snapshot remain. */
	void cancel() {
		this.status = BookingStatus.CANCELLED;
	}

	public String getCustomerName() {
		return customerName;
	}

	public Instant getStartTime() {
		return startTime;
	}

	public Instant getEndTime() {
		return endTime;
	}

	public BookingStatus getStatus() {
		return status;
	}

	public BigDecimal getBasePrice() {
		return basePrice;
	}

	public BigDecimal getPriceMultiplier() {
		return priceMultiplier;
	}

	public BigDecimal getFinalPrice() {
		return finalPrice;
	}

	public String getCurrency() {
		return currency;
	}

	public BigDecimal getPredictedUtilization() {
		return predictedUtilization;
	}

	public CongestionLevel getCongestionLevel() {
		return congestionLevel;
	}

	public String getForecastMode() {
		return forecastMode;
	}

	public Instant getForecastReferenceTime() {
		return forecastReferenceTime;
	}

	public String getModelId() {
		return modelId;
	}

	public Instant getCreatedAt() {
		return createdAt;
	}

}
