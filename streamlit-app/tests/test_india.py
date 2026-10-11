"""
Experimental India model on the Model insights page. Uses the real, validated replay files in
experiments/india_ev_lstm (read-only) and the stub backend, which must receive no India-related calls.
"""
import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from evcharge import india

ROOT = Path(__file__).resolve().parents[1]
PAGE = str(ROOT / "views" / "nerd_stats.py")
BASE = india.india_dir()
REPLAY = pd.read_csv(BASE / "results" / "replay_predictions.csv", parse_dates=["input_end", "target_time"])
DEFAULT_TARGET = pd.Timestamp("2026-03-29 18:00")


def india_page(**state) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60)      # India is the default model: nothing to select
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def expected(city: str, target: pd.Timestamp) -> pd.Series:
    return REPLAY[(REPLAY.city == city) & (REPLAY.target_time == target)].iloc[0]


def metrics(at: AppTest) -> dict:
    return {m.label: m.value for m in at.metric}


# ---------------------------------------------------------------- data and validation
def test_replay_files_validate_against_manifest_and_metadata():
    assert india.validation_problems(BASE) == []


def test_changed_or_missing_files_are_refused(tmp_path):
    copy = tmp_path / "india"
    shutil.copytree(BASE, copy, ignore=shutil.ignore_patterns("tests", "__pycache__", "*.py", "train_log.txt"))
    with open(copy / "results" / "replay_predictions.csv", "a", encoding="utf-8") as f:
        f.write("Pune,2026-03-29 23:00:00,2026-03-30 00:00:00,0.5,,beyond_data\n")
    assert "results/replay_predictions.csv changed after the replay predictions were generated" in india.validation_problems(copy)
    (copy / "model" / "india_synthetic_lstm.keras").unlink()
    assert "model/india_synthetic_lstm.keras is missing" in india.validation_problems(copy)
    assert india.validation_problems(tmp_path / "nowhere") == ["results/replay_manifest.json is missing"]


def test_demand_levels_match_pricing_bands_and_are_never_clipped():
    assert india.demand_level(0.3999) == "LOW" and india.demand_level(0.40) == "MEDIUM"
    assert india.demand_level(0.70) == "HIGH" and india.demand_level(0.90) == "VERY_HIGH"
    assert india.demand_level(1.0001) is None and india.demand_level(-0.01) is None
    assert india.demand_level(float("nan")) is None


@pytest.mark.parametrize("city", india.CITIES)
def test_comparison_frame_uses_city_and_seven_day_window(city):
    frame = india.comparison_frame(REPLAY, city, DEFAULT_TARGET)
    assert frame.index.min() == DEFAULT_TARGET - pd.Timedelta(days=7) and frame.index.max() == DEFAULT_TARGET
    assert len(frame) == 7 * 24 + 1
    row = expected(city, DEFAULT_TARGET)
    assert frame.loc[DEFAULT_TARGET, "India LSTM prediction"] == pytest.approx(row.predicted_utilization * 100)
    assert frame.loc[DEFAULT_TARGET, "Actual (simulated)"] == pytest.approx(row.actual_utilization * 100)


def test_comparison_frame_needs_full_history():
    first = REPLAY.target_time.min()
    assert india.comparison_frame(REPLAY, "Pune", first + pd.Timedelta(days=3)) is None
    assert india.comparison_frame(REPLAY, "Pune", first + pd.Timedelta(days=7)) is not None


# ---------------------------------------------------------------- page
def test_india_is_the_default_model(stub):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert at.radio(key="nerd_model").value == "India"
    assert at.radio(key="nerd_model").options == ["India", "Caltech (comparison)"]
    assert any(i.value == india.NOTICE for i in at.info)
    assert "Predicted utilization" in metrics(at)


def test_caltech_remains_available_for_comparison(stub):
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["nerd_model"] = "Caltech (comparison)"
    at.run()
    assert not at.exception
    assert not any(india.NOTICE in i.value for i in at.info)
    assert stub.calls_to("GET", "/api/forecast/next-hour")      # Caltech forecast from the backend, as before


def test_ui_text_does_not_call_the_model_experimental(stub):
    at = india_page()
    shown = [e.value for kind in (at.info, at.warning, at.markdown, at.caption, at.title) for e in kind]
    shown += [m.label for m in at.metric] + [r.label for r in at.radio] + list(at.radio(key="nerd_model").options)
    assert not any("xperiment" in str(t) for t in shown)


def test_india_view_shows_notice_cities_and_no_backend_calls(stub):
    at = india_page()
    assert any(i.value == india.NOTICE for i in at.info)
    assert at.selectbox(key="india_city").options == india.CITIES
    assert at.selectbox(key="india_city").value == "Pune"
    assert at.date_input(key="india_day").value == date(2026, 3, 29)
    assert stub.calls == []      # no forecast, pricing, availability or booking request
    assert len(at.get("vega_lite_chart")) == 1


@pytest.mark.parametrize("city", india.CITIES)
def test_city_selection_changes_prediction_actual_and_chart(stub, city):
    at = india_page()
    at.selectbox(key="india_city").set_value(city).run()
    assert not at.exception
    row = expected(city, DEFAULT_TARGET)
    m = metrics(at)
    assert m["Predicted utilization"] == f"{row.predicted_utilization * 100:.1f}%"
    assert m["Actual utilization (simulated)"] == f"{row.actual_utilization * 100:.1f}%"
    texts = [md.value for md in at.markdown] + [c.value for c in at.caption]
    assert any(f"**{city}** · Sun 29 Mar 2026, 18:00–19:00 IST" in t for t in texts)
    assert any(t.startswith(f"{city} · 22 Mar 2026 18:00 → 29 Mar 2026 18:00 IST") for t in texts)
    assert len(at.get("vega_lite_chart")) == 1
    assert stub.calls == []


def test_selected_hour_maps_to_the_right_row(stub):
    at = india_page(india_city="Delhi NCR", india_day=date(2026, 3, 10), india_hour=9)
    row = expected("Delhi NCR", pd.Timestamp("2026-03-10 09:00"))
    assert metrics(at)["Predicted utilization"] == f"{row.predicted_utilization * 100:.1f}%"
    assert metrics(at)["Actual utilization (simulated)"] == f"{row.actual_utilization * 100:.1f}%"
    assert any("09 Mar 09:00 – 10 Mar 08:00 IST" in c.value for c in at.caption)


def test_hour_after_dataset_is_reported_not_invented(stub):
    at = india_page(india_day=date(2026, 3, 30), india_hour=5)
    assert any("No prediction for Pune at 30 Mar 2026 05:00 IST" in i.value for i in at.info)
    assert not at.metric and not at.get("vega_lite_chart")


def test_last_predictable_hour_has_no_actual(stub):
    at = india_page(india_day=date(2026, 3, 30), india_hour=0)
    assert metrics(at)["Actual utilization (simulated)"] == "n/a"
    assert any("After the last hour in the dataset" in md.value for md in at.markdown)


def test_early_hour_shows_prediction_but_no_seven_day_chart(stub):
    at = india_page(india_day=date(2025, 10, 10), india_hour=12)
    assert "Predicted utilization" in metrics(at)
    assert any("Not enough history for a 7-day comparison chart" in i.value for i in at.info)
    assert not at.get("vega_lite_chart")


def test_validation_failure_hides_results(stub, monkeypatch, tmp_path):
    monkeypatch.setenv("EVCHARGE_INDIA_DIR", str(tmp_path))
    at = india_page()
    assert any("India model results are unavailable" in e.value for e in at.error)
    assert not at.metric
