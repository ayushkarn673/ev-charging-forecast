"""
Integration checks on the files written by `uv run preprocess.py`. Skipped if they do not exist.
These re-derive facts from the saved outputs rather than trusting the pipeline's own summary.
"""
import json

import joblib
import numpy as np
import pandas as pd
import pytest

import config

pytestmark = pytest.mark.skipif(not config.HOURLY_SITE_FILE.exists(), reason="run preprocess.py first")


@pytest.fixture(scope="module")
def hourly():
    return pd.read_csv(config.HOURLY_SITE_FILE, index_col="timestamp_utc", parse_dates=["timestamp_utc"])


@pytest.fixture(scope="module")
def seqs():
    return {s: np.load(p) for s, p in config.SEQUENCE_FILES.items()}


@pytest.fixture(scope="module")
def summary():
    return json.loads(config.REPORT_JSON.read_text(encoding="utf-8"))


def test_hourly_grid_is_complete_and_unique(hourly):
    assert hourly.index.is_unique and hourly.index.is_monotonic_increasing
    assert (hourly.index.to_series().diff().dropna() == pd.Timedelta("1h")).all()


def test_utilization_bounded_and_consistent_with_capacity(hourly, summary):
    cap = summary["installed_capacity_spaces"]
    assert (hourly["capacity"] == cap).all()
    assert hourly["utilization"].between(0, 1).all()
    assert np.allclose(hourly["utilization"], hourly["occupied_spaces"] / cap, atol=1e-5)
    assert (hourly["peak_occupied_spaces"] <= cap).all()
    assert (hourly["occupied_spaces"] <= hourly["peak_occupied_spaces"] + 1e-9).all()


def test_split_order_and_no_overlap(hourly):
    order = hourly["split"].map({"train": 0, "val": 1, "test": 2}).to_numpy()
    assert (np.diff(order) >= 0).all()


def test_sequence_shapes_and_no_nan(seqs, summary):
    n_feat = len(config.FEATURES)
    for s, d in seqs.items():
        assert d["X"].shape[1:] == (config.SEQUENCE_LENGTH, n_feat)
        assert d["X"].shape[0] == d["y"].shape[0] == len(d["target_timestamp_utc"])
        assert list(d["X"].shape) == summary["splits"][s]["X_shape"]
        assert not np.isnan(d["X"]).any() and not np.isnan(d["y"]).any()


def test_sequence_targets_lie_in_their_own_split(hourly, seqs):
    for s, d in seqs.items():
        t = pd.to_datetime(d["target_timestamp_utc"], utc=True)
        assert (hourly.loc[t, "split"] == s).all()
        # the first input hour of each window (target - 24 h) is in the same split too
        first_input = t - pd.Timedelta(hours=config.SEQUENCE_LENGTH)
        assert (hourly.loc[first_input, "split"] == s).all()


def test_unscaled_targets_match_hourly_utilization(hourly, seqs):
    for d in seqs.values():
        t = pd.to_datetime(d["target_timestamp_utc"], utc=True)
        assert np.allclose(d["y_unscaled"].ravel(), hourly.loc[t, "utilization"].to_numpy(), atol=1e-6)


def test_saved_scalers_were_fit_on_valid_training_rows_only(hourly):
    fs = joblib.load(config.FEATURE_SCALER_FILE)
    ts = joblib.load(config.TARGET_SCALER_FILE)
    train = hourly[(hourly["split"] == "train") & hourly["input_valid"]]
    assert np.allclose(fs.data_min_, train[config.SCALED_FEATURES].min(), atol=1e-6)
    assert np.allclose(fs.data_max_, train[config.SCALED_FEATURES].max(), atol=1e-6)
    assert np.isclose(ts.data_max_[0], train["utilization"].max(), atol=1e-6)


def test_lag_168_in_outputs_matches_one_week_earlier(hourly):
    lag = hourly["utilization_lag_168"]
    assert lag.iloc[:168].isna().all()
    assert np.allclose(lag.iloc[168:].to_numpy(), hourly["utilization"].iloc[:-168].to_numpy(), atol=1e-9)


def test_feature_config_matches_config(summary):
    fc = json.loads(config.FEATURE_CONFIG_FILE.read_text(encoding="utf-8"))
    assert fc["features"] == config.FEATURES
    assert fc["sequence_length"] == config.SEQUENCE_LENGTH and fc["target"] == "utilization"
    assert fc["installed_capacity_spaces"] == summary["installed_capacity_spaces"]
