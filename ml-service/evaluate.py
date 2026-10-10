"""
Phase 3 - evaluate the frozen LSTM on the untouched test split and compare it with two
baselines on exactly the same target timestamps.

  A. previous hour        : y_hat(t) = utilization(t - 1 h)
  B. same hour last week  : y_hat(t) = utilization(t - 168 h)
  C. LSTM                 : saved checkpoint, 24-hour input sequences

Nothing is trained, refitted or tuned here. Predictions are converted back to utilization with
the TARGET scaler (not the feature scaler).

Metrics (lower is better):
  MAE, RMSE in utilization (reported in percentage points, pp) and in occupied spaces (x 54);
  WAPE = sum|error| / sum|actual| (a percentage error; defined even when some hours are zero).
  MAPE is not used: it is undefined for hours with zero utilization (count reported in the output).

Outputs: models/evaluation/test_predictions.csv, test_metrics.json, test_metrics_table.csv,
         docs/evaluation_report.md, docs/figures/eval_*.png
Run    : uv run evaluate.py
"""
from __future__ import annotations

import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import json  # noqa: E402
import logging  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402

log = logging.getLogger("evaluate")

APPROACHES = {   # key -> display name
    "previous_hour": "Previous hour",
    "same_hour_last_week": "Same hour last week",
    "lstm": "LSTM",
}
BASELINE_LAGS = {"previous_hour": 1, "same_hour_last_week": 168}


# ===================================================================================
# Metrics
# ===================================================================================
def mae(actual, pred) -> float:
    return float(np.mean(np.abs(np.asarray(pred, float) - np.asarray(actual, float))))


def rmse(actual, pred) -> float:
    return float(np.sqrt(np.mean((np.asarray(pred, float) - np.asarray(actual, float)) ** 2)))


def bias(actual, pred) -> float:
    """Mean error (prediction - actual); positive = over-forecast."""
    return float(np.mean(np.asarray(pred, float) - np.asarray(actual, float)))


def wape(actual, pred) -> float:
    """Weighted absolute percentage error = sum|e| / sum|y|. Zero hours are fine; all-zero is not."""
    actual = np.asarray(actual, float)
    denom = np.abs(actual).sum()
    if denom == 0:
        raise ValueError("WAPE is undefined when every actual value is zero")
    return float(np.abs(np.asarray(pred, float) - actual).sum() / denom)


def metric_row(actual, pred, capacity: int) -> dict:
    actual, pred = np.asarray(actual, float), np.asarray(pred, float)
    if actual.shape != pred.shape:
        raise ValueError(f"shape mismatch: actual {actual.shape} vs pred {pred.shape}")
    if not (np.isfinite(actual).all() and np.isfinite(pred).all()):
        raise ValueError("actual/pred contain NaN or infinite values")
    m, r = mae(actual, pred), rmse(actual, pred)
    return {
        "n": int(len(actual)),
        "mae_utilization": m, "rmse_utilization": r,
        "mae_pp": m * 100, "rmse_pp": r * 100,                    # percentage points of utilization
        "mae_spaces": m * capacity, "rmse_spaces": r * capacity,  # estimated occupied spaces
        "bias_pp": bias(actual, pred) * 100,
        "wape_percent": wape(actual, pred) * 100,                 # percentage ERROR (relative)
    }


