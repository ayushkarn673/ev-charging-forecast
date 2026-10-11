"""Pure helpers for the experimental India dashboard (no Streamlit, no TensorFlow)."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "city_hourly.csv"
REPLAY = HERE / "results" / "replay_predictions.csv"
MANIFEST = HERE / "results" / "replay_manifest.json"
METRICS = HERE / "results" / "metrics.csv"

CITIES = ["Pune", "Mumbai", "Delhi NCR", "Bengaluru"]
BANNER = ("Experimental model trained on simulated Indian EV charging data. "
          "Results do not establish real-world forecasting accuracy.")
PERIODS = {
    "train": "Training period: the model saw this hour during training (in-sample)",
    "val": "Validation period: used to choose the stopping epoch",
    "test": "Held-out test period: never used for training",
    "beyond_data": "After the last hour in the dataset: no actual value to compare",
}
# Same bands as the production pricing policy (backend application.yml): lower bounds inclusive.
DEMAND_BANDS = [(0.90, "Very high", "red"), (0.70, "High", "orange"), (0.40, "Moderate", "blue"), (0.0, "Low", "green")]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def integrity_problems(base: Path = HERE) -> list[str]:
    """Files whose current hash differs from the one recorded when the replay was generated."""
    manifest = json.loads((base / "results" / "replay_manifest.json").read_text(encoding="utf-8"))
    problems = []
    for rel, expected in manifest["artifacts_sha256"].items():
        path = base / rel
        if not path.exists():
            problems.append(f"{rel} is missing")
        elif sha256(path) != expected:
            problems.append(f"{rel} changed after the predictions were generated")
    return problems


def demand_category(utilization: float) -> tuple[str, str] | None:
    """(label, colour) for a utilization in [0, 1]; None if it is not finite or out of range."""
    if not math.isfinite(utilization) or not 0.0 <= utilization <= 1.0:
        return None
    for lower, label, colour in DEMAND_BANDS:
        if utilization >= lower:
            return label, colour
    return None


def load_history(path: Path = DATA) -> pd.DataFrame:
    return pd.read_csv(path, usecols=["city", "timestamp", "occupied", "installed_chargers", "utilization"],
                       parse_dates=["timestamp"])


def load_replay(path: Path = REPLAY) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["input_end", "target_time"])


def lookup(replay: pd.DataFrame, city: str, target_time: pd.Timestamp) -> pd.Series | None:
    rows = replay[(replay.city == city) & (replay.target_time == target_time)]
    return None if rows.empty else rows.iloc[0]


def chart_frame(history: pd.DataFrame, replay: pd.DataFrame, city: str, target_time: pd.Timestamp,
                days: int = 7) -> pd.DataFrame:
    """Actual vs replayed next-hour prediction (percent) for one city, the `days` before target_time."""
    start = target_time - pd.Timedelta(days=days)
    h = history[(history.city == city) & history.timestamp.between(start, target_time)]
    r = replay[(replay.city == city) & replay.target_time.between(start, target_time)]
    frame = pd.DataFrame(index=pd.DatetimeIndex(sorted(set(h.timestamp) | set(r.target_time)), name="time"))
    frame["Actual utilization (%)"] = h.set_index("timestamp").utilization.reindex(frame.index) * 100
    frame["LSTM next-hour replay (%)"] = r.set_index("target_time").predicted_utilization.reindex(frame.index) * 100
    return frame


def city_test_metrics(city: str, path: Path = METRICS) -> pd.DataFrame:
    m = pd.read_csv(path)
    m = m[(m.split == "test") & (m.city == city)].set_index("model")
    return m[["mae_pp", "rmse_pp", "wape_percent"]].rename(
        index={"lstm": "LSTM", "previous_hour": "Previous hour", "same_hour_last_week": "Same hour last week"},
        columns={"mae_pp": "MAE (pp)", "rmse_pp": "RMSE (pp)", "wape_percent": "WAPE (%)"}).round(2)
