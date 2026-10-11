"""
SYNTHETIC-DEMAND EXPERIMENT - step 2: train and evaluate an LSTM on simulated city-hourly
utilization (data/city_hourly.csv, built by prepare.py). Results describe how well the model
learns the dataset generator's patterns; they are NOT evidence of real-world Indian EV
charging forecast accuracy.

Mirrors the production pipeline in ml-service/ (copied, not imported, so ml-service is untouched):
  * 24 hourly steps x 11 features -> utilization one hour ahead
  * LSTM(64, return_sequences) -> Dropout(0.2) -> LSTM(32) -> Dropout(0.2) -> Dense(16, relu) -> Dense(1)
  * Adam 1e-3, MSE loss, batch 256, max 300 epochs, early stopping on val_loss (patience 10,
    best weights restored), seed 42, op determinism, no shuffling
  * chronological 70/15/15 split snapped to local midnight; windows never cross a split
  * MinMax scalers fitted on valid TRAINING rows only

Adaptations for pooled multi-city data (documented in README.md):
  * arrivals            -> demand_per_charger = demand_vehicles / installed_chargers
  * energy_kwh_completed -> energy_per_charger = energy_kwh / installed_chargers
    (per-charger so one scaler serves cities of very different size)
  * is_holiday          -> generator festival windows (Sundays are already in is_weekend)
  * one model for all four cities; training windows ordered by target time, then city

Run from the repo root (uses the ml-service interpreter, installs nothing):
    ml-service/.venv/Scripts/python.exe -I -B experiments/india_ev_lstm/train_eval.py
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "city_hourly.csv"
MODEL_DIR = HERE / "model"
RESULTS_DIR = HERE / "results"
MIN_FREE_RAM_MB = 1536

SEQ_LEN, HORIZON, WEEKLY_LAG, ROLL = 24, 1, 168, 24
SPLIT_RATIOS = (0.70, 0.15, 0.15)
SPLITS = ("train", "val", "test")
TARGET = "utilization"
SCALED = ["utilization", "utilization_lag_168", "utilization_roll_mean_24", "demand_per_charger", "energy_per_charger"]
UNSCALED = ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend", "is_holiday"]
FEATURES = SCALED + UNSCALED
HP = {"lstm_units": [64, 32], "dropout": 0.2, "dense_units": 16, "learning_rate": 0.001, "batch_size": 256,
      "max_epochs": 300, "early_stopping_patience": 10, "seed": 42}
WARNING = ("SYNTHETIC-DEMAND EXPERIMENT: hourly demand is simulated by the dataset generator; "
           "results do not measure real-world Indian EV charging forecast accuracy.")


# ----------------------------------------------------------------------------- memory guard
def free_ram_mb() -> int:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    s = MEMORYSTATUSEX()
    s.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return int(s.ullAvailPhys / 2 ** 20)


# ----------------------------------------------------------------------------- features
def city_features(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("timestamp").set_index("timestamp").copy()
    g["utilization_lag_168"] = g[TARGET].shift(WEEKLY_LAG)
    g["utilization_roll_mean_24"] = g[TARGET].rolling(ROLL, min_periods=ROLL).mean()
    g["demand_per_charger"] = g.demand_vehicles / g.installed_chargers
    g["energy_per_charger"] = g.energy_kwh / g.installed_chargers
    hour, dow = g.index.hour, g.index.dayofweek
    g["hour_sin"], g["hour_cos"] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
    g["dow_sin"], g["dow_cos"] = np.sin(2 * np.pi * dow / 7), np.cos(2 * np.pi * dow / 7)
    g["is_weekend"] = (dow >= 5).astype(int)
    g["is_holiday"] = g.is_festival.astype(int)
    g["input_valid"] = g[FEATURES].notna().all(axis=1)
    return g


def split_bounds(index: pd.DatetimeIndex) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Ratio boundaries snapped to the nearest midnight on the shared hourly timeline."""
    n = len(index)
    midnights = np.nonzero(index.hour == 0)[0]
    snap = lambda pos: int(midnights[np.argmin(np.abs(midnights - pos))])  # noqa: E731
    b1, b2 = snap(int(n * SPLIT_RATIOS[0])), snap(int(n * (SPLIT_RATIOS[0] + SPLIT_RATIOS[1])))
    if not 0 < b1 < b2 < n:
        raise ValueError("split boundaries collapsed")
    return index[b1], index[b2]