def block_bootstrap_mean(diff: np.ndarray, block: int, reps: int, seed: int) -> dict:
    """
    Circular moving-block bootstrap of the mean of a paired loss differential. Blocks of
    `block` consecutive hours keep the daily autocorrelation that a plain bootstrap would break.
    """
    diff = np.asarray(diff, float)
    n = len(diff)
    if n < block:
        raise ValueError("series shorter than one bootstrap block")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(reps, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(reps, -1)[:, :n] % n
    means = diff[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"mean": float(diff.mean()), "ci95": [float(lo), float(hi)],
            "share_of_replicates_below_zero": float((means < 0).mean())}


# ===================================================================================
# Inputs
# ===================================================================================
def load_hourly() -> pd.DataFrame:
    h = pd.read_csv(config.HOURLY_SITE_FILE, index_col="timestamp_utc", parse_dates=["timestamp_utc"])
    if h.index.tz is None:
        h.index = h.index.tz_localize("UTC")
    return h


def load_test() -> dict:
    d = np.load(config.SEQUENCE_FILES["test"])
    return {k: d[k] for k in d.files}


def verify_inputs(model, test: dict, target_scaler, feature_scaler, hourly: pd.DataFrame) -> dict:
    """Every check must pass before any metric is computed."""
    fc = json.loads(config.FEATURE_CONFIG_FILE.read_text(encoding="utf-8"))
    mc = json.loads(config.MODEL_CONFIG_FILE.read_text(encoding="utf-8"))
    ts = json.loads(config.TRAINING_SUMMARY_FILE.read_text(encoding="utf-8"))
    X, y, y_un = test["X"], test["y"], test["y_unscaled"]
    checks = {
        "model_input_shape": list(model.input_shape),
        "model_output_shape": list(model.output_shape),
        "test_X_shape": list(X.shape), "test_y_shape": list(y.shape),
        "shapes_match_model": tuple(X.shape[1:]) == tuple(model.input_shape[1:]) and y.shape == (len(X), 1),
        "feature_order_matches_training": fc["features"] == config.FEATURES == mc["feature_metadata"]["features"],
        "target_scaler_inverse_reproduces_unscaled_targets":
            bool(np.allclose(target_scaler.inverse_transform(y), y_un, atol=1e-6)),
        "target_scaler_differs_from_feature_scaler": target_scaler.n_features_in_ == 1 and feature_scaler.n_features_in_ > 1,
        "unscaled_targets_match_hourly_utilization": bool(np.allclose(
            y_un.ravel(), hourly.loc[pd.to_datetime(test["target_timestamp_utc"], utc=True), "utilization"].to_numpy(), atol=1e-6)),
        "all_targets_in_test_split": bool((hourly.loc[pd.to_datetime(test["target_timestamp_utc"], utc=True), "split"] == "test").all()),
        "training_used_only_train_and_val": set(k.split("_")[1] for k in ts["data_shapes"]) == {"train", "val"},
        "no_nan_in_test_inputs": bool(np.isfinite(X).all() and np.isfinite(y).all()),
    }
    failed = [k for k, v in checks.items() if v is False]
    if failed:
        raise AssertionError(f"input verification failed: {failed}")
    return checks


# ===================================================================================
# Predictions
# ===================================================================================
def lstm_predictions(model, X: np.ndarray, target_scaler) -> np.ndarray:
    """Model output (target-scaler units) -> utilization. Raw output, no clipping."""
    import train
    scaled = train.predict_scaled(model, X)
    return target_scaler.inverse_transform(scaled).ravel()


def baseline_predictions(hourly: pd.DataFrame, target_times: pd.DatetimeIndex, lag_hours: int) -> np.ndarray:
    """
    utilization(t - lag) looked up by timestamp (not by row position, so a gap could never
    silently shift the alignment). The source hour must exist and be input-valid.
    """
    src = target_times - pd.Timedelta(hours=lag_hours)
    missing = src.difference(hourly.index)
    if len(missing):
        raise ValueError(f"{len(missing)} source hours for lag {lag_hours} are missing")
    rows = hourly.loc[src]
    if (rows["confirmed_invalid"] != 0).any() or rows["utilization"].isna().any():
        raise ValueError(f"lag {lag_hours}: source hours include invalid observations")
    return rows["utilization"].to_numpy(dtype=float)


def build_prediction_table(hourly, test, lstm_pred) -> pd.DataFrame:
    t = pd.to_datetime(test["target_timestamp_utc"], utc=True)
    cap = int(hourly["capacity"].iloc[0])
    df = pd.DataFrame(index=pd.DatetimeIndex(t, name="target_timestamp_utc"))
    df["target_timestamp_local"] = t.tz_convert(config.LOCAL_TZ).strftime("%Y-%m-%d %H:%M%z")
    df["site"] = config.SITE
    df["installed_capacity_spaces"] = cap
    df["actual_utilization"] = test["y_unscaled"].ravel().astype(float)
    df["pred_lstm"] = lstm_pred
    for key, lag in BASELINE_LAGS.items():
        df[f"pred_{key}"] = baseline_predictions(hourly, t, lag)
    for key in APPROACHES:
        df[f"error_{key}"] = df[f"pred_{key}"] - df["actual_utilization"]
    df["actual_occupied_spaces"] = df["actual_utilization"] * cap
    df["pred_lstm_occupied_spaces"] = df["pred_lstm"] * cap
    h = hourly.loc[t]
    for c in ("hour", "day_of_week", "is_weekend", "is_holiday"):
        df[c] = h[c].to_numpy()
    df["actual_utilization_excl_over_48h"] = h["utilization_excl_over_48h"].to_numpy()
    return df


# ===================================================================================
# Evaluation
# ===================================================================================
def evaluate(df: pd.DataFrame, capacity: int) -> dict:
    a = df["actual_utilization"].to_numpy()
    overall = {k: metric_row(a, df[f"pred_{k}"].to_numpy(), capacity) for k in APPROACHES}

    bs = config.BOOTSTRAP
    abs_lstm = np.abs(df["error_lstm"].to_numpy())
    comparisons = {}
    for k in BASELINE_LAGS:
        abs_base = np.abs(df[f"error_{k}"].to_numpy())
        boot = block_bootstrap_mean(abs_lstm - abs_base, bs["block_hours"], bs["replicates"], bs["seed"])
        comparisons[f"lstm_vs_{k}"] = {
            "mae_difference_pp": boot["mean"] * 100,                    # negative = LSTM better
            "mae_difference_ci95_pp": [x * 100 for x in boot["ci95"]],
            "mae_reduction_percent": (1 - overall["lstm"]["mae_utilization"] / overall[k]["mae_utilization"]) * 100,
            "rmse_reduction_percent": (1 - overall["lstm"]["rmse_utilization"] / overall[k]["rmse_utilization"]) * 100,
            "lstm_lower_mae": overall["lstm"]["mae_utilization"] < overall[k]["mae_utilization"],
            "lstm_lower_rmse": overall["lstm"]["rmse_utilization"] < overall[k]["rmse_utilization"],
            "difference_significant_95": boot["ci95"][1] < 0 or boot["ci95"][0] > 0,
        }

    subsets = {
        "weekday_non_holiday": (df["is_weekend"] == 0) & (df["is_holiday"] == 0),
        "weekend": df["is_weekend"] == 1,
        "holiday": df["is_holiday"] == 1,
        "weekday_daytime_07_19": (df["is_weekend"] == 0) & (df["is_holiday"] == 0) & df["hour"].between(7, 19),
    }
    by_subset = {}
    for name, mask in subsets.items():
        if mask.sum() == 0:
            continue
        mask = mask.to_numpy()
        by_subset[name] = {"n": int(mask.sum()), **{
            k: {"mae_pp": mae(a[mask], df.loc[mask, f"pred_{k}"]) * 100,
                "rmse_pp": rmse(a[mask], df.loc[mask, f"pred_{k}"]) * 100} for k in APPROACHES}}

    by_hour = {k: [mae(a[df["hour"] == h], df.loc[df["hour"] == h, f"pred_{k}"]) * 100 for h in range(24)]
               for k in APPROACHES}

    # Long-session sensitivity: same predictions, alternative ACTUAL series (no retraining).
    alt = df["actual_utilization_excl_over_48h"].to_numpy()
    sensitivity = {
        "what_it_measures": "target-definition sensitivity of the evaluation, NOT a model trained on the alternative target",
        "target_difference_mae_pp": mae(a, alt) * 100,
        "target_difference_max_pp": float(np.abs(a - alt).max() * 100),
        "hours_where_targets_differ": int((np.abs(a - alt) > 1e-9).sum()),
        "lstm_vs_alt_target": metric_row(alt, df["pred_lstm"].to_numpy(), capacity),
    }

    lp = df["pred_lstm"].to_numpy()
    return {
        "overall": overall,
        "comparisons": comparisons,
        "by_subset": by_subset,
        "mae_pp_by_local_hour": by_hour,
        "long_session_sensitivity": sensitivity,
        "lstm_prediction_range": [float(lp.min()), float(lp.max())],
        "lstm_predictions_below_0": int((lp < 0).sum()),
        "lstm_predictions_above_1": int((lp > 1).sum()),
        "test_hours_with_zero_actual": int((a == 0).sum()),
    }


# ===================================================================================
# Figures
# ===================================================================================
def _colors():
    from plot_style import SERIES
    return {"actual": SERIES[0], "lstm": SERIES[1], "previous_hour": SERIES[2], "same_hour_last_week": SERIES[6]}


def make_figures(df: pd.DataFrame, results: dict) -> list[str]:
    import plot_style
    from plot_style import TEXT_SECONDARY, plt

    plot_style.apply()
    c = _colors()
    config.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    local = df.index.tz_convert(config.LOCAL_TZ).tz_localize(None)
    a = df["actual_utilization"] * 100
    names = []

    def save(fig, name):
        fig.savefig(config.FIGURES_DIR / name)
        plt.close(fig)
        names.append(name)

    # 1. actual vs predicted over time: full test period + fixed two-week zoom
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.5))
    axes[0].plot(local, a, color=c["actual"], linewidth=1, label="actual")
    axes[0].plot(local, df["pred_lstm"] * 100, color=c["lstm"], linewidth=1, label="LSTM")
    axes[0].set_title("Test period: actual vs LSTM-predicted utilization (next hour)")
    zs, ze = (pd.Timestamp(x) for x in config.ZOOM_WINDOW_LOCAL)
    z = (local >= zs) & (local < ze)
    axes[1].plot(local[z], a[z], color=c["actual"], label="actual")
    axes[1].plot(local[z], df.loc[z, "pred_lstm"] * 100, color=c["lstm"], label="LSTM")
    axes[1].plot(local[z], df.loc[z, "pred_previous_hour"] * 100, color=c["previous_hour"], linewidth=1,
                 linestyle="--", label="previous hour")
    axes[1].plot(local[z], df.loc[z, "pred_same_hour_last_week"] * 100, color=c["same_hour_last_week"],
                 linewidth=1, linestyle=":", label="same hour last week")
    axes[1].set_title(f"Zoom: {config.ZOOM_WINDOW_LOCAL[0]} to {config.ZOOM_WINDOW_LOCAL[1]} (window fixed in config)")
    for ax in axes:
        ax.set_ylabel("Utilization (%)")
        ax.set_ylim(top=ax.get_ylim()[1] * 1.18)   # headroom so the legend never covers data
        ax.legend(loc="upper right", ncol=4)
    fig.tight_layout()
    save(fig, "eval_actual_vs_predicted_timeseries.png")

    # 2. scatter
    fig, ax = plt.subplots(figsize=(5.2, 5.2))
    ax.scatter(a, df["pred_lstm"] * 100, s=8, alpha=0.35, color=c["lstm"], edgecolors="none")
    lim = max(a.max(), df["pred_lstm"].max() * 100) * 1.05
    ax.plot([0, lim], [0, lim], color=TEXT_SECONDARY, linewidth=1, linestyle="--", label="perfect forecast")
    ax.set_xlim(-1, lim); ax.set_ylim(-1, lim)
    ax.set_xlabel("Actual utilization (%)"); ax.set_ylabel("LSTM predicted utilization (%)")
    ax.set_title("LSTM: predicted vs actual (test)")
    ax.legend(loc="upper left")
    save(fig, "eval_scatter_lstm.png")

    # 3. residual distribution (all three, same bins)
    fig, ax = plt.subplots(figsize=(8, 3.8))
    errs = {k: df[f"error_{k}"] * 100 for k in APPROACHES}
    bins = np.linspace(-25, 25, 101)
    for k in ("previous_hour", "same_hour_last_week", "lstm"):
        ax.hist(np.clip(errs[k], -25, 25), bins=bins, histtype="step", linewidth=1.6 if k == "lstm" else 1.2,
                color=c[k], label=APPROACHES[k])
    ax.axvline(0, color=TEXT_SECONDARY, linewidth=1)
    ax.set_xlabel("Forecast error (percentage points; values beyond ±25 shown at the edge)")
    ax.set_ylabel("Test hours")
    ax.set_title("Error distribution on the test set")
    ax.legend()
    save(fig, "eval_residual_distribution.png")

    # 4. residuals over time (LSTM)
    fig, ax = plt.subplots(figsize=(11, 3.4))
    ax.plot(local, errs["lstm"], color=c["lstm"], linewidth=0.8)
    ax.axhline(0, color=TEXT_SECONDARY, linewidth=1)
    hol = df["is_holiday"].to_numpy() == 1
    if hol.any():
        ax.fill_between(local, errs["lstm"].min(), errs["lstm"].max(), where=hol, color="#e4e3df", zorder=0,
                        label="holiday / Institute closure")
        ax.legend(loc="upper right")
    ax.set_ylabel("Error (pp)")
    ax.set_title("LSTM residuals over the test period (prediction − actual)")
    save(fig, "eval_residuals_over_time.png")

    # 5. MAE / RMSE comparison
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    keys = list(APPROACHES)
    x = np.arange(2)
    w = 0.26
    for i, k in enumerate(keys):
        vals = [results["overall"][k]["mae_pp"], results["overall"][k]["rmse_pp"]]
        bars = ax.bar(x + (i - 1) * w, vals, width=w - 0.02, color=c[k], label=APPROACHES[k])
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=8,
                    color=TEXT_SECONDARY)
    ax.set_xticks(x, ["MAE", "RMSE"])
    ax.set_ylabel("Percentage points of utilization")
    ax.set_title("Test-set error by approach (lower is better)")
    ax.legend()
    save(fig, "eval_metric_comparison.png")

    # 6. MAE by hour of day
    fig, ax = plt.subplots(figsize=(8, 3.6))
    for k in keys:
        ax.plot(range(24), results["mae_pp_by_local_hour"][k], color=c[k], label=APPROACHES[k],
                linewidth=2 if k == "lstm" else 1.4)
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlabel("Target hour of day (local)")
    ax.set_ylabel("MAE (pp)")
    ax.set_title("Test-set MAE by hour of day")
    ax.legend()
    save(fig, "eval_mae_by_hour.png")
    return names


