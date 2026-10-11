# India EV LSTM — synthetic-demand experiment

> **Synthetic data.** Every hourly value used here (occupancy, demand, energy) was **simulated** by
> the dataset's own generator script. The results show how well an LSTM learns that generator's
> patterns. They are **not** evidence of real-world Indian EV charging forecast accuracy and must
> not be reported as such.

This folder holds the India model and everything used to build it. It does not change the Caltech model
(`models/`), the ACN-Data dataset (`dataset/`), the backup (`ml-model-backup/`) or `ml-service/`.
The Streamlit app shows these predictions on its Model insights page (see "Use in the app"). Booking
availability and prices still use the Caltech LSTM through the backend.

## Source and provenance

| | |
|---|---|
| Archive | `datasets.zip` (received via WhatsApp), folder `india_ev_4cities/` |
| Built by | `build_real_dataset.py` in the archive (read as text, never run) |
| **Real** | Station names, operators, locations and source URLs (OpenStreetMap + web listings); 601 of 991 charger counts; 131 of 991 tariffs |
| **Imputed** | 390 charger counts (222 drawn at random, 168 capped at 8); 860 tariffs (operator/city medians) |
| **Simulated** | All hourly data: Poisson demand around hand-set daily curves × weekend, festival, weather and growth multipliers; random charger faults; rule-based price |
| Coverage | 991 stations, 4 cities, 2025-10-01 00:00 → 2026-03-29 23:00 (4,320 hours, no gaps) |

The archive's `.joblib` models and Python environment were not loaded or run. The archive's
`models/metrics.csv` comes from a gradient-boosting model in that project, not from this LSTM.

Source file hashes are in `data/source_manifest.json`.

## Target: city-level hourly utilization

Single stations are too coarse to forecast (25% have one charger, so utilization is only 0 or 1).
Stations are therefore summed per city, which is comparable to the production model's one 54-space site.

```
installed_chargers(city) = Σ total_chargers of the city's stations   (fixed: Bengaluru 378,
                                                                       Delhi NCR 512, Mumbai 237, Pune 1,937)
utilization(city, hour)  = Σ chargers_occupied / installed_chargers
```

Capacity is **installed and fixed**, as in production. Simulated charger faults lower the number
of *working* chargers but not the denominator, so the dataset's own `utilisation` column (which
divides by working chargers) is not used. Timestamps are naive and treated as India Standard Time.

## Features (24 hours × 11, same shape as production)

| Production | This experiment |
|---|---|
| `utilization`, `utilization_lag_168`, `utilization_roll_mean_24` | same, from city utilization |
| `arrivals` | `demand_per_charger` = Σ `demand_vehicles` / installed chargers |
| `energy_kwh_completed` | `energy_per_charger` = Σ `energy_kwh` / installed chargers |
| `hour_sin/cos`, `dow_sin/cos`, `is_weekend` | same |
| `is_holiday` | generator festival windows (Sundays are already covered by `is_weekend`) |

Demand and energy are per charger so a single scaler works for cities of very different size.

## Method

- **Split:** chronological 70/15/15 on the shared hourly timeline, snapped to midnight, identical for
  all cities. Windows never cross a split boundary. Every validation and test target comes after every training target.
- **Scaling:** MinMax scalers fitted on valid training rows only (all four cities pooled), then
  applied unchanged to validation and test.
- **Model:** one pooled model for all four cities, same architecture and hyperparameters as
  production: LSTM(64, return_sequences) → Dropout(0.2) → LSTM(32) → Dropout(0.2) → Dense(16, relu) → Dense(1);
  Adam 1e-3, MSE, batch 256, ≤ 300 epochs, early stopping on validation loss (patience 10, best weights restored), seed 42,
  deterministic ops, no shuffling. Training windows are ordered by target time with cities interleaved.
- **Baselines** (same test targets): previous hour, and same hour last week.
- **Metrics:** MAE, RMSE (percentage points of utilization), WAPE, bias. A day-block bootstrap
  (2,000 resamples) gives a 95% interval for the MAE difference between the LSTM and each baseline.

## Run

From the repo root, using the existing ml-service interpreter (nothing is installed or synced):

```powershell
ml-service\.venv\Scripts\python.exe -I -B experiments\india_ev_lstm\prepare.py --source <folder>\india_ev_4cities
ml-service\.venv\Scripts\python.exe -I -B experiments\india_ev_lstm\train_eval.py
```

`train_eval.py` refuses to start if less than 1.5 GB of RAM is free. Stop FastAPI and Spring Boot first.

## Files

| Path | Contents |
|---|---|
| `prepare.py` | station-hourly → city-hourly aggregation and integrity checks |
| `train_eval.py` | features, splits, scalers, training, evaluation |
| `data/city_hourly.csv`, `data/source_manifest.json` | aggregated data (17,280 city-hours) and provenance |
| `model/india_synthetic_lstm.keras` | best-validation-loss model |
| `model/feature_scaler.pkl`, `model/target_scaler.pkl`, `model/metadata.json` | scalers and model metadata |
| `results/metrics.csv` | validation and test metrics, overall and per city, LSTM and baselines |
| `results/test_predictions.csv` | every test-hour prediction |
| `results/training_history.csv`, `results/training_summary.json`, `results/train_log.txt` | training record |
| `replay_predict.py`, `results/replay_predictions.csv`, `results/replay_manifest.json` | historical-replay predictions used by the app, with hashes and checks |

