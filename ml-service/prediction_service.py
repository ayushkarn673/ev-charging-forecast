"""
Forecasting core for the API (Phase 4) - HISTORICAL REPLAY of one-hour-ahead forecasts.

A request gives a forecast time F (the simulated "now", on an hour boundary). The service
predicts utilization for the target hour [F, F+1h) using only observations for hours that
had fully ended by F, i.e. hours F-192h .. F-1h:

  * The observation store holds only the per-hour measurements a live system would have
    recorded: utilization, arrivals, energy_kwh_completed (+ validity flags). Precomputed
    lag/rolling columns from the processed CSV are NOT loaded.
  * For each request the store is cut to rows strictly before F, and every feature is
    recomputed with the same preprocess.py functions used in training (calendar features,
    lag-168, 24-hour rolling mean), then scaled with the saved feature scaler in the
    features.json order.
  * 192 hours are needed: 24 input hours, each needing the value 168 hours earlier.

Output policy:
  raw_utilization        = model output inverse-transformed with the TARGET scaler (kept for diagnostics)
  utilization            = raw clipped to [0, 1]  (warning PREDICTION_CLIPPED when it changes)
  estimated_occupied     = utilization x 54, a time-weighted AVERAGE over the hour (fractional estimate)
  occupied_rounded       = ceil(estimated_occupied)          - conservative: never understates occupancy
  available_rounded      = 54 - occupied_rounded             - so availability is never overstated
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

import config
import preprocess as pp

HOUR = pd.Timedelta(hours=1)
HISTORY_HOURS = config.SEQUENCE_LENGTH + config.WEEKLY_LAG          # 24 + 168 = 192
OBSERVED_COLUMNS = ["utilization", "arrivals", "energy_kwh_completed"]
MODE = "historical_replay"
QUIET_HOURS = range(0, 7)


class ForecastError(Exception):
    status_code = 422
    code = "FORECAST_ERROR"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class UnknownSite(ForecastError):
    status_code = 404
    code = "UNKNOWN_SITE"


class UnsupportedForecastTime(ForecastError):
    status_code = 422
    code = "UNSUPPORTED_FORECAST_TIME"


def _iso_local(ts: pd.Timestamp) -> str:
    return ts.tz_convert(config.LOCAL_TZ).isoformat()


def _iso_utc(ts: pd.Timestamp) -> str:
    return ts.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def load_observations(path=config.HOURLY_SITE_FILE) -> pd.DataFrame:
    """Per-hour measurements only (no derived features), indexed by hour start in UTC."""
    cols = ["timestamp_utc", "split", "confirmed_invalid", "capacity"] + OBSERVED_COLUMNS
    df = pd.read_csv(path, usecols=cols, parse_dates=["timestamp_utc"]).set_index("timestamp_utc")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    if not (df.index.is_monotonic_increasing and df.index.is_unique):
        raise ValueError("observation index must be unique and increasing")
    return df


class EvaluationRangeError(ForecastError):
    status_code = 422
    code = "INVALID_EVALUATION_RANGE"


EVALUATION_SERIES_MAX_DAYS = 31


def load_evaluation_predictions(path=config.TEST_PREDICTIONS_FILE) -> pd.DataFrame | None:
    """Saved Phase 3 test-set predictions (read-only). None if evaluate.py has not been run."""
    if not path.exists():
        return None
    cols = ["target_timestamp_utc", "actual_utilization", "pred_lstm", "pred_previous_hour", "pred_same_hour_last_week"]
    df = pd.read_csv(path, usecols=cols, parse_dates=["target_timestamp_utc"]).set_index("target_timestamp_utc")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.sort_index()


@dataclass
class ForecastService:
    model: object
    feature_scaler: object
    target_scaler: object
    feature_config: dict
    observations: pd.DataFrame
    model_config: dict = field(default_factory=dict)
    training_summary: dict = field(default_factory=dict)
    evaluation: dict = field(default_factory=dict)
    evaluation_predictions: pd.DataFrame | None = None
    model_sha256: str = ""
    loaded_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    # ------------------------------------------------------------------ loading
    @classmethod
    def from_files(cls) -> "ForecastService":
        from tensorflow import keras

        fc = json.loads(config.FEATURE_CONFIG_FILE.read_text(encoding="utf-8"))
        svc = cls(
            model=keras.models.load_model(config.MODEL_FILE),
            feature_scaler=joblib.load(config.FEATURE_SCALER_FILE),
            target_scaler=joblib.load(config.TARGET_SCALER_FILE),
            feature_config=fc,
            observations=load_observations(),
            model_config=json.loads(config.MODEL_CONFIG_FILE.read_text(encoding="utf-8")),
            training_summary=json.loads(config.TRAINING_SUMMARY_FILE.read_text(encoding="utf-8")),
            evaluation=json.loads(config.EVAL_METRICS_FILE.read_text(encoding="utf-8")) if config.EVAL_METRICS_FILE.exists() else {},
            evaluation_predictions=load_evaluation_predictions(),
            model_sha256=hashlib.sha256(config.MODEL_FILE.read_bytes()).hexdigest(),
        )
        svc.check_consistency()
        svc.warm_up()
        return svc

    def warm_up(self) -> None:
        """Trace the model and build the supported-time index so the first request is not slow."""
        self._forward(np.zeros((1, config.SEQUENCE_LENGTH, len(config.FEATURES)), np.float32))
        self.supported_forecast_times()

    def check_consistency(self) -> None:
        fc = self.feature_config
        if fc["features"] != config.FEATURES:
            raise ValueError("features.json order differs from config.FEATURES")
        expected = (None, fc["sequence_length"], len(fc["features"]))
        if tuple(self.model.input_shape) != expected:
            raise ValueError(f"model input shape {self.model.input_shape} != {expected}")
        if tuple(self.model.output_shape) != (None, 1):
            raise ValueError(f"model output shape {self.model.output_shape} != (None, 1)")
        if self.feature_scaler.n_features_in_ != len(fc["scaled_features"]) or self.target_scaler.n_features_in_ != 1:
            raise ValueError("scaler dimensions do not match feature metadata")

    @property
    def site_id(self) -> str:
        return self.feature_config["site"]

    @property
    def capacity(self) -> int:
        return int(self.feature_config["installed_capacity_spaces"])

    # ------------------------------------------------------------------ supported range
    def supported_forecast_times(self) -> pd.DatetimeIndex:
        """Every F whose 192 preceding hours exist, are consecutive and are not confirmed invalid."""
        if getattr(self, "_supported", None) is None:
            obs = self.observations
            ok = (obs["confirmed_invalid"].to_numpy() == 0) & obs[OBSERVED_COLUMNS].notna().all(axis=1).to_numpy()
            follows_previous = np.r_[False, np.diff(obs.index.asi8) == HOUR.value]
            streak = np.zeros(len(obs), dtype=int)       # length of the valid, gap-free run ending at row i
            for i in range(len(obs)):
                if ok[i]:
                    streak[i] = streak[i - 1] + 1 if follows_previous[i] else 1
            self._supported = obs.index[streak >= HISTORY_HOURS] + HOUR
        return self._supported

    def validate_forecast_time(self, forecast_time) -> pd.Timestamp:
        F = pd.Timestamp(forecast_time)
        if F.tzinfo is None:
            raise UnsupportedForecastTime("forecastTime must include a timezone offset (e.g. -08:00 or Z)",
                                          code="TIMEZONE_REQUIRED")
        F = F.tz_convert("UTC")
        if F != F.floor("h"):
            raise UnsupportedForecastTime("forecastTime must be on an hour boundary (minutes and seconds = 0)",
                                          code="NOT_ON_HOUR")
        supported = self.supported_forecast_times()
        if F < supported[0]:
            raise UnsupportedForecastTime(
                f"forecastTime needs {HISTORY_HOURS} hours of earlier observations; the earliest supported "
                f"forecastTime is {_iso_local(supported[0])}", code="INSUFFICIENT_HISTORY")
        if F > supported[-1]:
            raise UnsupportedForecastTime(
                f"forecastTime is after the historical dataset; the latest supported forecastTime is "
                f"{_iso_local(supported[-1])}", code="OUT_OF_RANGE")
        if F not in supported:
            raise UnsupportedForecastTime("not enough valid history in the 192 hours before forecastTime",
                                          code="INSUFFICIENT_HISTORY")
        return F

    # ------------------------------------------------------------------ inputs
    def history_before(self, F: pd.Timestamp) -> pd.DataFrame:
        """Observations for hours that had ended by F: [F-192h, F). Nothing at or after F."""
        obs = self.observations
        hist = obs[(obs.index >= F - HISTORY_HOURS * HOUR) & (obs.index < F)]
        if len(hist) != HISTORY_HOURS:
            raise UnsupportedForecastTime(f"expected {HISTORY_HOURS} hours of history before forecastTime, "
                                          f"found {len(hist)}", code="INSUFFICIENT_HISTORY")
        if (np.diff(hist.index.asi8) != HOUR.value).any():
            raise UnsupportedForecastTime("history before forecastTime has gaps", code="INSUFFICIENT_HISTORY")
        if (hist["confirmed_invalid"] != 0).any() or hist[OBSERVED_COLUMNS].isna().any().any():
            raise UnsupportedForecastTime("history before forecastTime contains invalid observations",
                                          code="INSUFFICIENT_HISTORY")
        return hist

    def build_input(self, F: pd.Timestamp) -> tuple[np.ndarray, pd.DataFrame]:
        """Recompute features from the cut history exactly as in training; return (X, feature rows)."""
        hist = self.history_before(F)
        feats = pp.add_history_features(pp.add_time_features(hist[OBSERVED_COLUMNS]))
        window = feats.iloc[-config.SEQUENCE_LENGTH:]
        if window[config.FEATURES].isna().any().any():
            raise UnsupportedForecastTime("could not compute all input features", code="INSUFFICIENT_HISTORY")
        X = pp.scaled_feature_matrix(window, self.feature_scaler).reshape(1, config.SEQUENCE_LENGTH, -1)
        return X, window

    # ------------------------------------------------------------------ prediction
    def _forward(self, X: np.ndarray) -> np.ndarray:
        """Inference call. Keras models are wrapped once in a compiled tf.function (same weights,
        same outputs) because the eager LSTM call is ~50x slower on CPU."""
        fn = getattr(self, "_compiled", None)
        if fn is None:
            try:
                import tensorflow as tf
                from tensorflow import keras
                if isinstance(self.model, keras.Model):
                    spec = tf.TensorSpec([None, config.SEQUENCE_LENGTH, len(config.FEATURES)], tf.float32)
                    fn = tf.function(lambda x: self.model(x, training=False), input_signature=[spec])
            except ImportError:
                fn = None
            self._compiled = fn = fn or (lambda x: self.model(x, training=False))
        return np.asarray(fn(np.asarray(X, np.float32))).reshape(-1, 1)

    def raw_predict(self, X: np.ndarray) -> float:
        return float(self.target_scaler.inverse_transform(self._forward(X))[0, 0])

    def apply_output_policy(self, raw: float) -> dict:
        util = min(max(raw, 0.0), 1.0)
        occupied = util * self.capacity
        occupied_rounded = int(math.ceil(round(occupied, 6)))
        return {
            "raw_utilization": raw,
            "utilization": util,
            "utilization_percent": round(util * 100, 1),
            "estimated_occupied_spaces": round(occupied, 2),
            "estimated_occupied_spaces_rounded": occupied_rounded,
            "estimated_available_spaces_rounded": self.capacity - occupied_rounded,
            "clipped": util != raw,
        }

    def _warnings(self, F: pd.Timestamp, out: dict) -> list[dict]:
        w = []
        split = self.observations["split"].get(F)
        if split == "train":
            w.append(("IN_SAMPLE_TRAINING_PERIOD", "The target hour is in the training period: the model was fitted "
                      "on this hour, so this is not an out-of-sample forecast."))
        elif split == "val":
            w.append(("MODEL_SELECTION_PERIOD", "The target hour is in the validation period, which was used to choose "
                      "the best training epoch."))
        elif split is None:
            w.append(("OUTCOME_NOT_IN_DATASET", "The target hour is after the end of the dataset; no observed outcome exists."))
        if out["clipped"]:
            w.append(("PREDICTION_CLIPPED", f"Raw model output {out['raw_utilization']:.4f} was clipped to [0, 1]."))

        local = F.tz_convert(config.LOCAL_TZ)
        cal = pp.add_time_features(pd.DataFrame(index=pd.DatetimeIndex([F])))
        ev = self.evaluation
        sub = ev.get("by_subset", {})
        if cal["is_holiday"].iloc[0] == 1:
            msg = "Target hour is a holiday or Institute closure."
            if "holiday" in sub:
                msg += (f" On test-set holidays the LSTM MAE was {sub['holiday']['lstm']['mae_pp']:.2f} pp vs "
                        f"{sub['holiday']['previous_hour']['mae_pp']:.2f} pp for the previous-hour baseline.")
            w.append(("HOLIDAY_TARGET", msg))
        elif cal["is_weekend"].iloc[0] == 1:
            msg = "Target hour is on a weekend."
            if "weekend" in sub:
                msg += (f" On test-set weekends the LSTM MAE was {sub['weekend']['lstm']['mae_pp']:.2f} pp vs "
                        f"{sub['weekend']['previous_hour']['mae_pp']:.2f} pp for the previous-hour baseline.")
            w.append(("WEEKEND_TARGET", msg))
        by_hour = ev.get("mae_pp_by_local_hour", {})
        if by_hour:
            h = local.hour
            lstm_h, prev_h = by_hour["lstm"][h], by_hour["previous_hour"][h]
            if prev_h < lstm_h:
                w.append(("BASELINE_BETTER_AT_THIS_HOUR",
                          f"At {h:02d}:00 the previous-hour baseline had lower test MAE ({prev_h:.2f} pp) than the "
                          f"LSTM ({lstm_h:.2f} pp)."))
        return [{"code": c, "message": m} for c, m in w]

    def predict_next_hour(self, forecast_time, site_id: str | None = None) -> dict:
        if site_id is not None and site_id != self.site_id:
            raise UnknownSite(f"unknown siteId '{site_id}'; the only supported site is '{self.site_id}'")
        F = self.validate_forecast_time(forecast_time)
        X, window = self.build_input(F)
        out = self.apply_output_policy(self.raw_predict(X))
        target_end = F + HOUR

        observed = None
        if F in self.observations.index:
            u = float(self.observations.at[F, "utilization"])
            observed = {"utilization": u, "utilization_percent": round(u * 100, 1),
                        "average_occupied_spaces": round(u * self.capacity, 2),
                        "note": "Recorded outcome of the target hour, shown for comparison only. It was not "
                                "available at forecastTime and is never used as model input."}

        return {
            "mode": MODE,
            "is_simulation": True,
            "notice": "Historical replay: a forecast reconstructed as if it had been made at forecastTime, using "
                      "only ACN-Data observations that existed by then. This is not live data.",
            "site_id": self.site_id,
            "installed_capacity_spaces": self.capacity,
            "forecast_time": _iso_local(F),
            "forecast_time_utc": _iso_utc(F),
            "target_start": _iso_local(F),
            "target_end": _iso_local(target_end),
            "horizon_hours": config.HORIZON,
            "inputs": {
                "first_input_hour": _iso_local(window.index[0]),
                "last_input_hour": _iso_local(window.index[-1]),
                "earliest_observation_used": _iso_local(F - HISTORY_HOURS * HOUR),
                "latest_observation_used": _iso_local(F - HOUR),
                "sequence_length": config.SEQUENCE_LENGTH,
                "features": config.FEATURES,
            },
            "prediction": {k: out[k] for k in ("utilization", "utilization_percent", "estimated_occupied_spaces",
                                                "estimated_occupied_spaces_rounded",
                                                "estimated_available_spaces_rounded", "raw_utilization")},
            "rounding_policy": "estimatedOccupiedSpaces is a time-weighted hourly average (estimate). The rounded "
                               "occupied count uses ceiling and available = capacity - rounded occupied, so "
                               "availability is never overstated. Utilization is clipped to [0, 1]; the raw model "
                               "output is kept in rawUtilization.",
            "observed_outcome": observed,
            "model_id": f"ev_demand_lstm@sha256:{self.model_sha256[:12]}",
            "warnings": self._warnings(F, out),
        }

    # ------------------------------------------------------------------ metadata
    def available_dates(self) -> dict:
        sup = self.supported_forecast_times()
        split_of_target = self.observations["split"].reindex(sup)
        periods = {}
        for s in ("train", "val", "test"):
            t = sup[split_of_target.to_numpy() == s]
            if len(t):
                periods[s] = {"first_forecast_time": _iso_local(t[0]), "last_forecast_time": _iso_local(t[-1]),
                              "forecast_hours": int(len(t))}
        after = sup[split_of_target.isna().to_numpy()]
        local_days = sorted(set(sup.tz_convert(config.LOCAL_TZ).strftime("%Y-%m-%d")))
        return {
            "mode": MODE,
            "site_id": self.site_id,
            "timezone": config.LOCAL_TZ,
            "first_forecast_time": _iso_local(sup[0]),
            "last_forecast_time": _iso_local(sup[-1]),
            "supported_forecast_hours": int(len(sup)),
            "forecast_times_without_observed_outcome": [_iso_local(t) for t in after],
            "periods_by_target_split": periods,
            "recommended_out_of_sample_period": "test",
            "local_dates": local_days,
            "rule": "forecastTime must be on the hour, with a timezone offset, and have 192 consecutive valid "
                    "hours of observations before it.",
        }

    # ------------------------------------------------------------------ saved evaluation (read-only)
    def evaluation_summary(self) -> dict:
        """Phase 3 test-set metrics exactly as saved by evaluate.py. No inference is run here."""
        ev = self.evaluation
        if not ev:
            raise ForecastError("no saved evaluation found; run evaluate.py", code="EVALUATION_NOT_AVAILABLE")
        keep = ("n", "mae_pp", "rmse_pp", "mae_spaces", "rmse_spaces", "bias_pp", "wape_percent")
        meta = ev.get("meta", {})
        return {
            "source": "Saved Phase 3 evaluation on the untouched test split (models/evaluation); not live data.",
            "model_id": f"ev_demand_lstm@sha256:{self.model_sha256[:12]}",
            "test_period_local": [meta.get("test_first_target_local"), meta.get("test_last_target_local")],
            "horizon_hours": config.HORIZON,
            "installed_capacity_spaces": self.capacity,
            "overall": {k: {m: v[m] for m in keep} for k, v in ev["overall"].items()},
            "comparisons": ev.get("comparisons", {}),
            "by_subset": ev.get("by_subset", {}),
            "mae_pp_by_local_hour": ev.get("mae_pp_by_local_hour", {}),
            "series_available": self.evaluation_predictions is not None,
            "default_series_window": list(config.ZOOM_WINDOW_LOCAL),
        }

    def evaluation_series(self, start, end) -> dict:
        """Saved actual vs predicted utilization for target hours whose local date is in [start, end]."""
        df = self.evaluation_predictions
        if df is None:
            raise ForecastError("no saved test predictions found; run evaluate.py", code="EVALUATION_NOT_AVAILABLE")
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        if end < start:
            raise EvaluationRangeError("end must not be before start")
        if (end - start).days + 1 > EVALUATION_SERIES_MAX_DAYS:
            raise EvaluationRangeError(f"at most {EVALUATION_SERIES_MAX_DAYS} days per request")
        local = df.index.tz_convert(config.LOCAL_TZ)
        days = local.tz_localize(None).normalize()
        mask = (days >= start) & (days <= end)
        first, last = local.min().date(), local.max().date()
        if not mask.any():
            raise EvaluationRangeError(f"no test-set predictions in that range; the test period is {first} to {last}")
        part, part_local = df[mask], local[mask]
        rows = [{"target_time": t.isoformat(), "actual": round(float(r.actual_utilization), 6),
                 "lstm": round(float(r.pred_lstm), 6), "previous_hour": round(float(r.pred_previous_hour), 6),
                 "same_hour_last_week": round(float(r.pred_same_hour_last_week), 6)}
                for t, r in zip(part_local, part.itertuples())]
        return {"source": "Saved Phase 3 test-set predictions (models/evaluation/test_predictions.csv); no new inference.",
                "units": "utilization ratio (0..1)", "start": str(start.date()), "end": str(end.date()),
                "test_period": [str(first), str(last)], "points": rows}

    def model_info(self) -> dict:
        ev, ts, mc = self.evaluation, self.training_summary, self.model_config
        overall = ev.get("overall", {})
        return {
            "model_id": f"ev_demand_lstm@sha256:{self.model_sha256[:12]}",
            "model_file": f"models/{config.MODEL_FILE.name}",
            "model_sha256": self.model_sha256,
            "mode": MODE,
            "site_id": self.site_id,
            "installed_capacity_spaces": self.capacity,
            "horizon_hours": config.HORIZON,
            "validated_horizons_hours": [1],
            "input_shape": [None, config.SEQUENCE_LENGTH, len(config.FEATURES)],
            "features": config.FEATURES,
            "target": self.feature_config["target_definition"],
            "architecture": [{"name": l["name"], "type": l["type"], "output_shape": l["output_shape"]}
                             for l in mc.get("layers", [])],
            "training": {"best_epoch": ts.get("best_epoch"), "epochs_completed": ts.get("epochs_completed"),
                         "best_val_loss_mse_scaled": ts.get("best_val_loss_mse_scaled")},
            "test_evaluation": {
                k: {"mae_pp": round(v["mae_pp"], 3), "rmse_pp": round(v["rmse_pp"], 3),
                    "mae_spaces": round(v["mae_spaces"], 3), "n": v["n"]} for k, v in overall.items()},
            "test_period": [ev.get("meta", {}).get("test_first_target_local"), ev.get("meta", {}).get("test_last_target_local")],
            "limitations": [
                "Validated for one-hour-ahead forecasts only; longer horizons are not evaluated.",
                "Historical replay of ACN-Data (Caltech, Nov 2018 - Feb 2020); not live data.",
                "Single site; results may not generalise to other sites.",
                "Utilization is relative to 54 installed spaces, not operational capacity.",
                "On test-set weekends, holidays and several quiet hours the previous-hour baseline had lower MAE.",
            ],
            "loaded_at_utc": self.loaded_at_utc,
        }
