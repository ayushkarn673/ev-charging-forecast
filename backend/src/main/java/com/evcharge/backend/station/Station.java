package com.evcharge.backend.station;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.ZoneId;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** A charging location. Schema owned by Flyway (V1); rows are read-only for the API. */
@Entity
@Table(name = "stations")
public class Station {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(nullable = false, unique = true, length = 32)
	private String code;

	@Column(nullable = false, length = 100)
	private String name;

	@Column(nullable = false)
	private String address;

	@Column(nullable = false)
	private int capacity;

	@Column(name = "time_zone", nullable = false, length = 64)
	private String timeZone;

	@Column(name = "base_price_per_hour", nullable = false, precision = 10, scale = 2)
	private BigDecimal basePricePerHour;

	@Column(name = "created_at", nullable = false)
	private Instant createdAt;

	protected Station() {
	}

	public Long getId() {
		return id;
	}

	public String getCode() {
		return code;
	}

	public String getName() {
		return name;
	}

	public String getAddress() {
		return address;
	}

	public int getCapacity() {
		return capacity;
	}

	public ZoneId getZoneId() {
		return ZoneId.of(timeZone);
	}

	public BigDecimal getBasePricePerHour() {
		return basePricePerHour;
	}

	public Instant getCreatedAt() {
		return createdAt;
	}

}
