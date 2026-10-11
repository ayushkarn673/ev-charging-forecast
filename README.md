# EV Charging Demand Forecasting with Dynamic Slot Booking and Demand-Based Pricing

A final-year project: an **LSTM** forecasts next-hour charger utilization from real EV charging
sessions; a **demand-based pricing policy** turns that forecast into slot prices; a **Spring Boot**
backend handles safe, concurrent slot booking in **MySQL**; a **React** dashboard shows forecasts,
model accuracy, availability, pricing and bookings.

```
React (Vite, :5173) ──/api──▶ Spring Boot (:8080) ──JDBC──▶ MySQL 8.4 in Docker (:3307)
                                      │
                                      └──HTTP──▶ FastAPI ml-service (:8000) ──▶ trained LSTM (Keras)
```

## Honest scope

- **Data:** ACN-Data, Caltech garage, 54 charging spaces, Nov 2018 – Feb 2020 (Lee, Li & Low, e-Energy 2019).
- **Forecasts are historical replay, not live.** FastAPI rebuilds each forecast using only
  observations before the requested time. Booking prices for current dates use the forecast for the
  same weekday and hour of a fixed test-period week (2020-02-03) — labelled as such in the API and UI.
- **Validated horizon: 1 hour.** Each booking is one one-hour slot priced from one forecast.
- **Pricing rules are a policy** (configured thresholds × multipliers), not learned by the model.
- **Stations and bookings are demonstration data** (`DEMO-` codes), not ACN-Data records.

## Results (untouched test set, 1,728 hours, 2019-12-20 → 2020-02-29)

| Approach | MAE (pp) | RMSE (pp) | WAPE |
|---|---:|---:|---:|
| **LSTM** | **1.599** | **2.384** | **14.7%** |
| Previous-hour baseline | 2.533 | 5.004 | 23.4% |
| Same-hour-last-week baseline | 5.023 | 9.611 | 46.3% |

pp = percentage points of utilization (1.6 pp ≈ 0.86 of 54 spaces). The LSTM's MAE is lower than both
baselines (95% bootstrap intervals exclude zero). On weekends and holidays the previous-hour baseline
was better; utilization never exceeded 70% in the test period. Details: `docs/evaluation_report.md`.

## Prerequisites

Windows with Docker Desktop (WSL 2), Java 21, Maven 3.9, Node 24, Python 3.12 via `uv`.
Create `mysql.env` from `mysql.env.example` (git-ignored; never commit it).

## Start the demo (four terminals, in this order)

```powershell
# 1. Database (MySQL 8.4 in Docker on 127.0.0.1:3307)
docker compose up -d

# 2. ML service (loads the trained LSTM; first start can take 1-3 minutes)
cd ml-service; uv run uvicorn api:app --host 127.0.0.1 --port 8000

# 3. Backend (reads DB credentials from ../mysql.env without printing them)
cd backend; .\scripts\with-db-env.ps1 mvn spring-boot:run

# 4. Frontend
cd frontend; npm install; npm run dev        # open http://127.0.0.1:5173
```

The header shows a live status dot for Backend, MySQL and the LSTM service.

## Demo walkthrough

1. **Analytics:** pick a test-period hour (or a preset) → the LSTM forecast, occupied/available
   estimates, congestion band, the recorded outcome for comparison, metrics vs baselines, and the
   actual-vs-predicted chart.
2. **Stations:** capacity, base price and hour-by-hour availability.
3. **Book a slot:** choose station, day and slot → price breakdown (base × multiplier from the forecast)
   → confirm. The backend re-validates, re-prices and refuses if the slot filled up (409) or the
   price changed (409).
4. **Booking history:** saved bookings with slot, status, the forecast and the price charged.

## Tests

```powershell
cd ml-service; uv run pytest                              # 126 tests (pipeline, model, API)
cd backend;   .\scripts\with-db-env.ps1 mvn test          # 61 tests (pricing, booking, concurrency, client)
cd frontend;  npm run build                               # production build check
```

## Repository layout

| Path | Contents |
|---|---|
| `ml-service/` | preprocessing, training, evaluation, FastAPI inference service (see its README) |
| `models/`, `ml-model-backup/` | trained model, scalers, metadata, saved evaluation; verified backup |
| `backend/` | Spring Boot API, Flyway migrations (see `backend/README.md`) |
| `frontend/` | React + Vite + Tailwind dashboard |
| `docs/` | preprocessing and evaluation reports, figures |
| `docker-compose.yml` | MySQL 8.4 container (`evcharge-mysql`, volume `evcharge-mysql-data`) |
