-- V1: minimum schema for one-hour slot booking with demand-based pricing.
-- All DATETIME values are UTC (connectionTimeZone=UTC, hibernate.jdbc.time_zone=UTC).

CREATE TABLE stations (
    id                  BIGINT        NOT NULL AUTO_INCREMENT,
    code                VARCHAR(32)   NOT NULL,         -- stable public identifier, e.g. DEMO-01
    name                VARCHAR(100)  NOT NULL,
    address             VARCHAR(255)  NOT NULL,
    capacity            INT           NOT NULL,         -- chargers that can be booked in the same hour
    time_zone           VARCHAR(64)   NOT NULL,         -- IANA zone; slots are whole hours in this zone
    base_price_per_hour DECIMAL(10,2) NOT NULL,         -- price before the demand multiplier
    created_at          DATETIME(6)   NOT NULL,
    CONSTRAINT pk_stations PRIMARY KEY (id),
    CONSTRAINT uk_stations_code UNIQUE (code),
    CONSTRAINT ck_stations_capacity CHECK (capacity BETWEEN 1 AND 500),
    CONSTRAINT ck_stations_price CHECK (base_price_per_hour >= 0)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- One row = one charger reserved for one one-hour slot. The price and the forecast it was based on
-- are stored as a snapshot so booking history shows exactly what the customer was charged and why.
CREATE TABLE bookings (
    id                      BIGINT        NOT NULL AUTO_INCREMENT,
    station_id              BIGINT        NOT NULL,
    customer_name           VARCHAR(100)  NOT NULL,     -- no accounts yet
    start_time              DATETIME      NOT NULL,     -- UTC, on a whole hour of the station's zone
    end_time                DATETIME      NOT NULL,     -- UTC, exclusive (start + 1 hour)
    status                  VARCHAR(16)   NOT NULL,
    base_price              DECIMAL(10,2) NOT NULL,
    price_multiplier        DECIMAL(5,3)  NOT NULL,
    final_price             DECIMAL(10,2) NOT NULL,
    currency                CHAR(3)       NOT NULL,
    predicted_utilization   DECIMAL(7,6)  NOT NULL,     -- LSTM output (0..1) the price was based on
    congestion_level        VARCHAR(16)   NOT NULL,
    forecast_mode           VARCHAR(32)   NOT NULL,     -- e.g. historical_replay (never "live" for ACN data)
    forecast_reference_time DATETIME      NOT NULL,     -- UTC hour whose forecast was used
    model_id                VARCHAR(64)   NOT NULL,
    created_at              DATETIME(6)   NOT NULL,
    CONSTRAINT pk_bookings PRIMARY KEY (id),
    CONSTRAINT fk_bookings_station FOREIGN KEY (station_id) REFERENCES stations (id) ON DELETE RESTRICT,
    CONSTRAINT ck_bookings_time CHECK (end_time > start_time),
    CONSTRAINT ck_bookings_status CHECK (status IN ('CONFIRMED', 'CANCELLED')),
    CONSTRAINT ck_bookings_price CHECK (base_price >= 0 AND final_price >= 0 AND price_multiplier > 0),
    CONSTRAINT ck_bookings_utilization CHECK (predicted_utilization BETWEEN 0 AND 1),
    CONSTRAINT ck_bookings_congestion CHECK (congestion_level IN ('LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH'))
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- Capacity checks: WHERE station_id = ? AND status = 'CONFIRMED' AND start_time < ? AND end_time > ?
CREATE INDEX ix_bookings_station_status_start ON bookings (station_id, status, start_time);
-- Booking history ordered by time
CREATE INDEX ix_bookings_start ON bookings (start_time);
