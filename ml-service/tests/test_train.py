"""Tests for train.py. Unit tests use a tiny model and synthetic arrays so they run in seconds."""
import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

import config
import train as tr

SEQ, FEAT = config.SEQUENCE_LENGTH, len(config.FEATURES)
TINY = replace(tr.TrainConfig(), lstm_units=(4, 2), dense_units=2, batch_size=16, max_epochs=3,
               early_stopping_patience=2)


def rand(n, seq=SEQ, feat=FEAT, seed=0):
    return np.random.default_rng(seed).random((n, seq, feat), dtype=np.float32)


# ---------------------------------------------------------------- configuration
def test_default_config_matches_specification():
    c = tr.TrainConfig().validate()
    assert c.lstm_units == (64, 32) and c.dropout == 0.2 and c.dense_units == 16
    assert c.batch_size == 256 and c.max_epochs == 100


@pytest.mark.parametrize("override", [
    {"lstm_units": (64,)}, {"lstm_units": (0, 32)}, {"lstm_units": (64, 2.5)},
    {"dropout": -0.1}, {"dropout": 1.0}, {"dense_units": 0}, {"learning_rate": 0.0},
    {"learning_rate": 1.5}, {"batch_size": 0}, {"max_epochs": 0}, {"early_stopping_patience": 0},
    {"seed": -1},
])
def test_invalid_config_rejected(override):
    with pytest.raises(ValueError):
        replace(tr.TrainConfig(), **override).validate()


def test_cli_overrides_are_applied_and_validated():
    c = tr.parse_args(["--epochs", "5", "--batch-size", "64", "--seed", "7", "--units", "32", "16"])
    assert (c.max_epochs, c.batch_size, c.seed, c.lstm_units) == (5, 64, 7, (32, 16))
    with pytest.raises(ValueError):
        tr.parse_args(["--dropout", "1.2"])


# ---------------------------------------------------------------- architecture and shapes
def test_default_architecture_matches_specification():
    m = tr.build_model(SEQ, FEAT, tr.TrainConfig())
    kinds = [(l.__class__.__name__, getattr(l, "units", getattr(l, "rate", None))) for l in m.layers]
    assert kinds == [("LSTM", 64), ("Dropout", 0.2), ("LSTM", 32), ("Dropout", 0.2), ("Dense", 16), ("Dense", 1)]
    assert m.layers[0].return_sequences is True and m.layers[2].return_sequences is False
    assert m.layers[4].activation.__name__ == "relu"


def test_model_input_and_output_shape():
    m = tr.build_model(SEQ, FEAT, TINY)
    assert m.input_shape == (None, SEQ, FEAT)
    assert m.output_shape == (None, 1)


def test_prediction_output_dimensions():
    m = tr.build_model(SEQ, FEAT, TINY)
    p = tr.predict_scaled(m, rand(7))
    assert p.shape == (7, 1) and np.isfinite(p).all()


@pytest.mark.parametrize("X, match", [
    (np.zeros((5, SEQ * FEAT), np.float32), "3-D"),
    (np.zeros((5, SEQ - 1, FEAT), np.float32), "sequence length"),
    (np.zeros((5, SEQ, FEAT + 1), np.float32), "features"),
    (np.zeros((0, SEQ, FEAT), np.float32), "no samples"),
    (np.full((2, SEQ, FEAT), np.nan, np.float32), "NaN"),
])
def test_invalid_input_dimensions_rejected(X, match):
    m = tr.build_model(SEQ, FEAT, TINY)
    with pytest.raises(ValueError, match=match):
        tr.predict_scaled(m, X)


# ---------------------------------------------------------------- save / reload / training loop
def test_model_save_and_reload_gives_identical_predictions(tmp_path):
    from tensorflow import keras
    m = tr.build_model(SEQ, FEAT, TINY)
    X = rand(5)
    path = tmp_path / "m.keras"
    m.save(path)
    reloaded = keras.models.load_model(path)
    assert reloaded.input_shape == m.input_shape
    np.testing.assert_allclose(tr.predict_scaled(m, X), tr.predict_scaled(reloaded, X), rtol=1e-6)


def test_training_loop_returns_best_checkpoint(tmp_path):
    X, y = rand(64, seed=1), np.random.default_rng(2).random((64, 1), dtype=np.float32)
    Xv, yv = rand(32, seed=3), np.random.default_rng(4).random((32, 1), dtype=np.float32)
    model, history, duration = tr.train(TINY, X, y, Xv, yv, tmp_path / "best.keras")
    assert (tmp_path / "best.keras").exists() and duration > 0
    assert 1 <= len(history) <= TINY.max_epochs
    assert {"epoch", "loss", "val_loss", "mae", "val_mae"} <= set(history.columns)
    val_loss, _ = model.evaluate(Xv, yv, verbose=0)
    assert np.isclose(val_loss, history["val_loss"].min(), rtol=1e-4)   # best weights, not last


def test_same_seed_gives_same_result(tmp_path):
    X, y = rand(48, seed=1), np.random.default_rng(2).random((48, 1), dtype=np.float32)
    cfg = replace(TINY, max_epochs=2)
    _, h1, _ = tr.train(cfg, X, y, X, y, tmp_path / "a.keras")
    _, h2, _ = tr.train(cfg, X, y, X, y, tmp_path / "b.keras")
    np.testing.assert_allclose(h1["val_loss"], h2["val_loss"], rtol=1e-6)


def test_preprocessing_mismatch_is_detected():
    good_X, good_y = rand(4), np.zeros((4, 1), np.float32)
    with pytest.raises(ValueError, match="shape"):
        tr.check_preprocessing_outputs(rand(4, feat=FEAT - 1), good_y, good_X, good_y)
    with pytest.raises(ValueError, match="y shape"):
        tr.check_preprocessing_outputs(good_X, np.zeros((4,), np.float32), good_X, good_y)


# ---------------------------------------------------------------- saved artifacts (after `uv run train.py`)
artifacts = pytest.mark.skipif(not config.MODEL_FILE.exists(), reason="run train.py first")


@artifacts
def test_saved_model_matches_feature_metadata():
    from tensorflow import keras
    fc = json.loads(config.FEATURE_CONFIG_FILE.read_text(encoding="utf-8"))
    m = keras.models.load_model(config.MODEL_FILE)
    assert m.input_shape == (None, fc["sequence_length"], len(fc["features"]))
    assert m.output_shape == (None, 1)
    X, _ = tr.load_split("val")
    assert tr.predict_scaled(m, X[:10]).shape == (10, 1)


@artifacts
def test_saved_summary_consistent_with_history():
    s = json.loads(config.TRAINING_SUMMARY_FILE.read_text(encoding="utf-8"))
    h = pd.read_csv(config.TRAINING_HISTORY_FILE)
    assert s["epochs_completed"] == len(h)
    assert s["best_epoch"] == int(h.loc[h["val_loss"].idxmin(), "epoch"])
    assert np.isclose(s["best_val_loss_mse_scaled"], h["val_loss"].min())
    assert np.isclose(s["reloaded_model_val_loss"], s["best_val_loss_mse_scaled"], rtol=1e-3)
    mc = json.loads(config.MODEL_CONFIG_FILE.read_text(encoding="utf-8"))
    assert mc["feature_metadata"]["features"] == config.FEATURES and mc["shuffle"] is False
