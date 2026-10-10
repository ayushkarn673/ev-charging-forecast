"""Tests for evaluate.py: metrics, inverse scaling, baseline/target alignment and saved outputs."""
import json

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import MinMaxScaler

import config
import evaluate as ev


# ---------------------------------------------------------------- metric calculations
def test_metrics_match_hand_calculation():
    actual, pred = np.array([0.0, 0.1, 0.2]), np.array([0.1, 0.1, 0.4])
    r = ev.metric_row(actual, pred, capacity=54)
    assert np.isclose(r["mae_utilization"], 0.1)                      # (0.1 + 0 + 0.2) / 3
    assert np.isclose(r["rmse_utilization"], np.sqrt(0.05 / 3))       # (0.01 + 0 + 0.04) / 3
    assert np.isclose(r["mae_pp"], 10.0) and np.isclose(r["mae_spaces"], 5.4)
    assert np.isclose(r["bias_pp"], 10.0)
    assert np.isclose(r["wape_percent"], 100.0)                       # 0.3 / 0.3
    assert r["n"] == 3


def test_rmse_never_below_mae():
    rng = np.random.default_rng(0)
    a, p = rng.random(500), rng.random(500)
    assert ev.rmse(a, p) >= ev.mae(a, p)


def test_metrics_reject_mismatched_or_non_finite_inputs():
    with pytest.raises(ValueError, match="shape"):
        ev.metric_row(np.zeros(3), np.zeros(4), 54)
    with pytest.raises(ValueError, match="NaN"):
        ev.metric_row(np.array([0.1, np.nan]), np.array([0.1, 0.2]), 54)


# ---------------------------------------------------------------- zero-utilization handling
def test_zero_actual_hours_are_handled():
    actual = np.array([0.0, 0.0, 0.5])
    pred = np.array([0.1, 0.0, 0.4])
    r = ev.metric_row(actual, pred, 54)                # no division by an individual zero hour
    assert np.isclose(r["wape_percent"], 0.2 / 0.5 * 100)
    assert np.isclose(r["mae_utilization"], 0.2 / 3)


def test_wape_undefined_when_all_actuals_zero():
    with pytest.raises(ValueError, match="undefined"):
        ev.wape(np.zeros(4), np.ones(4))


# ---------------------------------------------------------------- bootstrap
def test_bootstrap_constant_difference_has_zero_width_interval():
    out = ev.block_bootstrap_mean(np.full(96, -0.5), block=24, reps=200, seed=1)
    assert out["mean"] == -0.5 and np.allclose(out["ci95"], [-0.5, -0.5])
    assert out["share_of_replicates_below_zero"] == 1.0


def test_bootstrap_is_reproducible_with_seed():
    d = np.random.default_rng(3).normal(size=200)
    a = ev.block_bootstrap_mean(d, 24, 300, seed=7)
    b = ev.block_bootstrap_mean(d, 24, 300, seed=7)
    assert a == b


# ---------------------------------------------------------------- inverse scaling
class StubModel:
    """Behaves like a Keras model for predict_scaled: fixed scaled output."""
    input_shape = (None, 24, 3)

    def __init__(self, out):
        self.out = np.asarray(out, np.float32).reshape(-1, 1)

    def predict(self, X, verbose=0):
        return self.out[: len(X)]


def test_lstm_predictions_use_the_target_scaler():
    target_scaler = MinMaxScaler().fit(np.array([[0.0], [0.8]]))      # scaled 1.0 -> 0.8 utilization
    model = StubModel([0.0, 0.5, 1.0])
    pred = ev.lstm_predictions(model, np.zeros((3, 24, 3), np.float32), target_scaler)
    assert np.allclose(pred, [0.0, 0.4, 0.8])


def test_saved_target_scaler_inverts_saved_test_targets():
    if not config.SEQUENCE_FILES["test"].exists():
        pytest.skip("run preprocess.py first")
    d = np.load(config.SEQUENCE_FILES["test"])
    ts = joblib.load(config.TARGET_SCALER_FILE)
    fs = joblib.load(config.FEATURE_SCALER_FILE)
    assert np.allclose(ts.inverse_transform(d["y"]), d["y_unscaled"], atol=1e-6)
    assert ts.n_features_in_ == 1 and fs.n_features_in_ == len(config.SCALED_FEATURES)


# ---------------------------------------------------------------- baseline timestamps
def _hourly(n=400):
    idx = pd.date_range("2019-01-07", periods=n, freq="h", tz="UTC", name="timestamp_utc")
    return pd.DataFrame({"utilization": np.arange(n) / 1000.0, "confirmed_invalid": 0}, index=idx)