def windows(feats: np.ndarray, target: np.ndarray, valid: np.ndarray):
    """X[k] = feats[i:i+24], y[k] = target[i+24]; inputs must all be valid. One split, one city."""
    n_win = len(feats) - SEQ_LEN - HORIZON + 1
    ok = np.lib.stride_tricks.sliding_window_view(valid, SEQ_LEN)[:n_win].all(axis=1)
    starts = np.nonzero(ok)[0]
    X = np.stack([feats[s:s + SEQ_LEN] for s in starts]).astype(np.float32)
    pos = starts + SEQ_LEN + HORIZON - 1
    return X, target[pos].astype(np.float32).reshape(-1, 1), pos


# ----------------------------------------------------------------------------- metrics
def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    e = p - y
    return {"n": int(len(y)), "mae_pp": float(np.abs(e).mean() * 100), "rmse_pp": float(np.sqrt((e ** 2).mean()) * 100),
            "wape_percent": float(np.abs(e).sum() / np.abs(y).sum() * 100), "bias_pp": float(e.mean() * 100)}


def block_bootstrap_mae_diff(df: pd.DataFrame, a: str, b: str, n_boot=2000, seed=42) -> dict:
    """95% interval of MAE(a) - MAE(b) in pp, resampling whole days (all cities together)."""
    rng = np.random.default_rng(seed)
    day = df.target_time.dt.normalize()
    per_day = df.assign(day=day, ea=(df[a] - df.actual).abs(), eb=(df[b] - df.actual).abs()).groupby("day")[["ea", "eb"]].agg(["sum", "count"])
    sa, sb, cnt = per_day[("ea", "sum")].to_numpy(), per_day[("eb", "sum")].to_numpy(), per_day[("ea", "count")].to_numpy()
    idx = rng.integers(0, len(cnt), (n_boot, len(cnt)))
    diffs = (sa[idx].sum(1) - sb[idx].sum(1)) / cnt[idx].sum(1) * 100
    point = (sa.sum() - sb.sum()) / cnt.sum() * 100
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"mae_diff_pp": float(point), "ci95_pp": [float(lo), float(hi)], "days": int(len(cnt)), "resamples": n_boot}


