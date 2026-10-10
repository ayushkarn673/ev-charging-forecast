# ML Model Backup — EV Charging Demand LSTM

Independent copy of the trained forecasting model and everything needed to run inference,
made before starting the Spring Boot backend. Files are byte-identical copies of the originals
(see `SHA256SUMS.txt` and `MANIFEST.json`).

- Source commit: `fee183a` ("Add ML pipeline and FastAPI forecast service (phases 1-4)")
- Model id used by the API: `ev_demand_lstm@sha256:14c51f034f14`
- Model: LSTM(64) → Dropout(0.2) → LSTM(32) → Dropout(0.2) → Dense(16, relu) → Dense(1);
  input (None, 24, 11); best epoch 111 of 121
- Target: next-hour time-weighted utilization of 54 installed spaces (Caltech ACN site)
- Test set (n = 1,728 h, 2019-12-20 → 2020-02-29): LSTM MAE 1.599 pp, RMSE 2.384 pp

## Contents

| Folder | Files | Copied from | Needed for inference? |
|---|---|---|---|
| `model/` | `ev_demand_lstm.keras` | `models/` | **Yes** |
| `preprocessing/` | `feature_scaler.pkl`, `target_scaler.pkl`, `features.json` | `models/` | **Yes** (feature order, scaling, inverse scaling) |
| `training/` | `model_config.json`, `training_summary.json`, `training_history.csv` | `models/` | Yes — `model_config.json` and `training_summary.json` are read by the API at startup |
| `evaluation/` | `test_metrics.json`, `test_metrics_table.csv`, `test_predictions.csv`, `evaluation_report.md`, `figures/` | `models/evaluation/`, `docs/` | `test_metrics.json` is read by the API (warnings, `/model-info`); the rest is documentation |
| `inference-data/` | `hourly_utilization.csv` | `dataset/processed/` | **Yes for historical replay** — the observation history the API reads (processed data, not raw) |
| `environment/` | `pyproject.toml`, `uv.lock`, `.python-version` | `ml-service/` | To recreate the exact Python 3.12 / TensorFlow 2.20 environment with `uv sync` |
| `docs/` | `preprocessing_report.md` | `docs/` | Documentation |

Not included on purpose: raw ACN-Data (`dataset/raw/`), `ml-service/.env` (API token),
`.venv/`, training logs and the archived training runs (`models/runs/`).

## Restore

Copy each file back to its original path (listed in `MANIFEST.json`), then verify:

```bash
cd ml-model-backup
sha256sum -c SHA256SUMS.txt
```

The inference code (`prediction_service.py`, `preprocess.py`, `config.py`, `api.py`,
`schemas.py`) is not duplicated here; it is in `ml-service/` at commit `fee183a`.