def test_baselines_read_exact_historical_timestamps():
    h = _hourly()
    targets = h.index[[200, 250, 399]]
    assert np.allclose(ev.baseline_predictions(h, targets, 1), np.array([199, 249, 398]) / 1000)
    assert np.allclose(ev.baseline_predictions(h, targets, 168), np.array([32, 82, 231]) / 1000)


def test_baseline_never_uses_the_target_hour_itself():
    h = _hourly()
    targets = h.index[200:260]
    for lag in (1, 168):
        assert not np.allclose(ev.baseline_predictions(h, targets, lag), h.loc[targets, "utilization"])


def test_baseline_rejects_missing_or_invalid_history():
    h = _hourly()
    with pytest.raises(ValueError, match="missing"):
        ev.baseline_predictions(h, h.index[[100]], 168)                # t-168 before the series
    gappy = h.drop(h.index[199])
    with pytest.raises(ValueError, match="missing"):
        ev.baseline_predictions(gappy, gappy.index[[199]], 1)          # source hour removed
    bad = h.copy()
    bad.iloc[199, bad.columns.get_loc("confirmed_invalid")] = 1
    with pytest.raises(ValueError, match="invalid"):
        ev.baseline_predictions(bad, bad.index[[200]], 1)


# ---------------------------------------------------------------- saved evaluation outputs
saved = pytest.mark.skipif(not config.TEST_PREDICTIONS_FILE.exists(), reason="run evaluate.py first")


@pytest.fixture(scope="module")
def outputs():
    pred = pd.read_csv(config.TEST_PREDICTIONS_FILE, index_col="target_timestamp_utc",
                       parse_dates=["target_timestamp_utc"])
    metrics = json.loads(config.EVAL_METRICS_FILE.read_text(encoding="utf-8"))
    test = np.load(config.SEQUENCE_FILES["test"])
    hourly = ev.load_hourly()
    return pred, metrics, test, hourly


@saved
def test_predictions_aligned_with_test_targets(outputs):
    pred, _, test, hourly = outputs
    assert len(pred) == len(test["y"])
    assert list(pred.index.strftime("%Y-%m-%dT%H:%M:%SZ")) == list(test["target_timestamp_utc"])
    assert np.allclose(pred["actual_utilization"], test["y_unscaled"].ravel(), atol=1e-6)
    assert (hourly.loc[pred.index, "split"] == "test").all()


@saved
def test_previous_hour_baseline_equals_last_input_step(outputs):
    """Independent check: the last input step's (inverse-scaled) utilization is hour t-1."""
    pred, _, test, _ = outputs
    fs = joblib.load(config.FEATURE_SCALER_FILE)
    j = config.SCALED_FEATURES.index("utilization")
    last_step = test["X"][:, -1, j] * (fs.data_max_[j] - fs.data_min_[j]) + fs.data_min_[j]
    assert np.allclose(pred["pred_previous_hour"], last_step, atol=1e-5)


@saved
def test_same_hour_last_week_baseline_is_168_hours_back(outputs):
    pred, _, _, hourly = outputs
    src = pred.index - pd.Timedelta(hours=168)
    assert np.allclose(pred["pred_same_hour_last_week"], hourly.loc[src, "utilization"], atol=1e-6)


@saved
def test_saved_metrics_recompute_from_saved_predictions(outputs):
    pred, metrics, _, _ = outputs
    a = pred["actual_utilization"].to_numpy()
    for k in ev.APPROACHES:
        p = pred[f"pred_{k}"].to_numpy()
        m = metrics["overall"][k]
        assert m["n"] == len(pred)
        assert np.isclose(m["mae_utilization"], np.mean(np.abs(p - a)), atol=1e-6)
        assert np.isclose(m["rmse_utilization"], np.sqrt(np.mean((p - a) ** 2)), atol=1e-6)
        assert np.isclose(m["mae_spaces"], m["mae_utilization"] * 54)
        assert np.allclose(pred[f"error_{k}"], p - a, atol=1e-6)


@saved
def test_saved_lstm_predictions_reproduce_from_model(outputs):
    from tensorflow import keras
    pred, _, test, _ = outputs
    model = keras.models.load_model(config.MODEL_FILE)
    again = ev.lstm_predictions(model, test["X"][:50], joblib.load(config.TARGET_SCALER_FILE))
    assert np.allclose(again, pred["pred_lstm"].to_numpy()[:50], atol=1e-5)
