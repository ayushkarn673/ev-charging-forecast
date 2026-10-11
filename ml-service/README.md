# ML Service — EV Charging Demand Forecasting

LSTM forecasting of next-hour charger **utilization** for the Caltech ACN site, plus a FastAPI
service that serves those forecasts in **historical replay** mode.

> **Not live data.** All forecasts are reconstructions on historical ACN-Data
> (Caltech, Nov 2018 – Feb 2020). The model is validated for **one hour ahead only**.

## 1. Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12 (TensorFlow does not support 3.14).

```bash
cd ml-service
uv sync                      # creates .venv from pyproject.toml + uv.lock
```

`pyproject.toml` is the source of truth; `requirements.txt` is generated with
`uv export --no-hashes --no-dev --format requirements-txt -o requirements.txt` — do not edit it by hand.

## 2. Pipeline

| Step | Command | Output |
|---|---|---|
| Download data (needs `ACN_API_TOKEN` in `ml-service/.env`, see `.env.example`) | `uv run fetch_acn_data.py --sites caltech` | `dataset/raw/` |
| Preprocess | `uv run preprocess.py` | `dataset/processed/`, scalers + `features.json` in `models/`, `docs/preprocessing_report.md` |
| Train | `uv run train.py --epochs 300` | `models/ev_demand_lstm.keras`, history, `docs/figures/training_loss_curves.png` |
| Evaluate on the test split | `uv run evaluate.py` | `models/evaluation/`, `docs/evaluation_report.md` |
| Tests | `uv run pytest` | 126 tests |

## 3. Run the API

```bash
cd ml-service
uv run uvicorn api:app --host 127.0.0.1 --port 8000
```

Interactive docs: <http://127.0.0.1:8000/docs>. The model, scalers, feature metadata and
observation store are loaded once at startup.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Service status, model id, number of observation hours loaded |
| GET | `/model-info` | Architecture, features, horizon, training summary, test-set metrics, limitations |
| GET | `/available-dates` | Supported forecast-time range, per-split periods, list of local dates |
| POST | `/predict/next-hour` | One-hour-ahead utilization forecast for a historical forecast time |
| GET | `/evaluation` | Saved Phase 3 test-set metrics (MAE, RMSE, WAPE, baselines); read-only, no inference |
| GET | `/evaluation/series?start=2020-01-06&end=2020-01-12` | Saved actual vs predicted test-set values (≤ 31 days); read-only |

### Example

```bash
curl -X POST http://127.0.0.1:8000/predict/next-hour \
     -H "Content-Type: application/json" \
     -d '{"forecastTime": "2020-01-15T09:00:00-08:00"}'
```

Response (abridged, actual output):

```json
{
  "mode": "historical_replay",
  "isSimulation": true,
  "siteId": "caltech",
  "forecastTime": "2020-01-15T09:00:00-08:00",
  "targetStart": "2020-01-15T09:00:00-08:00",
  "targetEnd": "2020-01-15T10:00:00-08:00",
  "horizonHours": 1,
  "inputs": {"earliestObservationUsed": "2020-01-07T09:00:00-08:00",
             "latestObservationUsed": "2020-01-15T08:00:00-08:00", "sequenceLength": 24},
  "prediction": {
    "utilization": 0.2336, "utilizationPercent": 23.4,
    "estimatedOccupiedSpaces": 12.62,
    "estimatedOccupiedSpacesRounded": 13, "estimatedAvailableSpacesRounded": 41,
    "rawUtilization": 0.2336
  },
  "observedOutcome": {"utilizationPercent": 26.0, "note": "... never used as model input."},
  "modelId": "ev_demand_lstm@sha256:14c51f034f14",
  "warnings": []
}
```

### Request rules and errors

| Case | Status | `code` |
|---|---|---|
| `forecastTime` without timezone offset, not on the hour, malformed, or extra fields | 422 | FastAPI validation error |
| Less than 192 hours of valid history before `forecastTime` | 422 | `INSUFFICIENT_HISTORY` |
| After the end of the dataset | 422 | `OUT_OF_RANGE` |
| `siteId` other than `caltech` | 404 | `UNKNOWN_SITE` |
| Service not loaded | 503 | `MODEL_NOT_LOADED` |