# ----------------------------------------------------------------------------- main
def main() -> None:
    free = free_ram_mb()
    print(f"free RAM before TensorFlow import: {free} MB (minimum {MIN_FREE_RAM_MB} MB)", flush=True)
    if free < MIN_FREE_RAM_MB:
        sys.exit(f"ABORT: only {free} MB free RAM; not training.")

    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "1")
    import joblib
    import tensorflow as tf
    from sklearn.preprocessing import MinMaxScaler
    from tensorflow import keras

    keras.utils.set_random_seed(HP["seed"])
    tf.config.experimental.enable_op_determinism()

    raw = pd.read_csv(DATA, parse_dates=["timestamp"])
    frames = {c: city_features(g) for c, g in raw.groupby("city")}
    timeline = frames[next(iter(frames))].index
    val_start, test_start = split_bounds(timeline)
    for f in frames.values():
        if not f.index.equals(timeline):
            raise ValueError("cities do not share one hourly timeline")
        f["split"] = np.where(f.index < val_start, "train", np.where(f.index < test_start, "val", "test"))

    allrows = pd.concat(frames.values())
    train_rows = allrows[(allrows.split == "train") & allrows.input_valid]
    feature_scaler = MinMaxScaler().fit(train_rows[SCALED].to_numpy())
    target_scaler = MinMaxScaler().fit(train_rows[[TARGET]].to_numpy())

    data = {s: {"X": [], "y": [], "actual": [], "prev": [], "week": [], "time": [], "city": []} for s in SPLITS}
    for city, f in frames.items():
        for s in SPLITS:
            part = f[f.split == s]
            feats = np.hstack([feature_scaler.transform(part[SCALED].to_numpy()), part[UNSCALED].to_numpy(float)])
            tgt = target_scaler.transform(part[[TARGET]].to_numpy()).ravel()
            X, y, pos = windows(np.nan_to_num(feats, nan=0.0), tgt, part.input_valid.to_numpy())
            if np.isnan(X).any() or np.isnan(y).any():
                raise AssertionError(f"NaN in {city}/{s} sequences")
            ttime = part.index[pos]
            full_pos = f.index.get_indexer(ttime)
            u = f[TARGET].to_numpy()
            d = data[s]
            d["X"].append(X); d["y"].append(y)
            d["actual"].append(u[full_pos])
            d["prev"].append(u[full_pos - 1])                     # last observed hour (input step t)
            d["week"].append(u[full_pos - WEEKLY_LAG])            # same hour one week before the target
            d["time"].append(ttime.to_numpy()); d["city"].append(np.full(len(pos), city))
    for s in SPLITS:
        d = data[s]
        for k in d:
            d[k] = np.concatenate(d[k])
        order = np.lexsort((d["city"], d["time"]))                # chronological, cities interleaved
        for k in d:
            d[k] = d[k][order]
        if s != "train":
            assert d["time"].min() > data["train"]["time"].max(), "evaluation targets must follow training targets"
    print({s: data[s]["X"].shape for s in SPLITS}, flush=True)

    MODEL_DIR.mkdir(parents=True, exist_ok=True); RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    u1, u2 = HP["lstm_units"]
    model = keras.Sequential([
        keras.Input(shape=(SEQ_LEN, len(FEATURES))),
        keras.layers.LSTM(u1, return_sequences=True, name="lstm_1"),
        keras.layers.Dropout(HP["dropout"], name="dropout_1"),
        keras.layers.LSTM(u2, name="lstm_2"),
        keras.layers.Dropout(HP["dropout"], name="dropout_2"),
        keras.layers.Dense(HP["dense_units"], activation="relu", name="dense"),
        keras.layers.Dense(1, name="utilization_scaled"),
    ], name="india_ev_synthetic_lstm")
    model.compile(optimizer=keras.optimizers.Adam(learning_rate=HP["learning_rate"]), loss="mse",
                  metrics=[keras.metrics.MeanAbsoluteError(name="mae")])

    model_path = MODEL_DIR / "india_synthetic_lstm.keras"
    callbacks = [
        keras.callbacks.EarlyStopping(monitor="val_loss", mode="min", patience=HP["early_stopping_patience"],
                                      restore_best_weights=True),
        keras.callbacks.ModelCheckpoint(str(model_path), monitor="val_loss", mode="min", save_best_only=True),
    ]
    t0 = time.perf_counter()
    hist = model.fit(data["train"]["X"], data["train"]["y"], validation_data=(data["val"]["X"], data["val"]["y"]),
                     epochs=HP["max_epochs"], batch_size=HP["batch_size"], shuffle=False, callbacks=callbacks, verbose=2)
    train_seconds = time.perf_counter() - t0
    model = keras.models.load_model(model_path)                   # best-val_loss checkpoint
    history = pd.DataFrame(hist.history); history.index.name = "epoch"; history.index += 1
    history.to_csv(RESULTS_DIR / "training_history.csv")
    best_epoch = int(history.val_loss.idxmin())

    joblib.dump(feature_scaler, MODEL_DIR / "feature_scaler.pkl")
    joblib.dump(target_scaler, MODEL_DIR / "target_scaler.pkl")

    # ---------------------------------------------------------------- evaluation (val + held-out test)
    rows, preds = [], {}
    for s in ("val", "test"):
        d = data[s]
        p = target_scaler.inverse_transform(model.predict(d["X"], batch_size=1024, verbose=0)).ravel()
        preds[s] = pd.DataFrame({"target_time": pd.to_datetime(d["time"]), "city": d["city"], "actual": d["actual"],
                                 "lstm": p, "previous_hour": d["prev"], "same_hour_last_week": d["week"]})
        for scope, g in [("ALL", preds[s])] + list(preds[s].groupby("city")):
            for m in ("lstm", "previous_hour", "same_hour_last_week"):
                rows.append({"split": s, "city": scope, "model": m, **metrics(g.actual.to_numpy(), g[m].to_numpy())})
    table = pd.DataFrame(rows)
    table.to_csv(RESULTS_DIR / "metrics.csv", index=False, float_format="%.4f")
    test = preds["test"]
    test.to_csv(RESULTS_DIR / "test_predictions.csv", index=False, float_format="%.6f")
    boot = {b: block_bootstrap_mae_diff(test, "lstm", b) for b in ("previous_hour", "same_hour_last_week")}

    split_info = {s: [str(frames[next(iter(frames))].index[frames[next(iter(frames))].split == s].min()),
                      str(frames[next(iter(frames))].index[frames[next(iter(frames))].split == s].max())] for s in SPLITS}
    summary = {
        "WARNING": WARNING,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "training_seconds": round(train_seconds, 1),
        "epochs_completed": int(len(history)), "best_epoch": best_epoch,
        "best_val_loss_mse_scaled": float(history.val_loss.min()),
        "windows": {s: int(len(data[s]["y"])) for s in SPLITS},
        "split_periods_local_target_hours": split_info,
        "test_bootstrap_lstm_minus_baseline": boot,
        "environment": {"python": platform.python_version(), "tensorflow": tf.__version__, "keras": keras.__version__},
    }
    (RESULTS_DIR / "training_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    meta = {
        "WARNING": WARNING,
        "data": "data/city_hourly.csv (see data/source_manifest.json for source hashes and provenance)",
        "cities": sorted(frames), "timezone": "Asia/Kolkata (naive timestamps)",
        "target": TARGET, "target_definition": "sum(chargers_occupied) / sum(installed total_chargers), per city-hour",
        "capacity_mode": "installed_fixed", "sequence_length": SEQ_LEN, "horizon": HORIZON,
        "features": FEATURES, "scaled_features": SCALED, "unscaled_features": UNSCALED,
        "feature_notes": {"demand_per_charger": "replaces production 'arrivals'",
                          "energy_per_charger": "replaces production 'energy_kwh_completed'",
                          "is_holiday": "generator festival windows only; Sundays are covered by is_weekend"},
        "split_ratios": list(SPLIT_RATIOS), "split_periods_local_target_hours": split_info,
        "scalers": {"feature_scaler": "feature_scaler.pkl", "target_scaler": "target_scaler.pkl",
                    "fitted_on": "valid training rows only, all four cities pooled"},
        "architecture": [l.name + ":" + type(l).__name__ for l in model.layers],
        "parameters": int(model.count_params()), "input_shape": [None, SEQ_LEN, len(FEATURES)],
        "hyperparameters": HP, "optimizer": "Adam", "loss": "mse", "shuffle": False,
        "model_file": model_path.name,
    }
    (MODEL_DIR / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    pd.set_option("display.width", 160)
    print(f"\ntraining {train_seconds:.1f}s, epochs {len(history)}, best epoch {best_epoch}")
    print(table[table.split == "test"].pivot_table(index="city", columns="model", values=["mae_pp", "rmse_pp"]).round(3))
    print(json.dumps(boot, indent=2))


if __name__ == "__main__":
    main()