# ===================================================================================
# Report
# ===================================================================================
def _fmt(x, d=3):
    return f"{x:.{d}f}"


def write_report(meta: dict, results: dict, figs: list[str]) -> None:
    o, cmp_ = results["overall"], results["comparisons"]
    L = [
        "# Evaluation Report — LSTM vs baselines (test set)",
        "",
        f"_Generated by `ml-service/evaluate.py` at {meta['generated_utc']}. All numbers come from the run._",
        "",
        "## Setup",
        "",
        f"- **Model:** `models/{config.MODEL_FILE.name}` (best epoch {meta['best_epoch']}, selected on validation loss). Not retrained or tuned here.",
        f"- **Test period (target hours, local):** {meta['test_first_target_local'][:16]} → {meta['test_last_target_local'][:16]}; **n = {meta['n']}** hourly targets, identical for all approaches.",
        f"- **Target:** next-hour utilization of {meta['capacity']} installed spaces. Predictions are inverse-transformed with the target scaler.",
        "- **Baselines:** previous hour = utilization(t−1 h); same hour last week = utilization(t−168 h). Both are looked up by timestamp from the observed history.",
        "- **Units:** MAE/RMSE in **percentage points (pp)** of utilization and in **occupied spaces** (× 54). WAPE is a **percentage error** (Σ|error| / Σ actual).",
        f"- **MAPE is not reported:** {results['test_hours_with_zero_actual']} test hours have zero utilization, where percentage error is undefined.",
        "",
        "## Results",
        "",
        "| Approach | MAE (pp) | RMSE (pp) | MAE (spaces) | RMSE (spaces) | Bias (pp) | WAPE (%) | n |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for k, name in APPROACHES.items():
        r = o[k]
        L.append(f"| {name} | {_fmt(r['mae_pp'])} | {_fmt(r['rmse_pp'])} | {_fmt(r['mae_spaces'], 2)} | "
                 f"{_fmt(r['rmse_spaces'], 2)} | {_fmt(r['bias_pp'])} | {_fmt(r['wape_percent'], 1)} | {r['n']} |")
    L += ["", "## LSTM vs each baseline", "",
          "MAE difference = mean(|LSTM error| − |baseline error|); negative means the LSTM is better. "
          f"95% interval from a paired circular block bootstrap ({config.BOOTSTRAP['block_hours']}-hour blocks, "
          f"{config.BOOTSTRAP['replicates']} replicates, seed {config.BOOTSTRAP['seed']}).", "",
          "| Comparison | MAE diff (pp) | 95% CI (pp) | MAE reduction | RMSE reduction | Lower MAE? | Lower RMSE? | Significant? |",
          "|---|---:|---|---:|---:|---|---|---|"]
    for k, cm in cmp_.items():
        lo, hi = cm["mae_difference_ci95_pp"]
        L.append(f"| {k.replace('_', ' ')} | {_fmt(cm['mae_difference_pp'])} | [{_fmt(lo)}, {_fmt(hi)}] | "
                 f"{_fmt(cm['mae_reduction_percent'], 1)}% | {_fmt(cm['rmse_reduction_percent'], 1)}% | "
                 f"{'yes' if cm['lstm_lower_mae'] else 'no'} | {'yes' if cm['lstm_lower_rmse'] else 'no'} | "
                 f"{'yes' if cm['difference_significant_95'] else 'no'} |")
    L += ["", "## By period", "", "| Subset | n | " + " | ".join(f"{n} MAE / RMSE (pp)" for n in APPROACHES.values()) + " |",
          "|---|---:|" + "---|" * len(APPROACHES)]
    for name, s in results["by_subset"].items():
        L.append(f"| {name.replace('_', ' ')} | {s['n']} | " + " | ".join(
            f"{_fmt(s[k]['mae_pp'], 2)} / {_fmt(s[k]['rmse_pp'], 2)}" for k in APPROACHES) + " |")
    L += ["", "## Where a baseline beats the LSTM", ""]
    for k in BASELINE_LAGS:
        hrs = [h for h in range(24) if results["mae_pp_by_local_hour"][k][h] < results["mae_pp_by_local_hour"]["lstm"][h]]
        L.append(f"- {APPROACHES[k]} has lower MAE than the LSTM at target hours (local): "
                 f"{', '.join(f'{h:02d}' for h in hrs) if hrs else 'none'}.")
    for name, sub in results["by_subset"].items():
        for k in BASELINE_LAGS:
            if sub[k]["mae_pp"] < sub["lstm"]["mae_pp"]:
                L.append(f"- In the **{name.replace('_', ' ')}** subset, {APPROACHES[k]} has lower MAE than the LSTM "
                         f"({_fmt(sub[k]['mae_pp'], 2)} vs {_fmt(sub['lstm']['mae_pp'], 2)} pp).")
    s = results["long_session_sensitivity"]
    lv = s["lstm_vs_alt_target"]
    L += ["", "## Long-session sensitivity", "",
          f"This measures **{s['what_it_measures']}**. The same LSTM predictions are scored against the alternative "
          "actual series that excludes sessions longer than 48 h. No model was trained on that target.", "",
          f"- The two targets differ in {s['hours_where_targets_differ']} of {meta['n']} test hours "
          f"(mean |difference| {_fmt(s['target_difference_mae_pp'])} pp, max {_fmt(s['target_difference_max_pp'], 2)} pp).",
          f"- LSTM vs alternative target: MAE {_fmt(lv['mae_pp'])} pp, RMSE {_fmt(lv['rmse_pp'])} pp, bias {_fmt(lv['bias_pp'])} pp "
          f"(vs {_fmt(o['lstm']['mae_pp'])} / {_fmt(o['lstm']['rmse_pp'])} / {_fmt(o['lstm']['bias_pp'])} pp on the main target).",
          "", "## Other diagnostics", "",
          f"- LSTM raw prediction range: {_fmt(results['lstm_prediction_range'][0] * 100, 2)}% to "
          f"{_fmt(results['lstm_prediction_range'][1] * 100, 2)}%; predictions below 0: {results['lstm_predictions_below_0']}, "
          f"above 100%: {results['lstm_predictions_above_1']}. Metrics use the raw outputs (no clipping).",
          "", "## Figures", ""]
    L += [f"![{f}](figures/{f})" for f in figs]
    L += ["", "## Limitations", "",
          "- One site, one test period of about ten weeks (including the 2019 winter closure). Results may not transfer to other sites or seasons.",
          "- Utilization is measured against installed (not operational) capacity.",
          "- Single training run with one seed; run-to-run variance of the LSTM is not measured.",
          "- The LSTM has more information than either baseline (24 hours of history, lag-168 and calendar features); the baselines are naive persistence and seasonal-naive forecasts, not equally informed competitors.",
          "- All three are one-step-ahead (next-hour) forecasts from observed history; accuracy further ahead, as booking several hours in advance would need, is not evaluated here.",
          ]
    config.EVAL_REPORT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


# ===================================================================================
def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from tensorflow import keras

    model = keras.models.load_model(config.MODEL_FILE)
    target_scaler = joblib.load(config.TARGET_SCALER_FILE)
    feature_scaler = joblib.load(config.FEATURE_SCALER_FILE)
    hourly = load_hourly()
    test = load_test()
    checks = verify_inputs(model, test, target_scaler, feature_scaler, hourly)
    log.info("Input checks passed: %s", {k: v for k, v in checks.items() if isinstance(v, bool)})

    lstm_pred = lstm_predictions(model, test["X"], target_scaler)
    df = build_prediction_table(hourly, test, lstm_pred)
    cap = int(df["installed_capacity_spaces"].iloc[0])
    results = evaluate(df, cap)

    ts = json.loads(config.TRAINING_SUMMARY_FILE.read_text(encoding="utf-8"))
    meta = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_file": f"models/{config.MODEL_FILE.name}", "best_epoch": ts["best_epoch"],
        "n": int(len(df)), "capacity": cap,
        "test_first_target_local": df["target_timestamp_local"].iloc[0],
        "test_last_target_local": df["target_timestamp_local"].iloc[-1],
        "input_checks": checks,
    }
    config.EVAL_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(config.TEST_PREDICTIONS_FILE, float_format="%.6f")
    config.EVAL_METRICS_FILE.write_text(json.dumps({"meta": meta, **results}, indent=2), encoding="utf-8")
    pd.DataFrame(results["overall"]).T.rename_axis("approach").to_csv(config.EVAL_TABLE_FILE, float_format="%.6f")
    figs = make_figures(df, results)
    write_report(meta, results, figs)

    for k, name in APPROACHES.items():
        r = results["overall"][k]
        log.info("%-20s MAE %.3f pp (%.2f spaces)  RMSE %.3f pp (%.2f spaces)  n=%d", name, r["mae_pp"],
                 r["mae_spaces"], r["rmse_pp"], r["rmse_spaces"], r["n"])
    for k, cm in results["comparisons"].items():
        log.info("%s: MAE diff %.3f pp, 95%% CI [%.3f, %.3f], significant=%s", k, cm["mae_difference_pp"],
                 *cm["mae_difference_ci95_pp"], cm["difference_significant_95"])


if __name__ == "__main__":
    main()
