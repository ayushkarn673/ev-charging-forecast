"""
Phase 2 - train the LSTM demand-forecasting model on the preprocessed sequences.

Input  : dataset/processed/sequences_{train,val}.npz   (scaled by preprocess.py; NOT refitted here)
Model  : LSTM(64, return_sequences) -> Dropout -> LSTM(32) -> Dropout -> Dense(16, relu) -> Dense(1)
Target : next-hour utilization of the 54 installed spaces, in target-scaler units (0..1 on train)
Output : models/ev_demand_lstm.keras        best-validation-loss model
         models/model_config.json          architecture, hyper-parameters, feature metadata
         models/training_history.csv       per-epoch loss / MAE
         models/training_summary.json      best epoch, durations, versions
         docs/figures/training_loss_curves.png

The test split is not touched here (Phase 3).

Run: uv run train.py [--epochs 100 --batch-size 256 --patience 10 --seed 42 ...]
"""
from __future__ import annotations

import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "1")   # hide TensorFlow INFO logs, keep warnings

import argparse  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import platform  # noqa: E402
import time  # noqa: E402
from dataclasses import asdict, dataclass, replace  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import tensorflow as tf  # noqa: E402
from tensorflow import keras  # noqa: E402

import config  # noqa: E402

log = logging.getLogger("train")


# ===================================================================================
# Configuration
# ===================================================================================
@dataclass(frozen=True)
class TrainConfig:
    lstm_units: tuple[int, int] = tuple(config.TRAINING["lstm_units"])
    dropout: float = config.TRAINING["dropout"]
    dense_units: int = config.TRAINING["dense_units"]
    learning_rate: float = config.TRAINING["learning_rate"]
    batch_size: int = config.TRAINING["batch_size"]
    max_epochs: int = config.TRAINING["max_epochs"]
    early_stopping_patience: int = config.TRAINING["early_stopping_patience"]
    seed: int = config.TRAINING["seed"]

    def validate(self) -> "TrainConfig":
        if len(self.lstm_units) != 2 or any(int(u) != u or u < 1 for u in self.lstm_units):
            raise ValueError(f"lstm_units must be two positive integers, got {self.lstm_units}")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError(f"dropout must be in [0, 1), got {self.dropout}")
        if int(self.dense_units) != self.dense_units or self.dense_units < 1:
            raise ValueError(f"dense_units must be a positive integer, got {self.dense_units}")
        if not 0.0 < self.learning_rate < 1.0:
            raise ValueError(f"learning_rate must be in (0, 1), got {self.learning_rate}")
        for name in ("batch_size", "max_epochs"):
            v = getattr(self, name)
            if int(v) != v or v < 1:
                raise ValueError(f"{name} must be a positive integer, got {v}")
        if int(self.early_stopping_patience) != self.early_stopping_patience or self.early_stopping_patience < 1:
            raise ValueError(f"early_stopping_patience must be a positive integer, got {self.early_stopping_patience}")
        if int(self.seed) != self.seed or self.seed < 0:
            raise ValueError(f"seed must be a non-negative integer, got {self.seed}")
        return self


# ===================================================================================
# Model
# ===================================================================================
def build_model(seq_len: int, n_features: int, cfg: TrainConfig) -> keras.Model:
    """The LSTM architecture from the project specification."""
    cfg.validate()
    if seq_len < 1 or n_features < 1:
        raise ValueError(f"seq_len and n_features must be positive, got {seq_len}, {n_features}")
    u1, u2 = cfg.lstm_units
    model = keras.Sequential([
        keras.Input(shape=(seq_len, n_features), name="sequence"),
        keras.layers.LSTM(u1, return_sequences=True, name="lstm_1"),
        keras.layers.Dropout(cfg.dropout, name="dropout_1"),
        keras.layers.LSTM(u2, name="lstm_2"),
        keras.layers.Dropout(cfg.dropout, name="dropout_2"),
        keras.layers.Dense(cfg.dense_units, activation="relu", name="dense"),
        keras.layers.Dense(1, name="utilization_scaled"),
    ], name="ev_demand_lstm")
    model.compile(optimizer=keras.optimizers.Adam(learning_rate=cfg.learning_rate),
                  loss="mse", metrics=[keras.metrics.MeanAbsoluteError(name="mae")])
    return model


def validate_inputs(X: np.ndarray, seq_len: int, n_features: int) -> np.ndarray:
    """Reject anything that is not a finite (n, seq_len, n_features) array."""
    X = np.asarray(X, dtype=np.float32)
    if X.ndim != 3:
        raise ValueError(f"expected a 3-D array (samples, {seq_len}, {n_features}), got shape {X.shape}")
    if X.shape[1] != seq_len:
        raise ValueError(f"expected sequence length {seq_len}, got {X.shape[1]} (insufficient or excess history)")
    if X.shape[2] != n_features:
        raise ValueError(f"expected {n_features} features per time step, got {X.shape[2]}")
    if X.shape[0] == 0:
        raise ValueError("no samples to predict")
    if not np.isfinite(X).all():
        raise ValueError("inputs contain NaN or infinite values")
    return X


