"""
Central configuration for the ML pipeline. Every value that affects results lives here
so experiments are reproducible and easy to explain.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "dataset" / "raw"
PROCESSED_DIR = ROOT / "dataset" / "processed"
MODELS_DIR = ROOT / "models"
DOCS_DIR = ROOT / "docs"
FIGURES_DIR = DOCS_DIR / "figures"

# ---- Data source -------------------------------------------------------------------
# One ACN site: the Caltech garage. Results describe this single site only.
SITE = "caltech"
RAW_SESSIONS = RAW_DIR / "acn_caltech_sessions.csv"
LOCAL_TZ = "America/Los_Angeles"   # Pasadena, CA; raw timestamps are UTC

# ---- Analysis window (local time, end exclusive) -----------------------------------
#  - Start 2018-11-01: Caltech introduced a $0.12/kWh fee on this date and usage dropped
#    sharply (Lee, Li & Low, ACN-Data, e-Energy 2019, Sec. 3.1.2).
#  - End 2020-03-01: COVID-19 campus closures collapsed demand from March 2020, and the
#    raw data has no sessions at all in Sep-Oct 2020.
ANALYSIS_START = "2018-11-01"
ANALYSIS_END = "2020-03-01"
INTERVAL = "1h"

# ---- Capacity ----------------------------------------------------------------------
# Denominator of utilization = installed charging spaces: distinct spaces with at least one
# session overlapping the window (54). Constant; NOT operational capacity, which the dataset
# does not record. Outages are never inferred from inactivity.
CAPACITY_MODE = "installed_fixed"

# ---- Long sessions (all kept; flagged for reporting) --------------------------------
LONG_SESSION_FLAG_HOURS = (24.0, 48.0)
# A sensitivity-only occupancy series is built without sessions longer than this.
SENSITIVITY_EXCLUDE_OVER_HOURS = 48.0

# ---- Holidays (known in advance, used as the is_holiday feature) -------------------
# US federal holidays, minus the two that are ordinary working days at this site: sessions
# on Veterans Day (54 in 2018, 40 in 2019) and Columbus Day (34 in 2019) were inside the
# normal weekday range (median 38). These dates are in the train/val periods only.
FEDERAL_HOLIDAYS_NOT_OBSERVED = ("Columbus Day", "Veterans Day")
# Caltech Institute winter closures, published in advance on the Caltech events calendar:
#   https://www.caltech.edu/campus-life-events/calendar/institute-holidays    (2018)
#   https://www.caltech.edu/campus-life-events/calendar/institute-holidays-2  (2019)
# Inclusive local dates. Add each new year's closure before forecasting that period.
INSTITUTE_CLOSURES = (("2018-12-24", "2019-01-01"), ("2019-12-25", "2020-01-01"))

# ---- Data validity -----------------------------------------------------------------
# Non-holiday weekdays with zero sessions are FLAGGED as suspected outages (reported only).
# Only periods listed here, with evidence, are excluded from sequences. None are known.
CONFIRMED_INVALID_PERIODS: tuple[tuple[str, str, str], ...] = ()   # (start_local, end_local, reason)

# ---- Splits ------------------------------------------------------------------------
# Chronological ratios; each boundary is moved to the nearest local midnight.
SPLIT_RATIOS = (0.70, 0.15, 0.15)

# ---- LSTM inputs -------------------------------------------------------------------
SEQUENCE_LENGTH = 24      # previous 24 hours ...
HORIZON = 1               # ... predict the next hour
TARGET = "utilization"    # time-weighted mean occupied spaces in the hour / installed capacity
ROLLING_WINDOW = 24       # trailing mean over hours t-23 .. t
WEEKLY_LAG = 168          # utilization at t-168 (same hour one week earlier)

# Feature order inside each input time step. Continuous features are min-max scaled with a
# scaler fitted on valid training rows only; cyclical and binary features are already bounded.
SCALED_FEATURES = ["utilization", "utilization_lag_168", "utilization_roll_mean_24",
                   "arrivals", "energy_kwh_completed"]
UNSCALED_FEATURES = ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend", "is_holiday"]
FEATURES = SCALED_FEATURES + UNSCALED_FEATURES

# ---- Output files ------------------------------------------------------------------
HOURLY_SITE_FILE = PROCESSED_DIR / "hourly_utilization.csv"
HOURLY_SPACE_FILE = PROCESSED_DIR / "hourly_space_occupancy.csv.gz"
SESSION_FLAGS_FILE = PROCESSED_DIR / "session_flags.csv"
SEQUENCE_FILES = {s: PROCESSED_DIR / f"sequences_{s}.npz" for s in ("train", "val", "test")}
REPORT_JSON = PROCESSED_DIR / "preprocessing_report.json"
REPORT_MD = DOCS_DIR / "preprocessing_report.md"
FEATURE_SCALER_FILE = MODELS_DIR / "feature_scaler.pkl"
TARGET_SCALER_FILE = MODELS_DIR / "target_scaler.pkl"
FEATURE_CONFIG_FILE = MODELS_DIR / "features.json"

# ---- LSTM training (Phase 2) ---------------------------------------------------------
# Defaults for train.py; every value can be overridden on the command line.
TRAINING = {
    "lstm_units": (64, 32),        # LSTM(64, return_sequences=True) -> LSTM(32)
    "dropout": 0.2,                # after each LSTM layer
    "dense_units": 16,             # Dense(16, relu) -> Dense(1)
    "learning_rate": 1e-3,         # Adam
    "batch_size": 256,
    "max_epochs": 100,
    "early_stopping_patience": 10,  # epochs without val_loss improvement
    "seed": 42,
}
MODEL_FILE = MODELS_DIR / "ev_demand_lstm.keras"
MODEL_CONFIG_FILE = MODELS_DIR / "model_config.json"
TRAINING_HISTORY_FILE = MODELS_DIR / "training_history.csv"
TRAINING_SUMMARY_FILE = MODELS_DIR / "training_summary.json"
LOSS_FIGURE = FIGURES_DIR / "training_loss_curves.png"

# ---- Evaluation (Phase 3) ------------------------------------------------------------
EVAL_DIR = MODELS_DIR / "evaluation"
TEST_PREDICTIONS_FILE = EVAL_DIR / "test_predictions.csv"
EVAL_METRICS_FILE = EVAL_DIR / "test_metrics.json"
EVAL_TABLE_FILE = EVAL_DIR / "test_metrics_table.csv"
EVAL_REPORT_MD = DOCS_DIR / "evaluation_report.md"
# Paired moving-block bootstrap for "is the LSTM's MAE lower than a baseline's?"
BOOTSTRAP = {"block_hours": 24, "replicates": 2000, "seed": 42}
# Fixed two-week window for the zoomed actual-vs-predicted plot (chosen before looking at
# test results: the first two full Mon-Sun weeks after the 2019 winter closure).
ZOOM_WINDOW_LOCAL = ("2020-01-06", "2020-01-20")
