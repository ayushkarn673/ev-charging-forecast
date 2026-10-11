"""
SYNTHETIC-DEMAND EXPERIMENT - step 3: historical-replay predictions for the dashboard.

Loads the trained experimental model and its scalers (never retrains or overwrites them), builds
features with the SAME code used in training (imported from train_eval.py), and predicts next-hour
utilization for every city-hour that has a complete, valid 24-hour input window:

    inputs  = feature rows (t-23 .. t)  -> prediction for hour t+1
    a window is valid only if all 11 features are present in all 24 rows (the weekly lag needs
    168 hours of history, so the first 191 hours of each city have no prediction)

Predictions are NOT clipped. The script fails if any is non-finite, and it records how many fall
outside [0, 1]. It also checks that it reproduces results/test_predictions.csv, which shows the
preprocessing matches training. These are replays over simulated historical data, not live forecasts.

Outputs (results/):
    replay_predictions.csv  city, input_end, target_time, predicted_utilization, actual_utilization, period
    replay_manifest.json    hashes of the model, scalers, data and predictions + validation results

Run from the repo root with the ml-service interpreter (installs nothing):
    ml-service/.venv/Scripts/python.exe -I -B experiments/india_ev_lstm/replay_predict.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import train_eval as te  # noqa: E402  (same feature code, constants and split rule as training)

MODEL = te.MODEL_DIR / "india_synthetic_lstm.keras"
FEATURE_SCALER = te.MODEL_DIR / "feature_scaler.pkl"
TARGET_SCALER = te.MODEL_DIR / "target_scaler.pkl"
METADATA = te.MODEL_DIR / "metadata.json"
OUT_CSV = te.RESULTS_DIR / "replay_predictions.csv"
OUT_MANIFEST = te.RESULTS_DIR / "replay_manifest.json"
EXPECTED_CITIES = ["Bengaluru", "Delhi NCR", "Mumbai", "Pune"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    free_before = te.free_ram_mb()
    print(f"free RAM before TensorFlow import: {free_before} MB (minimum {te.MIN_FREE_RAM_MB} MB)", flush=True)
    if free_before < te.MIN_FREE_RAM_MB:
        sys.exit(f"ABORT: only {free_before} MB free RAM; not loading the model.")

    meta = json.loads(METADATA.read_text(encoding="utf-8"))
    if meta["features"] != te.FEATURES or meta["scaled_features"] != te.SCALED or meta["unscaled_features"] != te.UNSCALED:
        sys.exit("ABORT: feature order in model/metadata.json differs from train_eval.py")
    if meta["sequence_length"] != te.SEQ_LEN or meta["horizon"] != te.HORIZON:
        sys.exit("ABORT: window/horizon in metadata differ from train_eval.py")

    hashes_before = {p.name: sha256(p) for p in (MODEL, FEATURE_SCALER, TARGET_SCALER)}

    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "1")
    import joblib
    from tensorflow import keras

    model = keras.models.load_model(MODEL)
    feature_scaler = joblib.load(FEATURE_SCALER)
    target_scaler = joblib.load(TARGET_SCALER)
    if tuple(model.input_shape) != (None, te.SEQ_LEN, len(te.FEATURES)):
        sys.exit(f"ABORT: model input shape {model.input_shape} != (None, {te.SEQ_LEN}, {len(te.FEATURES)})")
    if feature_scaler.n_features_in_ != len(te.SCALED) or target_scaler.n_features_in_ != 1:
        sys.exit("ABORT: scaler shapes do not match the scaled feature list")

    raw = pd.read_csv(te.DATA, parse_dates=["timestamp"])
    cities = sorted(raw.city.unique())
    if cities != EXPECTED_CITIES or cities != meta["cities"]:
        sys.exit(f"ABORT: cities in data {cities} differ from expected {EXPECTED_CITIES}")
    frames = {c: te.city_features(g) for c, g in raw.groupby("city")}
    timeline = frames[cities[0]].index
    val_start, test_start = te.split_bounds(timeline)
    last_ts = timeline.max()

    parts = []
    for city, f in frames.items():
        scaled = feature_scaler.transform(f[te.SCALED].to_numpy())
        feats = np.hstack([scaled, f[te.UNSCALED].to_numpy(float)]).astype(np.float32)
        valid = f.input_valid.to_numpy()
        ok = np.lib.stride_tricks.sliding_window_view(valid, te.SEQ_LEN).all(axis=1)   # window ends at s+23
        starts = np.nonzero(ok)[0]
        X = np.stack([feats[s:s + te.SEQ_LEN] for s in starts])
        if np.isnan(X).any():
            raise AssertionError(f"{city}: NaN inside a window marked valid")
        pred = target_scaler.inverse_transform(model.predict(X, batch_size=1024, verbose=0)).ravel()
        input_end = f.index[starts + te.SEQ_LEN - 1]
        target_time = input_end + pd.Timedelta(hours=te.HORIZON)
        actual = f[te.TARGET].reindex(target_time).to_numpy()            # NaN after the last data hour
        period = np.where(target_time > last_ts, "beyond_data",
                          np.where(target_time < val_start, "train", np.where(target_time < test_start, "val", "test")))
        parts.append(pd.DataFrame({"city": city, "input_end": input_end, "target_time": target_time,
                                   "predicted_utilization": pred, "actual_utilization": actual, "period": period}))
    out = pd.concat(parts, ignore_index=True)

    # ---------------------------------------------------------------- validation (no clipping)
    if not np.isfinite(out.predicted_utilization).all():
        raise AssertionError("non-finite predictions")
    outside = int((~out.predicted_utilization.between(0.0, 1.0)).sum())
    saved = pd.read_csv(te.RESULTS_DIR / "test_predictions.csv", parse_dates=["target_time"])
    joined = saved.merge(out, on=["city", "target_time"], how="left", validate="one_to_one")
    if joined.predicted_utilization.isna().any():
        raise AssertionError("some saved test predictions have no replay counterpart")
    max_diff = float((joined.lstm - joined.predicted_utilization).abs().max())
    actual_diff = float((joined.actual - joined.actual_utilization).abs().max())
    if max_diff > 1e-4 or actual_diff > 1e-6:
        raise AssertionError(f"replay does not reproduce saved test predictions (pred {max_diff}, actual {actual_diff})")
    if {p.name: sha256(p) for p in (MODEL, FEATURE_SCALER, TARGET_SCALER)} != hashes_before:
        raise AssertionError("model or scaler file changed during the run")

    te.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False, float_format="%.6f")
    per_city = out.groupby("city").agg(predictions=("target_time", "size"), first_target=("target_time", "min"),
                                       last_target=("target_time", "max"), pred_min=("predicted_utilization", "min"),
                                       pred_max=("predicted_utilization", "max"))
    manifest = {
        "WARNING": te.WARNING,
        "mode": "historical replay over simulated data; not a live forecast",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "artifacts_sha256": {
            "model/india_synthetic_lstm.keras": hashes_before[MODEL.name],
            "model/feature_scaler.pkl": hashes_before[FEATURE_SCALER.name],
            "model/target_scaler.pkl": hashes_before[TARGET_SCALER.name],
            "data/city_hourly.csv": sha256(te.DATA),
            "results/replay_predictions.csv": sha256(OUT_CSV),
        },
        "split_starts_local": {"val": str(val_start), "test": str(test_start)},
        "last_data_hour_local": str(last_ts),
        "validation": {
            "cities": cities,
            "predictions": int(len(out)),
            "all_finite": True,
            "outside_0_1_unclipped": outside,
            "reproduces_saved_test_predictions_max_abs_diff": max_diff,
            "saved_test_predictions_compared": int(len(joined)),
        },
        "per_city": {c: {k: (str(v) if isinstance(v, pd.Timestamp) else (round(float(v), 6) if isinstance(v, float) else int(v)))
                         for k, v in r.items()} for c, r in per_city.iterrows()},
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest["validation"], indent=2))
    print(per_city.to_string())
    latest = out[out.period != "beyond_data"].sort_values("target_time").groupby("city").tail(1)
    print("latest in-data prediction per city:\n" + latest.to_string(index=False))
    print(f"free RAM after prediction: {te.free_ram_mb()} MB")


if __name__ == "__main__":
    main()
