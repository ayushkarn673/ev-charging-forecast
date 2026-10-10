"""Tests for the prediction service and API (historical replay, one hour ahead)."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

import config

pytestmark = pytest.mark.skipif(not (config.MODEL_FILE.exists() and config.HOURLY_SITE_FILE.exists()),
                                reason="needs trained model and processed data")

F_TEST = "2020-01-15T09:00:00-08:00"          # Wednesday 09:00, test period


@pytest.fixture(scope="module")
def service():
    from prediction_service import ForecastService
    return ForecastService.from_files()


@pytest.fixture(scope="module")
def client(service):
    from fastapi.testclient import TestClient
    import api
    with TestClient(api.create_app(service)) as c:
        yield c


def ts(s):
    return pd.Timestamp(s).tz_convert("UTC")


# ---------------------------------------------------------------- loading
def test_model_scalers_and_metadata_loaded(service):
    assert tuple(service.model.input_shape) == (None, 24, len(config.FEATURES))
    assert tuple(service.model.output_shape) == (None, 1)
    assert service.feature_scaler.n_features_in_ == len(config.SCALED_FEATURES)
    assert service.target_scaler.n_features_in_ == 1
    assert service.feature_config["features"] == config.FEATURES
    assert service.capacity == 54 and len(service.model_sha256) == 64


def test_observation_store_excludes_derived_features(service):
    assert "utilization_lag_168" not in service.observations.columns
    assert "utilization_roll_mean_24" not in service.observations.columns


def test_consistency_check_rejects_wrong_feature_order(service):
    bad = dict(service.feature_config, features=list(reversed(config.FEATURES)))
    with pytest.raises(ValueError, match="order"):
        replace(service, feature_config=bad).check_consistency()


# ---------------------------------------------------------------- request validation
@pytest.mark.parametrize("body, status", [
    ({"forecastTime": "2020-01-15T09:00:00"}, 422),               # no timezone
    ({"forecastTime": "2020-01-15T09:30:00-08:00"}, 422),         # not on the hour
    ({"forecastTime": "2020-01-15T09:00:05-08:00"}, 422),
    ({"forecastTime": "not-a-date"}, 422),
    ({}, 422),                                                    # missing
    ({"forecastTime": F_TEST, "unexpected": 1}, 422),             # extra field
    ({"siteId": "jpl", "forecastTime": F_TEST}, 404),             # unknown site
])
def test_request_validation(client, body, status):
    assert client.post("/predict/next-hour", json=body).status_code == status


def test_out_of_range_and_insufficient_history(client):
    late = client.post("/predict/next-hour", json={"forecastTime": "2021-01-01T09:00:00-08:00"})
    assert late.status_code == 422 and late.json()["code"] == "OUT_OF_RANGE"
    early = client.post("/predict/next-hour", json={"forecastTime": "2018-11-02T09:00:00-07:00"})
    assert early.status_code == 422 and early.json()["code"] == "INSUFFICIENT_HISTORY"


def test_first_and_last_supported_times(service):
    sup = service.supported_forecast_times()
    first_obs = service.observations.index[0]
    assert sup[0] == first_obs + pd.Timedelta(hours=192)
    assert sup[-1] == service.observations.index[-1] + pd.Timedelta(hours=1)
    service.predict_next_hour(sup[0])                         # exactly enough history
    from prediction_service import UnsupportedForecastTime
    with pytest.raises(UnsupportedForecastTime):
        service.predict_next_hour(sup[0] - pd.Timedelta(hours=1))


def test_invalid_or_missing_history_is_rejected(service):
    from prediction_service import UnsupportedForecastTime
    F = ts(F_TEST)
    bad = service.observations.copy()
    bad.loc[F - pd.Timedelta(hours=100), "confirmed_invalid"] = 1
    svc = replace(service, observations=bad)
    with pytest.raises(UnsupportedForecastTime) as e:
        svc.predict_next_hour(F)
    assert e.value.code == "INSUFFICIENT_HISTORY"
    svc.predict_next_hour(F + pd.Timedelta(hours=100))       # once the bad hour is > 192 h old, fine
    gappy = replace(service, observations=service.observations.drop(F - pd.Timedelta(hours=5)))
    with pytest.raises(UnsupportedForecastTime):
        gappy.predict_next_hour(F)


# ---------------------------------------------------------------- feature order / equivalence with training
def test_replay_inputs_identical_to_preprocessed_test_sequences(service):
    d = np.load(config.SEQUENCE_FILES["test"])
    for i in (0, 500, 1727):
        F = pd.Timestamp(str(d["target_timestamp_utc"][i]))
        X, window = service.build_input(F)
        assert list(window[config.FEATURES].columns) == config.FEATURES
        np.testing.assert_allclose(X[0], d["X"][i], atol=1e-6)


def test_replay_predictions_match_phase3_saved_predictions(service):
    saved = pd.read_csv(config.TEST_PREDICTIONS_FILE, index_col="target_timestamp_utc",
                        parse_dates=["target_timestamp_utc"])
    for F in saved.index[::173]:
        out = service.predict_next_hour(F)
        assert np.isclose(out["prediction"]["raw_utilization"], saved.at[F, "pred_lstm"], atol=1e-5)


# ---------------------------------------------------------------- information boundary / no leakage
def test_inputs_use_only_hours_that_ended_before_forecast_time(service):
    F = ts(F_TEST)
    hist = service.history_before(F)
    assert hist.index.max() == F - pd.Timedelta(hours=1)
    assert hist.index.min() == F - pd.Timedelta(hours=192)
    assert F not in hist.index
    out = service.predict_next_hour(F)
    assert pd.Timestamp(out["inputs"]["latest_observation_used"]) == F - pd.Timedelta(hours=1)


def test_no_future_data_leakage(service):
    F = ts(F_TEST)
    tampered = service.observations.copy()
    future = tampered.index >= F
    tampered.loc[future, "utilization"] = 0.99
    tampered.loc[future, "arrivals"] = 999
    tampered.loc[future, "energy_kwh_completed"] = np.nan
    svc = replace(service, observations=tampered)
    X_a, _ = service.build_input(F)
    X_b, _ = svc.build_input(F)
    np.testing.assert_array_equal(X_a, X_b)
    assert service.predict_next_hour(F)["prediction"] == svc.predict_next_hour(F)["prediction"]


def test_changing_the_past_does_change_the_prediction(service):
    """Sanity check that the leakage test is meaningful: inputs really are read."""
    F = ts(F_TEST)
    altered = service.observations.copy()
    altered.loc[F - pd.Timedelta(hours=1), "utilization"] = 0.9
    assert replace(service, observations=altered).build_input(F)[0][0, -1, 0] != service.build_input(F)[0][0, -1, 0]


# ---------------------------------------------------------------- output policy
@pytest.mark.parametrize("raw, util, occ_round, avail, clipped", [
    (-0.008, 0.0, 0, 54, True),
    (1.2, 1.0, 54, 0, True),
    (0.2336, 0.2336, 13, 41, False),        # 12.61 spaces -> ceil 13
    (0.5, 0.5, 27, 27, False),              # exactly 27 spaces stays 27 (no float overshoot)
    (0.0, 0.0, 0, 54, False),
])
def test_output_bounds_and_rounding(service, raw, util, occ_round, avail, clipped):
    o = service.apply_output_policy(raw)
    assert o["raw_utilization"] == raw and np.isclose(o["utilization"], util)
    assert o["estimated_occupied_spaces_rounded"] == occ_round
    assert o["estimated_available_spaces_rounded"] == avail
    assert o["estimated_occupied_spaces_rounded"] + o["estimated_available_spaces_rounded"] == 54
    assert isinstance(o["estimated_occupied_spaces_rounded"], int) and o["clipped"] is clipped


def test_clipping_is_reported_as_warning(service):
    class Negative:
        input_shape, output_shape = service.model.input_shape, service.model.output_shape
        def __call__(self, X, training=False):
            return np.full((len(X), 1), -0.05, np.float32)
    out = replace(service, model=Negative()).predict_next_hour(ts(F_TEST))
    assert out["prediction"]["utilization"] == 0.0 and out["prediction"]["raw_utilization"] < 0
    assert "PREDICTION_CLIPPED" in [w["code"] for w in out["warnings"]]


# ---------------------------------------------------------------- response schema and warnings
def test_prediction_response_schema(client):
    r = client.post("/predict/next-hour", json={"forecastTime": F_TEST})
    assert r.status_code == 200
    j = r.json()
    for key in ("mode", "isSimulation", "forecastTime", "targetStart", "targetEnd", "horizonHours", "prediction",
                "modelId", "warnings", "inputs", "roundingPolicy", "observedOutcome"):
        assert key in j
    assert j["mode"] == "historical_replay" and j["isSimulation"] is True and j["horizonHours"] == 1
    assert j["targetStart"] == j["forecastTime"] == "2020-01-15T09:00:00-08:00"
    assert j["targetEnd"] == "2020-01-15T10:00:00-08:00"
    p = j["prediction"]
    assert 0 <= p["utilization"] <= 1 and p["utilizationPercent"] == round(p["utilization"] * 100, 1)
    assert p["estimatedOccupiedSpacesRounded"] + p["estimatedAvailableSpacesRounded"] == 54
    assert j["observedOutcome"] is not None and "never used as model input" in j["observedOutcome"]["note"]


def test_period_and_quality_warnings(service):
    codes = lambda F: {w["code"] for w in service.predict_next_hour(ts(F))["warnings"]}
    assert "IN_SAMPLE_TRAINING_PERIOD" in codes("2019-03-13T09:00:00-07:00")
    assert "MODEL_SELECTION_PERIOD" in codes("2019-11-13T09:00:00-08:00")
    assert "HOLIDAY_TARGET" in codes("2020-01-01T10:00:00-08:00")
    assert "WEEKEND_TARGET" in codes("2020-01-18T10:00:00-08:00")
    assert "BASELINE_BETTER_AT_THIS_HOUR" in codes("2020-01-15T03:00:00-08:00")
    last = service.supported_forecast_times()[-1]
    out = service.predict_next_hour(last)
    assert out["observed_outcome"] is None
    assert "OUTCOME_NOT_IN_DATASET" in {w["code"] for w in out["warnings"]}


# ---------------------------------------------------------------- metadata endpoints
def test_health(client):
    j = client.get("/health").json()
    assert j["status"] == "ok" and j["modelLoaded"] is True and j["observationsLoaded"] > 0
    assert j["modelId"].startswith("ev_demand_lstm@sha256:")


def test_model_info(client):
    j = client.get("/model-info").json()
    assert j["horizonHours"] == 1 and j["validatedHorizonsHours"] == [1]
    assert j["features"] == config.FEATURES and j["inputShape"] == [None, 24, 11]
    assert j["installedCapacitySpaces"] == 54 and j["mode"] == "historical_replay"
    assert set(j["testEvaluation"]) == {"previous_hour", "same_hour_last_week", "lstm"} or \
           set(j["testEvaluation"]) == {"previousHour", "sameHourLastWeek", "lstm"}
    assert any("one-hour-ahead" in s for s in j["limitations"])


def test_available_dates(client, service):
    j = client.get("/available-dates").json()
    sup = service.supported_forecast_times()
    assert j["supportedForecastHours"] == len(sup)
    assert pd.Timestamp(j["firstForecastTime"]) == sup[0] and pd.Timestamp(j["lastForecastTime"]) == sup[-1]
    assert j["recommendedOutOfSamplePeriod"] == "test" and "test" in j["periodsByTargetSplit"]


def test_service_unavailable_returns_503():
    from fastapi.testclient import TestClient
    import api
    class Placeholder:                          # so startup does not load the real files
        observations = []
        def model_info(self):
            return {"model_id": "placeholder"}
    app = api.create_app(service=Placeholder())
    with TestClient(app) as c:
        app.state.service = None
        assert c.get("/model-info").status_code == 503
        assert c.get("/health").json()["status"] == "unavailable"