def predict_scaled(model: keras.Model, X: np.ndarray) -> np.ndarray:
    """Predictions in target-scaler units, shape (n, 1)."""
    _, seq_len, n_features = model.input_shape
    X = validate_inputs(X, seq_len, n_features)
    return model.predict(X, verbose=0).reshape(-1, 1)


# ===================================================================================
# Data
# ===================================================================================
def load_split(split: str) -> tuple[np.ndarray, np.ndarray]:
    path = config.SEQUENCE_FILES[split]
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run preprocess.py first")
    d = np.load(path)
    return d["X"], d["y"]


def check_preprocessing_outputs(X_train, y_train, X_val, y_val) -> dict:
    """Training must use exactly what preprocess.py produced; fail loudly on any mismatch."""
    fc = json.loads(config.FEATURE_CONFIG_FILE.read_text(encoding="utf-8"))
    if fc["features"] != config.FEATURES:
        raise ValueError("features.json feature order differs from config.FEATURES - rerun preprocess.py")
    expected = (fc["sequence_length"], len(fc["features"]))
    for name, X, y in (("train", X_train, y_train), ("val", X_val, y_val)):
        if X.shape[1:] != expected:
            raise ValueError(f"{name} X shape {X.shape} does not match features.json {expected}")
        if y.ndim != 2 or y.shape != (X.shape[0], 1):
            raise ValueError(f"{name} y shape {y.shape} does not match X {X.shape}")
        if not (np.isfinite(X).all() and np.isfinite(y).all()):
            raise ValueError(f"{name} sequences contain NaN or infinite values")
    return fc


# ===================================================================================
# Training
# ===================================================================================
def set_seed(seed: int) -> None:
    keras.utils.set_random_seed(seed)          # Python, NumPy and TensorFlow RNGs
    tf.config.experimental.enable_op_determinism()


def train(cfg: TrainConfig, X_train, y_train, X_val, y_val, checkpoint_path) -> tuple[keras.Model, pd.DataFrame, float]:
    """
    Fit with early stopping on val_loss. The best-val_loss model is checkpointed and reloaded,
    so the returned model has the best weights whether or not early stopping triggered.
    """
    cfg.validate()
    set_seed(cfg.seed)
    model = build_model(X_train.shape[1], X_train.shape[2], cfg)
    callbacks = [
        keras.callbacks.EarlyStopping(monitor="val_loss", mode="min", patience=cfg.early_stopping_patience,
                                      restore_best_weights=True, verbose=1),
        keras.callbacks.ModelCheckpoint(str(checkpoint_path), monitor="val_loss", mode="min",
                                        save_best_only=True, verbose=0),
    ]
    start = time.perf_counter()
    hist = model.fit(X_train, y_train, validation_data=(X_val, y_val), epochs=cfg.max_epochs,
                     batch_size=cfg.batch_size, shuffle=False, callbacks=callbacks, verbose=2)
    duration = time.perf_counter() - start
    history = pd.DataFrame(hist.history)
    history.insert(0, "epoch", np.arange(1, len(history) + 1))
    best = keras.models.load_model(checkpoint_path)
    return best, history, duration


def summarise(cfg: TrainConfig, model: keras.Model, history: pd.DataFrame, duration: float,
              shapes: dict, X_val, y_val) -> dict:
    best_row = history.loc[history["val_loss"].idxmin()]
    best_epoch = int(best_row["epoch"])
    # Re-evaluate the saved (reloaded) model on validation as a consistency check.
    val_loss, val_mae = model.evaluate(X_val, y_val, batch_size=cfg.batch_size, verbose=0)
    target_scaler = joblib.load(config.TARGET_SCALER_FILE)
    util_per_scaled_unit = float(target_scaler.data_max_[0] - target_scaler.data_min_[0])
    cap = json.loads(config.FEATURE_CONFIG_FILE.read_text(encoding="utf-8"))["installed_capacity_spaces"]
    val_mae_util = float(val_mae) * util_per_scaled_unit
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "epochs_completed": int(len(history)),
        "max_epochs": cfg.max_epochs,
        "stopped_early": bool(len(history) < cfg.max_epochs),
        "best_epoch": best_epoch,
        "best_val_loss_mse_scaled": float(best_row["val_loss"]),
        "val_mae_scaled_at_best_epoch": float(best_row["val_mae"]),
        "train_loss_at_best_epoch": float(best_row["loss"]),
        "train_mae_at_best_epoch": float(best_row["mae"]),
        "final_epoch": {k: float(v) for k, v in history.iloc[-1].items() if k != "epoch"},
        "reloaded_model_val_loss": float(val_loss),
        "reloaded_model_val_mae_scaled": float(val_mae),
        "reloaded_model_val_mae_utilization": round(val_mae_util, 6),
        "reloaded_model_val_mae_spaces": round(val_mae_util * cap, 4),
        "note": "Validation figures only. Training loss includes dropout; test metrics are computed in Phase 3.",
        "training_duration_seconds": round(duration, 2),
        "seconds_per_epoch": round(duration / len(history), 3),
        "trainable_parameters": int(sum(np.prod(w.shape) for w in model.trainable_weights)),
        "data_shapes": shapes,
        "versions": {"python": platform.python_version(), "tensorflow": tf.__version__,
                     "keras": keras.__version__, "numpy": np.__version__},
        "device": "GPU" if tf.config.list_physical_devices("GPU") else "CPU",
        "config": asdict(cfg),
    }


