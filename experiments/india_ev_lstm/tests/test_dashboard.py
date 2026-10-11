"""
Tests for the experimental India dashboard. Run with the streamlit-app interpreter (no TensorFlow):
    streamlit-app/.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider experiments/india_ev_lstm/tests -q
Requires results/replay_predictions.csv from replay_predict.py.
"""
import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import dashboard_core as core  # noqa: E402

DASHBOARD = str(HERE / "dashboard.py")


@pytest.fixture(scope="module")
def hist():
    return core.load_history()


@pytest.fixture(scope="module")
def rep():
    return core.load_replay()


def test_artifacts_match_manifest():
    assert core.integrity_problems() == []


def test_all_four_cities_present(hist, rep):
    for city in core.CITIES:
        assert city in set(hist.city) and city in set(rep.city)


def test_predictions_finite_and_in_range(rep):
    assert rep.predicted_utilization.map(math.isfinite).all()
    assert rep.predicted_utilization.between(0, 1).all()


def test_every_prediction_uses_the_24_hours_before_it(rep):
    assert (rep.target_time - rep.input_end == pd.Timedelta(hours=1)).all()
    assert (rep.groupby("city").input_end.min() == pd.Timestamp("2025-10-08 23:00")).all()   # 168 + 24 hours of history


def test_demand_category_bands():
    assert core.demand_category(0.0) == ("Low", "green")
    assert core.demand_category(0.3999) == ("Low", "green")
    assert core.demand_category(0.40) == ("Moderate", "blue")
    assert core.demand_category(0.70) == ("High", "orange")
    assert core.demand_category(0.90) == ("Very high", "red")
    assert core.demand_category(1.2) is None
    assert core.demand_category(float("nan")) is None


@pytest.mark.parametrize("city", core.CITIES)
def test_chart_frame_uses_selected_city_and_window(hist, rep, city):
    target = pd.Timestamp("2026-03-20 18:00")
    frame = core.chart_frame(hist, rep, city, target)
    assert frame.index.min() == target - pd.Timedelta(days=7) and frame.index.max() == target
    expected = hist[(hist.city == city) & (hist.timestamp == target)].utilization.iloc[0] * 100
    assert frame.loc[target, "Actual utilization (%)"] == pytest.approx(expected)
    pred = rep[(rep.city == city) & (rep.target_time == target)].predicted_utilization.iloc[0] * 100
    assert frame.loc[target, "LSTM next-hour replay (%)"] == pytest.approx(pred)


def test_page_default_render():
    at = AppTest.from_file(DASHBOARD, default_timeout=60).run()
    assert not at.exception
    assert any(core.BANNER in w.value for w in at.warning)
    assert at.selectbox(key="city").value == "Pune"
    assert at.date_input(key="day").value == date(2026, 3, 29)
    assert len(at.get("vega_lite_chart")) == 1


@pytest.mark.parametrize("city", core.CITIES)
def test_page_shows_prediction_for_each_city(rep, city):
    at = AppTest.from_file(DASHBOARD, default_timeout=60).run()
    at.selectbox(key="city").set_value(city).run()
    assert not at.exception
    row = rep[(rep.city == city) & (rep.target_time == pd.Timestamp("2026-03-29 18:00"))].iloc[0]
    assert at.metric[0].value == f"{row.predicted_utilization * 100:.1f}%"
    assert any(city in s.value for s in at.subheader)
    assert any(city in c.value and "22 Mar 2026 18:00" in c.value for c in at.caption)


def test_page_reports_hour_without_valid_window():
    at = AppTest.from_file(DASHBOARD, default_timeout=60).run()
    at.date_input(key="day").set_value(date(2026, 3, 30)).run()      # only 00:00 is predictable that day
    at.selectbox(key="hour").set_value(5).run()
    assert not at.exception
    assert any("No valid prediction" in i.value for i in at.info)
