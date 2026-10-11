"""
India EV demand forecasting model (Pune, Mumbai, Delhi NCR, Bengaluru): the primary model on the
Model insights page. Trained on simulated data; its predictions are historical replays.

Reads the validated historical-replay predictions written by experiments/india_ev_lstm/replay_predict.py.
It never loads TensorFlow and never calls the backend: these simulated predictions are not used for
booking availability or prices. Before anything is shown, the model, scalers, data and predictions
are checked against the hashes recorded in results/replay_manifest.json, and the model metadata
against the expected 24-hour × 11-feature input.

Folder: EVCHARGE_INDIA_DIR, default <repo>/experiments/india_ev_lstm.
Timestamps in the files are naive India Standard Time (UTC+05:30, no daylight saving).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from evcharge.fmt import demand_badge

CITIES = ["Pune", "Mumbai", "Delhi NCR", "Bengaluru"]
NOTICE = ("India EV demand forecasting model. This version was trained on simulated Indian EV charging data. "
          "Historical replay predictions are not live forecasts.")
FEATURES = ["utilization", "utilization_lag_168", "utilization_roll_mean_24", "demand_per_charger",
            "energy_per_charger", "hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend", "is_holiday"]
SEQ_LEN = 24
CHART_DAYS = 7
# Same bands as the production pricing policy (backend application.yml); lower bounds inclusive.
BANDS = [(0.90, "VERY_HIGH"), (0.70, "HIGH"), (0.40, "MEDIUM"), (0.0, "LOW")]
PERIODS = {
    "train": "Training period (in-sample: the model saw this hour while training)",
    "val": "Validation period (used to choose the stopping epoch)",
    "test": "Held-out test period (never used for training)",
    "beyond_data": "After the last hour in the dataset (no actual value)",
}


def india_dir() -> Path:
    default = Path(__file__).resolve().parents[2] / "experiments" / "india_ev_lstm"
    return Path(os.environ.get("EVCHARGE_INDIA_DIR", default))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def validation_problems(base: Path) -> list[str]:
    """Reasons the saved replay must not be shown (empty list = valid). Reads only small files."""
    manifest_path, metadata_path = base / "results" / "replay_manifest.json", base / "model" / "metadata.json"
    for p in (manifest_path, metadata_path):
        if not p.exists():
            return [f"{p.relative_to(base).as_posix()} is missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    problems = []
    if metadata.get("features") != FEATURES or metadata.get("sequence_length") != SEQ_LEN or metadata.get("horizon") != 1:
        problems.append("model metadata does not describe the expected 24-hour × 11-feature, 1-hour-ahead model")
    if sorted(metadata.get("cities", [])) != sorted(CITIES) or sorted(manifest.get("validation", {}).get("cities", [])) != sorted(CITIES):
        problems.append("model metadata or replay manifest does not list the four expected cities")
    if manifest.get("validation", {}).get("all_finite") is not True:
        problems.append("replay manifest does not confirm that all predictions are finite")
    for rel, expected in manifest.get("artifacts_sha256", {}).items():
        path = base / rel
        if not path.exists():
            problems.append(f"{rel} is missing")
        elif _sha256(path) != expected:
            problems.append(f"{rel} changed after the replay predictions were generated")
    if "results/replay_predictions.csv" not in manifest.get("artifacts_sha256", {}):
        problems.append("replay manifest has no hash for the predictions file")
    return problems


@st.cache_data(show_spinner=False)
def load_replay(path: str, sha256: str) -> pd.DataFrame:   # sha256 keys the cache to the validated file
    return pd.read_csv(path, parse_dates=["input_end", "target_time"])


@st.cache_data(show_spinner=False)
def load_history(path: str, sha256: str) -> pd.DataFrame:
    return pd.read_csv(path, usecols=["city", "timestamp", "installed_chargers", "utilization"], parse_dates=["timestamp"])


def demand_level(utilization: float) -> str | None:
    """Production band code for a utilization in [0, 1]; None if non-finite or outside 0–1 (never clipped)."""
    if not math.isfinite(utilization) or not 0.0 <= utilization <= 1.0:
        return None
    return next(level for lower, level in BANDS if utilization >= lower)


def lookup(replay: pd.DataFrame, city: str, target: pd.Timestamp) -> pd.Series | None:
    rows = replay[(replay.city == city) & (replay.target_time == target)]
    return None if rows.empty else rows.iloc[0]


def comparison_frame(replay: pd.DataFrame, city: str, target: pd.Timestamp, days: int = CHART_DAYS) -> pd.DataFrame | None:
    """Actual vs predicted (%) for the `days` before and including target; None if that history is incomplete."""
    start = target - pd.Timedelta(days=days)
    r = replay[(replay.city == city) & replay.target_time.between(start, target)].set_index("target_time").sort_index()
    if len(r) != days * 24 + 1 or r.actual_utilization.isna().any():
        return None
    frame = r[["actual_utilization", "predicted_utilization"]].rename(
        columns={"actual_utilization": "Actual (simulated)", "predicted_utilization": "India LSTM prediction"}) * 100
    frame.index.name = "IST"
    return frame


def city_test_metrics(base: Path, city: str) -> pd.DataFrame:
    m = pd.read_csv(base / "results" / "metrics.csv")
    m = m[(m.split == "test") & (m.city == city)].set_index("model")
    names = {"lstm": "India LSTM", "previous_hour": "Baseline: previous hour", "same_hour_last_week": "Baseline: same hour last week"}
    return (m.loc[list(names), ["mae_pp", "rmse_pp", "wape_percent"]].rename(index=names)
            .rename(columns={"mae_pp": "MAE (pp)", "rmse_pp": "RMSE (pp)", "wape_percent": "WAPE (%)"}).round(2))


# ---------------------------------------------------------------- page section
def render() -> None:
    st.info(NOTICE, icon=":material/info:")
    st.caption("All times are **India Standard Time (IST, UTC+05:30)**. The dataset stores local times without an "
               "offset; they are read as IST. A prediction for 18:00 covers the hour 18:00–19:00 and uses only the "
               "24 hours up to 17:00–18:00. They are not live station demand and are not used for slot availability "
               "or prices: booking prices come from the backend's pricing service, which uses the Caltech model.")

    base = india_dir()
    problems = validation_problems(base)
    if problems:
        st.error("**India model results are unavailable.** The saved predictions could not be validated against "
                 "the model and data:\n\n- " + "\n- ".join(problems), icon=":material/error:")
        return
    manifest = json.loads((base / "results" / "replay_manifest.json").read_text(encoding="utf-8"))
    hashes = manifest["artifacts_sha256"]
    replay = load_replay(str(base / "results" / "replay_predictions.csv"), hashes["results/replay_predictions.csv"])
    history = load_history(str(base / "data" / "city_hourly.csv"), hashes["data/city_hourly.csv"])
    missing = [c for c in CITIES if c not in set(replay.city)]
    if missing:
        st.error(f"Missing cities in the replay predictions: {', '.join(missing)}", icon=":material/error:")
        return

    with st.container(border=True):
        st.markdown("#### India EV demand forecast: next hour by city (historical replay)")
        c1, c2, c3 = st.columns([2, 2, 1])
        city = c1.selectbox("City", CITIES, key="india_city")
        first, last = replay.target_time.min().date(), replay.target_time.max().date()
        last_actual = replay.loc[replay.actual_utilization.notna(), "target_time"].max().date()
        st.session_state.setdefault("india_day", last_actual)
        st.session_state.setdefault("india_hour", 18)
        day = c2.date_input("Day (IST)", min_value=first, max_value=last, key="india_day")
        hour = c3.selectbox("Hour (IST)", list(range(24)), format_func=lambda h: f"{h:02d}:00", key="india_hour")
        target = pd.Timestamp(day) + pd.Timedelta(hours=hour)

        row = lookup(replay, city, target)
        if row is None:
            st.info(f"No prediction for {city} at {target:%d %b %Y %H:%M} IST. Predictions need 24 hours of inputs "
                    f"including the value from one week earlier, so they start at {replay.target_time.min():%d %b %Y %H:%M} "
                    f"IST and end at {replay.target_time.max():%d %b %Y %H:%M} IST.", icon=":material/info:")
            return

        installed = int(history.loc[history.city == city, "installed_chargers"].iloc[0])
        pred = float(row.predicted_utilization)
        level = demand_level(pred)
        st.markdown(f"**{city}** · {target:%a %d %b %Y, %H:%M}–{target + pd.Timedelta(hours=1):%H:%M} IST")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Predicted utilization", f"{pred * 100:.1f}%", help=f"≈ {pred * installed:.0f} of {installed:,} installed chargers")
        if pd.notna(row.actual_utilization):
            actual = float(row.actual_utilization)
            m2.metric("Actual utilization (simulated)", f"{actual * 100:.1f}%",
                      delta=f"{(pred - actual) * 100:+.1f} pp prediction error", delta_color="off")
        else:
            m2.metric("Actual utilization (simulated)", "n/a", help="This hour is after the end of the dataset.")
        m3.markdown("**Demand**  \n" + (demand_badge(level) if level else "n/a"))
        m4.markdown(f"**Period**  \n{PERIODS[row.period]}")
        if level is None:
            st.warning(f"The model output {pred:.4f} is outside 0–1. It is shown unclipped and has no demand band.")
        st.caption(f"Inputs: {row.input_end - pd.Timedelta(hours=SEQ_LEN - 1):%d %b %H:%M} – {row.input_end:%d %b %H:%M} IST "
                   f"(24 hourly steps) · installed chargers {installed:,} · bands as in the pricing policy: "
                   f"Low < 40% ≤ Moderate < 70% ≤ High < 90% ≤ Very high")

        frame = comparison_frame(replay, city, target)
        if frame is None:
            st.info(f"Not enough history for a {CHART_DAYS}-day comparison chart ending at {target:%d %b %Y %H:%M} IST. "
                    f"Choose a later hour.", icon=":material/info:")
        else:
            st.markdown(f"#### Actual vs predicted, previous {CHART_DAYS} days")
            st.line_chart(frame, x_label="India Standard Time (IST)", y_label="Utilization (%)")
            st.caption(f"{city} · {frame.index.min():%d %b %Y %H:%M} → {frame.index.max():%d %b %Y %H:%M} IST · "
                       f"historical replay on simulated data")

    with st.container(border=True):
        st.markdown(f"#### {city}: accuracy on the held-out test period (simulated data)")
        st.dataframe(city_test_metrics(base, city), width="stretch")
        st.caption("Test period 4–29 Mar 2026 IST · pp = percentage points of utilization. Same LSTM architecture as "
                   "the Caltech model, trained on four-city simulated data. These numbers measure how well the model "
                   "learns the data generator, not real-world demand.")