def model_config(cfg: TrainConfig, model: keras.Model, feature_cfg: dict) -> dict:
    layers = [{"name": layer.name, "type": layer.__class__.__name__,
               "output_shape": [None if d is None else int(d) for d in layer.output.shape],
               "parameters": int(layer.count_params())} for layer in model.layers]
    return {
        "model_file": config.MODEL_FILE.name,
        "input_shape": [None, int(model.input_shape[1]), int(model.input_shape[2])],
        "output": "next-hour utilization in target-scaler units; inverse-transform with target_scaler.pkl, "
                  "then multiply by installed_capacity_spaces for occupied spaces",
        "layers": layers,
        "hyperparameters": asdict(cfg),
        "optimizer": "Adam", "loss": "mse", "metrics": ["mae"],
        "early_stopping": {"monitor": "val_loss", "patience": cfg.early_stopping_patience,
                           "restore_best_weights": True, "best_checkpoint_reloaded": True},
        "shuffle": False,
        "feature_metadata": feature_cfg,
    }


def plot_history(history: pd.DataFrame, best_epoch: int) -> None:
    import plot_style
    from plot_style import ACTUAL_COLOR, PREDICTED_COLOR, TEXT_SECONDARY, plt

    plot_style.apply()
    config.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    for ax, key, label in ((axes[0], "loss", "MSE loss"), (axes[1], "mae", "MAE")):
        ax.plot(history["epoch"], history[key], color=ACTUAL_COLOR, label="training")
        ax.plot(history["epoch"], history[f"val_{key}"], color=PREDICTED_COLOR, label="validation")
        ax.axvline(best_epoch, color=TEXT_SECONDARY, linestyle="--", linewidth=1)
        ax.text(best_epoch, 0.6, f"best epoch {best_epoch} ", transform=ax.get_xaxis_transform(),
                ha="right", va="center", color=TEXT_SECONDARY, fontsize=9)
        ax.set_xlabel("Epoch")
        ax.set_ylabel(f"{label} (scaled target)")
        ax.set_title(label)
    axes[0].legend(loc="upper right")
    fig.suptitle("LSTM training history (training loss includes dropout)", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(config.LOSS_FIGURE)
    plt.close(fig)


# ===================================================================================
# CLI
# ===================================================================================
def parse_args(argv=None) -> TrainConfig:
    d = TrainConfig()
    ap = argparse.ArgumentParser(description="Train the EV demand LSTM.")
    ap.add_argument("--units", type=int, nargs=2, default=list(d.lstm_units), metavar=("LSTM1", "LSTM2"))
    ap.add_argument("--dropout", type=float, default=d.dropout)
    ap.add_argument("--dense", type=int, default=d.dense_units)
    ap.add_argument("--lr", type=float, default=d.learning_rate)
    ap.add_argument("--batch-size", type=int, default=d.batch_size)
    ap.add_argument("--epochs", type=int, default=d.max_epochs)
    ap.add_argument("--patience", type=int, default=d.early_stopping_patience)
    ap.add_argument("--seed", type=int, default=d.seed)
    a = ap.parse_args(argv)
    return replace(d, lstm_units=tuple(a.units), dropout=a.dropout, dense_units=a.dense, learning_rate=a.lr,
                   batch_size=a.batch_size, max_epochs=a.epochs, early_stopping_patience=a.patience,
                   seed=a.seed).validate()


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = parse_args(argv)
    X_train, y_train = load_split("train")
    X_val, y_val = load_split("val")
    feature_cfg = check_preprocessing_outputs(X_train, y_train, X_val, y_val)
    shapes = {"X_train": list(X_train.shape), "y_train": list(y_train.shape),
              "X_val": list(X_val.shape), "y_val": list(y_val.shape)}
    log.info("Config: %s", asdict(cfg))
    log.info("Shapes: %s", shapes)

    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model, history, duration = train(cfg, X_train, y_train, X_val, y_val, config.MODEL_FILE)

    summary = summarise(cfg, model, history, duration, shapes, X_val, y_val)
    history.to_csv(config.TRAINING_HISTORY_FILE, index=False)
    config.TRAINING_SUMMARY_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    config.MODEL_CONFIG_FILE.write_text(json.dumps(model_config(cfg, model, feature_cfg), indent=2), encoding="utf-8")
    plot_history(history, summary["best_epoch"])

    log.info("Epochs completed: %d (early stop: %s)", summary["epochs_completed"], summary["stopped_early"])
    log.info("Best epoch %d: val_loss=%.6f val_mae=%.6f (scaled); reloaded model val_loss=%.6f",
             summary["best_epoch"], summary["best_val_loss_mse_scaled"], summary["val_mae_scaled_at_best_epoch"],
             summary["reloaded_model_val_loss"])
    log.info("Training time %.1f s; model saved to %s", duration, config.MODEL_FILE)


if __name__ == "__main__":
    main()
