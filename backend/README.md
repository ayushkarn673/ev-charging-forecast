# Backend — Spring Boot 4.1.1 (Java 21)

REST API for stations, slot availability, demand-based pricing and bookings. It stores data in
MySQL 8.4 (Docker, `127.0.0.1:3307`) and gets every forecast from the Python FastAPI service
(`ml-service`, `127.0.0.1:8000`) over HTTP — the LSTM is never loaded in Java.

## Run

```powershell
# from the project root: database first
docker compose up -d
# then, from backend/ (loads DB_USERNAME / DB_PASSWORD from ../mysql.env without printing them)
.\scripts\with-db-env.ps1 mvn spring-boot:run
```

The app listens on `http://127.0.0.1:8080` (localhost only; set `SERVER_ADDRESS` to change).

## Tests

```powershell
.\scripts\with-db-env.ps1 mvn test     # 61 tests, incl. integration tests against Docker MySQL
mvn test                                # without credentials: DB integration tests are skipped
```

Integration tests create their own `IT-` stations and delete them afterwards; demo data is never
touched. The FastAPI client is mocked there; it is tested separately against a local stub server.

## Configuration (`src/main/resources/application.yml`)

| Setting | Default | Meaning |
|---|---|---|
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USERNAME` | `127.0.0.1` / `3307` / `ev_charging_db` / `evcharge_app` | Docker MySQL |
| `DB_PASSWORD` | *(none — required)* | supplied by `scripts/with-db-env.ps1` |
| `ML_SERVICE_URL` | `http://127.0.0.1:8000` | FastAPI base URL (timeouts 2 s connect / 5 s read) |
| `evcharge.booking.max-days-ahead` | `14` | booking window |
| `evcharge.pricing.thresholds.*` | `0.40 / 0.70 / 0.90` | utilization where MEDIUM / HIGH / VERY_HIGH start (inclusive) |
| `evcharge.pricing.multipliers.*` | `0.90 / 1.15 / 1.35 / 1.60` | LOW / MEDIUM / HIGH / VERY_HIGH |
| `evcharge.forecast.replay-week-start` | `2020-02-03` | Monday of the test-period week used for replay pricing |

Invalid pricing configuration (thresholds not increasing, multipliers decreasing, out of range)
stops the application at startup.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/health`, `/api/health/db` | backend / database status |
| GET | `/api/forecast/status` | FastAPI health (model loaded, model id) |
| GET | `/api/forecast/next-hour?forecastTime=2020-02-05T10:00:00-08:00` | LSTM forecast (historical replay) + congestion band |
| GET | `/api/forecast/model-info`, `/api/forecast/evaluation` | model metadata, saved test-set metrics |
| GET | `/api/forecast/evaluation/series?from=2020-02-03&to=2020-02-09` | saved actual vs predicted (≤ 31 days) |
| GET | `/api/stations` | stations with capacity and base price |
| GET | `/api/slots/availability?stationId=1&date=2026-10-12` | 24 one-hour slots: booked / available / bookable |
| GET | `/api/pricing/quote?stationId=1&startTime=2026-10-12T13:00:00%2B05:30` | price breakdown for one slot |
| POST | `/api/bookings` | `{stationId, customerName, startTime, quotedFinalPrice?}` → 201 |
| GET | `/api/bookings[?stationId=]`, `/api/bookings/{id}` | booking history |

Errors are RFC 9457 problem responses: 400 validation, 404 unknown station/booking,
409 slot full or price changed, 422 forecast request rejected by FastAPI, 503 FastAPI unavailable.

## How pricing works

1. The slot is validated (whole hour in the station's time zone, in the future, ≤ 14 days ahead).
2. **Replay mapping:** the LSTM only has ACN-Data history (Caltech, Nov 2018 – Feb 2020), so the
   slot is mapped to the same weekday and hour of the test-period week starting 2020-02-03 and
   FastAPI returns the LSTM's one-hour-ahead forecast for that hour. This is a documented proxy,
   labelled `historical_replay` everywhere — never presented as a live forecast for the slot's date.
3. `DemandPricingPolicy` classifies the predicted utilization into LOW / MEDIUM / HIGH / VERY_HIGH
   and multiplies the station's base price. **The thresholds and multipliers are a configured
   business policy; they are not learned by the LSTM.**
4. If FastAPI is unreachable, no price is produced and booking is refused (503) — no fallback numbers.

## Booking concurrency

`BookingWriter.insert` runs in a READ_COMMITTED transaction that first locks the station row
(`SELECT … FOR UPDATE`), then counts confirmed bookings in the slot and inserts only if a charger is
free. Concurrent requests for the same station therefore run one at a time; a test fires 8
simultaneous requests at a 1-charger slot and exactly one succeeds. The FastAPI call happens
before the transaction, so the lock is never held during a network call.

## Schema (Flyway, `src/main/resources/db/migration`)

- `V1__create_stations_and_bookings.sql` — `stations`, `bookings` (with price/forecast snapshot), checks, indexes
- `V2__seed_demo_stations.sql` — three clearly marked `DEMO-` stations (not ACN-Data sites)

Hibernate runs with `ddl-auto: validate` and Flyway `clean` is disabled: the application never
creates, drops or resets tables on its own.