## 4. How historical replay works

`forecastTime` F is the simulated "now". The forecast is for the hour **[F, F+1 h)**.

1. Only observations for hours that had **ended by F** are used: F−192 h … F−1 h
   (24 input hours, each needing the value 168 hours earlier for the lag feature).
2. The observation store contains only per-hour measurements (utilization, arrivals,
   completed energy). Lag and rolling features are **recomputed for every request** from that cut
   history with the same functions as training, then scaled with the saved feature scaler in the
   `features.json` order.
3. Tests verify that (a) tampering with every observation at or after F does not change the input
   or prediction, and (b) replay inputs are byte-identical to the preprocessed test sequences and
   replay predictions reproduce the Phase 3 saved predictions.

`observedOutcome` is the recorded utilization of the target hour, returned **for comparison only**.

### Output policy

- `rawUtilization`: model output inverse-transformed with the **target** scaler (kept for diagnostics).
- `utilization`: raw value clipped to [0, 1]; warning `PREDICTION_CLIPPED` if clipping changed it.
- `estimatedOccupiedSpaces`: utilization × 54 — a **time-weighted average** over the hour, not a
  physical count.
- `estimatedOccupiedSpacesRounded` = ceil(estimate); `estimatedAvailableSpacesRounded` = 54 − that.
  Rounding up occupancy means availability is never overstated.

### Warnings

| Code | When |
|---|---|
| `IN_SAMPLE_TRAINING_PERIOD` | Target hour is in the training period (not an out-of-sample forecast) |
| `MODEL_SELECTION_PERIOD` | Target hour is in the validation period (used to pick the best epoch) |
| `OUTCOME_NOT_IN_DATASET` | Target hour is after the last observation |
| `HOLIDAY_TARGET` / `WEEKEND_TARGET` | Periods where the test-set previous-hour baseline beat the LSTM |
| `BASELINE_BETTER_AT_THIS_HOUR` | Target hour of day where the test-set previous-hour baseline had lower MAE |
| `PREDICTION_CLIPPED` | Raw output outside [0, 1] |

For honest out-of-sample demos use forecast times in the **test** period
(2019-12-19 → 2020-02-29). Note: replay supports 1,752 test-period forecast hours; the Phase 3
evaluation scored 1,728 of them, because evaluation sequences could not start before the test
split, while replay may use the last validation hours as (past) input.

## 5. Model and results

LSTM(64, return_sequences) → Dropout(0.2) → LSTM(32) → Dropout(0.2) → Dense(16, relu) → Dense(1);
input 24 hours × 11 features; target = next-hour time-weighted utilization of 54 installed spaces.
Best epoch 111 of 121 (early stopping on validation loss).

Test set (`models/evaluation/test_metrics.json`, n = 1,728 hours, 2019-12-20 → 2020-02-29):

| Approach | MAE (pp) | RMSE (pp) | MAE (spaces) |
|---|---:|---:|---:|
| Previous hour | 2.533 | 5.004 | 1.37 |
| Same hour last week | 5.023 | 9.611 | 2.71 |
| **LSTM** | **1.599** | **2.384** | **0.86** |

pp = percentage points of utilization. Full analysis: `docs/evaluation_report.md`.

## 6. Limitations

- **One hour ahead only.** No multi-hour forecasts are served; longer horizons are not evaluated.
- **Historical replay only** of ACN-Data; not connected to live chargers.
- **Single site** (Caltech garage); results may not generalise.
- **Installed capacity** (54 spaces) is the denominator, not operational capacity.
- **Weaker in quiet periods:** on test-set weekends (0.88 vs 0.69 pp) and holidays (1.28 vs 0.57 pp),
  and at several night/midday hours, the previous-hour baseline had lower MAE than the LSTM.
- Under-predicts the highest peaks; slight over-prediction during the winter closure.
- The holiday calendar (`config.py`) covers 2018–2020; new closure dates must be added for other years.
