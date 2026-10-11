"""Tests for the read-only evaluation endpoints (saved Phase 3 results; no inference)."""
import json

import numpy as np
import pandas as pd
import pytest

import config

pytestmark = pytest.mark.skipif(
    not (config.MODEL_FILE.exists() and config.EVAL_METRICS_FILE.exists() and config.TEST_PREDICTIONS_FILE.exists()),
    reason="needs trained model and saved evaluation")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import api
    from prediction_service import ForecastService
    with TestClient(api.create_app(ForecastService.from_files())) as c:
        yield c


def test_summary_matches_saved_metrics(client):
    saved = json.loads(config.EVAL_METRICS_FILE.read_text(encoding="utf-8"))
    j = client.get("/evaluation").json()
    assert j["horizonHours"] == 1 and j["seriesAvailable"] is True
    for key, camel in (("lstm", "lstm"), ("previous_hour", "previousHour"), ("same_hour_last_week", "sameHourLastWeek")):
        got, exp = j["overall"][camel], saved["overall"][key]
        assert got["n"] == exp["n"] == 1728
        for m_snake, m_camel in (("mae_pp", "maePp"), ("rmse_pp", "rmsePp"), ("wape_percent", "wapePercent")):
            assert got[m_camel] == exp[m_snake]
    assert "lstmVsPreviousHour" in j["comparisons"]
    assert j["testPeriodLocal"][0].startswith("2019-12-20")


def test_series_returns_saved_values_for_range(client):
    saved = pd.read_csv(config.TEST_PREDICTIONS_FILE, parse_dates=["target_timestamp_utc"])
    j = client.get("/evaluation/series", params={"start": "2020-01-06", "end": "2020-01-07"}).json()
    pts = j["points"]
    assert len(pts) == 48
    assert pts[0]["targetTime"] == "2020-01-06T00:00:00-08:00"
    first = saved[saved["target_timestamp_utc"] == pd.Timestamp("2020-01-06T08:00:00Z")].iloc[0]
    assert np.isclose(pts[0]["actual"], first["actual_utilization"], atol=1e-6)
    assert np.isclose(pts[0]["lstm"], first["pred_lstm"], atol=1e-6)
    assert np.isclose(pts[0]["previousHour"], first["pred_previous_hour"], atol=1e-6)


@pytest.mark.parametrize("params, status", [
    ({"start": "2020-01-10", "end": "2020-01-05"}, 422),          # end before start
    ({"start": "2020-01-01", "end": "2020-02-15"}, 422),          # more than 31 days
    ({"start": "2021-01-01", "end": "2021-01-02"}, 422),          # outside test period
    ({"start": "not-a-date", "end": "2020-01-02"}, 422),          # malformed
    ({"start": "2020-01-06"}, 422),                               # missing end
])
def test_series_validation(client, params, status):
    r = client.get("/evaluation/series", params=params)
    assert r.status_code == status


def test_evaluation_endpoints_do_not_run_the_model(client):
    """The endpoints must only read saved results: calling them must never invoke the model."""
    svc = client.app.state.service
    calls = []
    original = svc._forward
    svc._forward = lambda X: calls.append(1) or original(X)
    try:
        client.get("/evaluation")
        client.get("/evaluation/series", params={"start": "2020-01-06", "end": "2020-01-06"})
    finally:
        svc._forward = original
    assert calls == []