## Results (synthetic data — see warning at top)

Run on 2026-10-12, CPU, 8 GB laptop: Python 3.12.7, TensorFlow 2.20.0. Training took **188.6 s**:
42 epochs, stopped early, **best epoch 32** (validation MSE 0.00196 in scaled units). The model has 32,417 parameters.

| Split | Period (rows, IST) | Windows (4 cities) |
|---|---|---:|
| train | 2025-10-01 → 2026-02-03 | 11,328 |
| val | 2026-02-04 → 2026-03-02 | 2,496 |
| test | 2026-03-03 → 2026-03-29 (first target 2026-03-04 00:00, after a 24 h input window) | 2,496 |

The `split_periods_local_target_hours` key in the JSON files gives these row periods.

**Held-out test, all four cities** (pp = percentage points of utilization):

| Model | MAE (pp) | RMSE (pp) | WAPE | Bias (pp) |
|---|---:|---:|---:|---:|
| **LSTM** | **1.80** | **2.34** | **6.7%** | −0.33 |
| Previous hour | 3.51 | 4.55 | 13.2% | 0.00 |
| Same hour last week | 2.66 | 3.49 | 10.0% | 0.01 |

**By city (test MAE / RMSE, pp):**

| City | LSTM | Previous hour | Same hour last week |
|---|---|---|---|
| Bengaluru | **1.92** / **2.41** | 3.71 / 4.78 | 2.86 / 3.59 |
| Delhi NCR | **2.07** / **2.62** | 3.88 / 4.98 | 2.85 / 3.60 |
| Mumbai | **2.18** / **2.75** | 3.64 / 4.64 | 3.17 / 4.12 |
| Pune | **1.04** / **1.32** | 2.83 / 3.69 | 1.76 / 2.44 |

The LSTM's MAE is lower than both baselines in every city, on validation and on test. Day-block bootstrap
of the test MAE difference (LSTM − baseline, 26 days, 2,000 resamples):
previous hour −1.71 pp [95%: −1.78, −1.65], same hour last week −0.86 pp [−1.14, −0.61].

**How to read this:**
- **Why last week beats previous hour here.** Same hour last week beating previous hour is the opposite of the Caltech result. It follows from how the data was generated: a fixed daily curve repeats every week, plus independent random noise each hour.
- **What the LSTM learns.** It learns that repeating curve, and its remaining error is largely the generator's Poisson noise.
- **Why Pune scores best.** Pune has the most chargers (1,937), so its relative noise is smallest. Mumbai has the fewest (237) and the largest error.
- **The numbers can't be compared to the Caltech model.** The data, sites and demand process are all different.

Full tables: `results/metrics.csv`. Bootstrap figures: `results/training_summary.json`.

## Use in the app

The Streamlit app's **Model insights** page opens on this model (`streamlit-app/evcharge/india.py`).
It is not connected to bookings, pricing or the FastAPI service.

**Why two steps.** No existing environment has both TensorFlow (in `ml-service`) and Streamlit
(in `streamlit-app`), and nothing new is installed.
1. **Generate predictions.** `replay_predict.py` loads the trained model and scalers and builds features with the
   same code as training (imported from `train_eval.py`). It writes next-hour predictions for every hour that has a
   complete 24-hour window to `results/replay_predictions.csv`. It refuses to run with less than 1.5 GB free RAM,
   fails on non-finite output, and never clips. It also checks that it reproduces `results/test_predictions.csv`
   (maximum difference 5×10⁻⁷).
2. **Show them.** The app reads those predictions plus `data/city_hourly.csv`. Before showing anything, it checks
   the model, scalers and data against the hashes in `results/replay_manifest.json`, and the model metadata against
   the expected inputs. The Streamlit process never loads TensorFlow.

```powershell
ml-service\.venv\Scripts\python.exe -I -B experiments\india_ev_lstm\replay_predict.py
```

The first 8 days of each city cannot be predicted, because the features need one week of history plus a
24-hour window. The app says so instead of inventing values. Tests: `streamlit-app/tests/test_india.py`.

## Limitations

- **Synthetic demand.** The model learns a known formula plus Poisson noise, so its error is mostly that noise. It says nothing about how real drivers behave.
- **Weather is simulated** and is not a model input.
- **Short history.** 180 days in total, so the test period is 27 days in March 2026.
- **Seasonal effects are untested.** Festivals in the test period are limited to Holi.
- **Pooled cities.** The model has no input that identifies the city, and each city's capacity is held fixed for the whole period.
- **Display only.** The app shows this model's replay predictions, but it is not connected to the FastAPI service
  or the backend, so it does not affect slot availability or prices.
