# EV Charging Demand Forecasting with Dynamic Slot Booking and Demand-Based Pricing

A final-year project: an **LSTM** forecasts next-hour charger utilization from real EV charging
sessions; a **demand-based pricing policy** turns that forecast into slot prices; a **Spring Boot**
backend handles safe, concurrent slot booking in **MySQL**; a **Streamlit** web app shows forecasts,
model accuracy, availability, pricing and bookings.

```
Streamlit (:8501) ──HTTP──▶ Spring Boot (:8080) ──JDBC──▶ MySQL 8.4 in Docker (:3307)
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
- **Stations and bookings are demonstration data** (`DEMO-` codes, plus one sample station per India-model city
  with `IN-` codes: Pune, Mumbai, Delhi NCR, Bengaluru), not real sites. All slot prices use the Caltech-trained forecast.

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

Windows with Docker Desktop (WSL 2), Java 21, Maven 3.9, Python 3.12 via `uv`.
Create `mysql.env` from `mysql.env.example` (git-ignored; never commit it).

One-time setup:

```powershell
cd ml-service;    uv sync
cd streamlit-app; uv sync
```

## Start the demo (four terminals, in this order)

```powershell
# 1. Database (MySQL 8.4 in Docker on 127.0.0.1:3307). Wait until Docker Desktop is running.
docker compose up -d

# 2. ML service (loads the trained LSTM; first start can take 1-3 minutes on an 8 GB laptop)
cd ml-service; uv run uvicorn api:app --host 127.0.0.1 --port 8000

# 3. Backend (reads DB credentials from ../mysql.env without printing them; start after the database)
cd backend; .\scripts\with-db-env.ps1 mvn spring-boot:run

# 4. Frontend (Streamlit)
cd streamlit-app; uv run streamlit run app.py        # open http://127.0.0.1:8501
```

The Streamlit app talks only to the backend (default `http://127.0.0.1:8080`). Set
`EVCHARGE_API_URL` to point it elsewhere and `EVCHARGE_API_TIMEOUT` (seconds, default 20) to change
the request timeout. Forecasts and model evaluation reach the ML service through the backend.

If the first price request after startup reports "Pricing is temporarily unavailable", the model's
first prediction exceeded the backend's 5-second limit (usually low free memory); try again.

## Demo walkthrough

1. **Home:** how booking works, the demand levels, and the stations.
2. **Stations:** capacity, base price and hour-by-hour availability (Available, Full, Started, Not open yet).
3. **Book:** choose station, day and an available hour → price breakdown (base price × demand
   adjustment from the forecast) → confirm. The backend re-validates, re-prices and refuses if the
   slot filled up (409), the price changed (409) or the customer already holds that slot (409).
4. **My bookings:** saved bookings with status and price; confirmed future bookings can be cancelled.
5. **Model insights:** the LSTM forecast for any test-period hour (historical replay), the pricing
   policy, accuracy against the baselines and the actual-vs-predicted chart.

## Tests

Run one suite at a time, with the demo services stopped (8 GB RAM).

```powershell
cd ml-service;    uv run pytest                           # 126 tests (pipeline, model, API)
cd backend;       .\scripts\with-db-env.ps1 mvn test      # 78 tests (pricing, booking lifecycle, concurrency, client)
cd streamlit-app; uv run pytest                           # 48 tests (API client, formatting, all screens via AppTest)
```

## Repository layout

| Path | Contents |
|---|---|
| `ml-service/` | preprocessing, training, evaluation, FastAPI inference service (see its README) |
| `models/`, `ml-model-backup/` | trained model, scalers, metadata, saved evaluation; verified backup |
| `backend/` | Spring Boot API, Flyway migrations (see `backend/README.md`) |
| `streamlit-app/` | Streamlit frontend: `app.py`, `views/`, `evcharge/` client, `tests/` |
| `docs/` | preprocessing and evaluation reports, figures |
| `docker-compose.yml` | MySQL 8.4 container (`evcharge-mysql`, volume `evcharge-mysql-data`) |
