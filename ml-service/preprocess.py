"""
Phase 1 - preprocessing pipeline: raw ACN-Data sessions (Caltech site) -> hourly utilization
time series -> scaled, split-contained LSTM sequences.

Conventions (all documented in docs/preprocessing_report.md):
  * Raw timestamps are UTC. Hourly buckets use a UTC index (no DST gaps or duplicates);
    calendar features come from America/Los_Angeles local time.
  * Occupancy uses connectionTime -> disconnectTime only. doneChargingTime is never used.
  * Intervals are half-open [connect, disconnect): a session ending exactly at 10:00:00
    occupies nothing in the 10:00-11:00 hour; one starting at 10:00:00 counts from 10:00.
  * occupied_spaces(h) = sum over spaces of seconds occupied in hour h / 3600
    (time-weighted mean number of occupied spaces). Overlapping sessions on one space are
    merged, so a space counts at most once and the total cannot exceed capacity.
  * utilization(h) = occupied_spaces(h) / installed capacity (54 spaces).
  * Energy (kWhDelivered) is assigned to the hour the session ends - it is only known then.

Run: uv run preprocess.py
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from sklearn.preprocessing import MinMaxScaler

import config

log = logging.getLogger("preprocess")

TIME_COLS = ["connectionTime", "disconnectTime", "doneChargingTime"]
REQUIRED_COLS = {"_id", "sessionID", "stationID", "spaceID", "connectionTime", "disconnectTime",
                 "kWhDelivered"}
HOUR = pd.Timedelta(config.INTERVAL)
SPLITS = ("train", "val", "test")


def _utc64(values) -> np.ndarray:
    """tz-aware Series/Index -> naive UTC datetime64[ns] array (for fast vector maths)."""
    values = values.dt.tz_convert(None) if isinstance(values, pd.Series) else values.tz_convert(None)
    return values.to_numpy(dtype="datetime64[ns]")


def _local_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index.tz_convert(config.LOCAL_TZ).tz_localize(None).normalize()


# ===================================================================================
# 1. Load, parse, validate
# ===================================================================================
def load_sessions(path=config.RAW_SESSIONS) -> pd.DataFrame:
    """Read the raw export as strings. The raw file is never modified."""
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run fetch_acn_data.py first")
    df = pd.read_csv(path, dtype=str)
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"raw dataset is missing required columns: {sorted(missing)}")
    return df


def parse_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """Parse ISO-8601 timestamps to UTC. Unparseable values become NaT (counted, never guessed)."""
    out = df.copy()
    for c in TIME_COLS:
        if c in out.columns:
            out[c] = pd.to_datetime(out[c], utc=True, errors="coerce", format="ISO8601")
    out["kWhDelivered"] = pd.to_numeric(out["kWhDelivered"], errors="coerce")
    return out


def overlapping_sessions(df: pd.DataFrame) -> int:
    """Sessions that start before the previous session on the same space has ended."""
    t = df.dropna(subset=["connectionTime", "disconnectTime"]).sort_values(["stationID", "connectionTime"])
    prev_end = t.groupby("stationID")["disconnectTime"].shift()
    return int((t["connectionTime"] < prev_end).sum())


def validate_sessions(raw: pd.DataFrame, parsed: pd.DataFrame) -> dict:
    """Measure data quality over the whole raw file. Nothing is changed here."""
    p = parsed
    dur = (p["disconnectTime"] - p["connectionTime"]).dt.total_seconds() / 3600
    done = p["doneChargingTime"] if "doneChargingTime" in p else pd.Series(pd.NaT, index=p.index)
    done_missing = done.isna()
    kwh = p["kWhDelivered"]
    one_to_one = (p.groupby("stationID")["spaceID"].nunique().max() == 1
                  and p.groupby("spaceID")["stationID"].nunique().max() == 1)
    return {
        "records": int(len(raw)),
        "columns": list(raw.columns),
        "missing_values_raw": {c: int(v) for c, v in raw.isna().sum().items()},
        "timezone_values": sorted(raw["timezone"].dropna().unique().tolist()) if "timezone" in raw else [],
        "site_ids": sorted(raw["siteID"].dropna().unique().tolist()) if "siteID" in raw else [],
        "coverage_local": [str(p["connectionTime"].min().tz_convert(config.LOCAL_TZ)),
                           str(p["connectionTime"].max().tz_convert(config.LOCAL_TZ))],
        "stations": int(p["stationID"].nunique()),
        "spaces": int(p["spaceID"].nunique()),
        "station_to_space_one_to_one": bool(one_to_one),
        "duplicate_id": int(p["_id"].duplicated().sum()),
        "duplicate_sessionID": int(p["sessionID"].duplicated().sum()),
        "duplicate_station_and_connectionTime": int(p.duplicated(["stationID", "connectionTime"]).sum()),
        "exact_duplicate_rows": int(raw.duplicated().sum()),
        "unparseable_or_missing_connectionTime": int(p["connectionTime"].isna().sum()),
        "unparseable_or_missing_disconnectTime": int(p["disconnectTime"].isna().sum()),
        "disconnect_not_after_connect": int((dur <= 0).sum()),
        "missing_kWh": int(kwh.isna().sum()),
        "negative_kWh": int((kwh < 0).sum()),
        "zero_kWh": int((kwh == 0).sum()),
        "min_kWh": round(float(kwh.min()), 3),
        "sessions_starting_on_exact_hour": int((p["connectionTime"] == p["connectionTime"].dt.floor("h")).sum()),
        "sessions_ending_on_exact_hour": int((p["disconnectTime"] == p["disconnectTime"].dt.floor("h")).sum()),
        "overlapping_sessions_same_space": overlapping_sessions(p),
        "doneChargingTime": {
            "missing": int(done_missing.sum()),
            "missing_by_year": {int(k): int(v) for k, v in p.loc[done_missing, "connectionTime"]
                                .dt.tz_convert(config.LOCAL_TZ).dt.year.value_counts().sort_index().items()},
            "median_kWh_when_missing": round(float(kwh[done_missing].median()), 3) if done_missing.any() else None,
            "median_kWh_when_present": round(float(kwh[~done_missing].median()), 3),
            "earlier_than_connectionTime": int((done < p["connectionTime"]).sum()),
            "later_than_disconnectTime": int((done > p["disconnectTime"]).sum()),
        },
    }


# ===================================================================================
# 2. Clean and flag sessions
# ===================================================================================
def clean_sessions(parsed: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Drop only records that cannot describe a real occupancy interval; count every drop.
    Kept on purpose: long sessions (the space is genuinely occupied) and missing
    doneChargingTime (never used). Adds duration_h and long-session flags.
    """
    t = parsed.copy()
    stats = {"input_rows": int(len(t))}

    def drop(mask: pd.Series, reason: str):
        nonlocal t
        stats[reason] = int(mask.sum())
        t = t[~mask]

    drop(t["connectionTime"].isna(), "dropped_missing_or_unparseable_connectionTime")
    drop(t["disconnectTime"].isna(), "dropped_missing_or_unparseable_disconnectTime")
    drop(t["disconnectTime"] <= t["connectionTime"], "dropped_disconnect_not_after_connect")
    drop(t["_id"].duplicated(keep="first"), "dropped_duplicate_id")
    drop(t.duplicated(["stationID", "connectionTime"], keep="first"), "dropped_duplicate_station_and_connectionTime")
    drop(t["kWhDelivered"].isna() | (t["kWhDelivered"] < 0), "dropped_missing_or_negative_kWh")

    t["duration_h"] = (t["disconnectTime"] - t["connectionTime"]).dt.total_seconds() / 3600
    for h in config.LONG_SESSION_FLAG_HOURS:
        t[f"over_{int(h)}h"] = t["duration_h"] > h
        stats[f"kept_flagged_over_{int(h)}h"] = int(t[f"over_{int(h)}h"].sum())
    if "doneChargingTime" in t:
        stats["kept_missing_doneChargingTime"] = int(t["doneChargingTime"].isna().sum())

    t = t.sort_values("connectionTime", kind="stable").reset_index(drop=True)
    stats["output_rows"] = int(len(t))
    return t, stats


def window_bounds(start=config.ANALYSIS_START, end=config.ANALYSIS_END):
    return (pd.Timestamp(start, tz=config.LOCAL_TZ).tz_convert("UTC"),
            pd.Timestamp(end, tz=config.LOCAL_TZ).tz_convert("UTC"))


def hourly_index(start=config.ANALYSIS_START, end=config.ANALYSIS_END) -> pd.DatetimeIndex:
    """Hourly UTC index covering local [start, end)."""
    s, e = window_bounds(start, end)
    return pd.date_range(s, e, freq=config.INTERVAL, inclusive="left", name="timestamp_utc")


def overlapping_window(sessions: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Sessions whose interval overlaps the index range (includes ones that began earlier)."""
    lo, hi = index[0], index[-1] + HOUR
    return sessions[(sessions["disconnectTime"] > lo) & (sessions["connectionTime"] < hi)]


# ===================================================================================
# 3. Occupancy
# ===================================================================================
def merge_space_intervals(sessions: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Union of [connect, disconnect) per space. Returns (intervals, number_of_merges)."""
    rows, merges = [], 0
    t = sessions.sort_values(["stationID", "connectionTime"])
    for station, g in t.groupby("stationID", sort=False):
        cur_s = cur_e = None
        for s, e in zip(g["connectionTime"], g["disconnectTime"]):
            if cur_s is None:
                cur_s, cur_e = s, e
            elif s < cur_e:
                merges += 1
                cur_e = max(cur_e, e)
            else:
                rows.append((station, cur_s, cur_e))
                cur_s, cur_e = s, e
        if cur_s is not None:
            rows.append((station, cur_s, cur_e))
    return pd.DataFrame(rows, columns=["stationID", "start", "end"]), merges


def space_hourly_occupancy(intervals: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Fraction of each hour each space was occupied (0..1), exact to the second.
    Interval [s, e) touches hours floor(s) .. ceil(e) - 1h.
    """
    cols = ["timestamp_utc", "stationID", "occupied_fraction"]
    lo, hi = index[0], index[-1] + HOUR
    iv = intervals[(intervals["end"] > lo) & (intervals["start"] < hi)]
    if iv.empty:
        return pd.DataFrame(columns=cols)
    first = iv["start"].dt.floor(config.INTERVAL).clip(lower=lo)
    last_excl = iv["end"].dt.ceil(config.INTERVAL).clip(upper=hi)
    n = ((last_excl - first) / HOUR).astype(int).to_numpy()

    rep = np.repeat(np.arange(len(iv)), n)
    offset = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
    hour = _utc64(first)[rep] + offset * np.timedelta64(1, "h")
    seg_start = np.maximum(_utc64(iv["start"])[rep], hour)
    seg_end = np.minimum(_utc64(iv["end"])[rep], hour + np.timedelta64(1, "h"))
    frac = (seg_end - seg_start) / np.timedelta64(1, "h")

    out = pd.DataFrame({"timestamp_utc": pd.DatetimeIndex(hour).tz_localize("UTC"),
                        "stationID": iv["stationID"].to_numpy()[rep], "occupied_fraction": frac})
    out = out[out["occupied_fraction"] > 0]
    out = out.groupby(["timestamp_utc", "stationID"], as_index=False)["occupied_fraction"].sum()
    # Merged intervals cannot overlap, so <= 1 holds by construction; clip float noise only.
    out["occupied_fraction"] = out["occupied_fraction"].clip(0, 1).round(6)
    return out[cols]


def occupied_spaces(sessions: pd.DataFrame, index: pd.DatetimeIndex):
    intervals, merges = merge_space_intervals(sessions)
    per_space = space_hourly_occupancy(intervals, index)
    total = per_space.groupby("timestamp_utc")["occupied_fraction"].sum().reindex(index, fill_value=0.0)
    return total, per_space, intervals, merges


def peak_concurrency(intervals: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Maximum number of simultaneously occupied spaces at any instant within each hour."""
    if intervals.empty:
        return pd.Series(0, index=index)
    starts = np.sort(_utc64(intervals["start"]))
    ends = np.sort(_utc64(intervals["end"]))
    h = _utc64(index)
    at_hour_start = np.searchsorted(starts, h, side="right") - np.searchsorted(ends, h, side="right")
    level_after_start = np.arange(1, len(starts) + 1) - np.searchsorted(ends, starts, side="right")
    within = (pd.Series(level_after_start, index=pd.DatetimeIndex(starts).floor(config.INTERVAL))
              .groupby(level=0).max())
    within.index = within.index.tz_localize("UTC")
    within = within.reindex(index, fill_value=0).to_numpy()
    return pd.Series(np.maximum(at_hour_start, within), index=index).astype(int)


def installed_capacity(sessions: pd.DataFrame, index: pd.DatetimeIndex) -> int:
    """Distinct spaces with at least one session overlapping the window."""
    return int(overlapping_window(sessions, index)["stationID"].nunique())


def active_spaces_by_month(sessions: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """
    REPORTING ONLY: spaces with >= 1 session overlapping each local calendar month, mapped to
    every hour of that month. It uses the whole month (including later hours), so it must never
    be a model input or target.
    """
    month_of_hour = index.tz_convert(config.LOCAL_TZ).tz_localize(None).to_period("M")
    counts = {}
    for m in month_of_hour.unique():
        lo = pd.Timestamp(m.start_time, tz=config.LOCAL_TZ).tz_convert("UTC")
        hi = pd.Timestamp(m.end_time.normalize() + pd.Timedelta(days=1), tz=config.LOCAL_TZ).tz_convert("UTC")
        active = sessions[(sessions["disconnectTime"] > lo) & (sessions["connectionTime"] < hi)]
        counts[m] = active["stationID"].nunique()
    return pd.Series([counts[m] for m in month_of_hour], index=index)


def site_hourly(sessions: pd.DataFrame, index: pd.DatetimeIndex, capacity: int):
    """Site-level hourly table, plus the per-space table and interval stats behind it."""
    lo, hi = index[0], index[-1] + HOUR
    occ, per_space, intervals, merges = occupied_spaces(sessions, index)

    starts_in = sessions[(sessions["connectionTime"] >= lo) & (sessions["connectionTime"] < hi)]
    arrivals = starts_in.groupby(starts_in["connectionTime"].dt.floor(config.INTERVAL)).size()
    ends_in = sessions[(sessions["disconnectTime"] >= lo) & (sessions["disconnectTime"] < hi)]
    energy = ends_in.groupby(ends_in["disconnectTime"].dt.floor(config.INTERVAL))["kWhDelivered"].sum()

    df = pd.DataFrame(index=index)
    df["capacity"] = capacity
    df["occupied_spaces"] = occ.round(4)
    df["utilization"] = (occ / capacity).round(6)
    df["arrivals"] = arrivals.reindex(index, fill_value=0).astype(int)
    df["energy_kwh_completed"] = energy.reindex(index, fill_value=0.0).round(3)

    # ---- reporting / sensitivity only (never model inputs or targets) ----
    df["peak_occupied_spaces"] = peak_concurrency(intervals, index)
    limit = config.SENSITIVITY_EXCLUDE_OVER_HOURS
    occ_short, *_ = occupied_spaces(sessions[sessions["duration_h"] <= limit], index)
    df[f"occupied_spaces_excl_over_{int(limit)}h"] = occ_short.round(4)
    df[f"utilization_excl_over_{int(limit)}h"] = (occ_short / capacity).round(6)
    df["active_spaces_month"] = active_spaces_by_month(sessions, index)
    df["utilization_active_month"] = (occ / df["active_spaces_month"].replace(0, np.nan)).round(6)

    if (df["occupied_spaces"] > capacity + 1e-9).any() or (df["peak_occupied_spaces"] > capacity).any():
        raise AssertionError("occupancy exceeds installed capacity")
    return df, per_space, merges


# ===================================================================================
# 4. Calendar, holidays, validity
# ===================================================================================
def holiday_dates(first_day, last_day) -> pd.DatetimeIndex:
    """Observed holidays: federal holidays (minus ones this site works) + Institute closures."""
    fed = USFederalHolidayCalendar().holidays(first_day, last_day, return_name=True)
    observed = set(fed[~fed.isin(config.FEDERAL_HOLIDAYS_NOT_OBSERVED)].index)
    for s, e in config.INSTITUTE_CLOSURES:
        observed.update(pd.date_range(s, e, freq="D"))
    lo, hi = pd.Timestamp(first_day), pd.Timestamp(last_day)
    return pd.DatetimeIndex(sorted(d for d in observed if lo <= d <= hi))


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    local = out.index.tz_convert(config.LOCAL_TZ)
    days = _local_dates(out.index)
    out["timestamp_local"] = local.strftime("%Y-%m-%d %H:%M%z")
    out["hour"] = local.hour
    out["day_of_week"] = local.dayofweek             # 0 = Monday
    out["month"] = local.month
    out["is_weekend"] = (local.dayofweek >= 5).astype(int)
    out["is_holiday"] = days.isin(holiday_dates(days.min(), days.max())).astype(int)
    out["hour_sin"] = np.sin(2 * np.pi * out["hour"] / 24)
    out["hour_cos"] = np.cos(2 * np.pi * out["hour"] / 24)
    out["dow_sin"] = np.sin(2 * np.pi * out["day_of_week"] / 7)
    out["dow_cos"] = np.cos(2 * np.pi * out["day_of_week"] / 7)
    return out


def add_history_features(df: pd.DataFrame, lag: int = config.WEEKLY_LAG,
                         window: int = config.ROLLING_WINDOW) -> pd.DataFrame:
    """
    Backward-looking only, computed on the full contiguous hourly series:
      utilization_lag_168[t]      = utilization[t - 168]          (NaN for the first 168 hours)
      utilization_roll_mean_24[t] = mean(utilization[t-23 .. t])  (NaN for the first 23 hours)
    Both are inputs at step t used to predict t+1. At the start of the validation/test period
    they may read hours from the preceding split - that is past data, available at prediction
    time, so it is not leakage. They never read any hour after t.
    """
    out = df.copy()
    out[f"utilization_lag_{lag}"] = out["utilization"].shift(lag)
    out[f"utilization_roll_mean_{window}"] = out["utilization"].rolling(window, min_periods=window).mean()
    return out


def suspected_outage_days(df: pd.DataFrame) -> list[str]:
    """FLAG ONLY: non-holiday weekdays with zero arrivals at the whole site."""
    days = _local_dates(df.index)
    daily = df["arrivals"].groupby(days).sum()
    hol = holiday_dates(days.min(), days.max())
    suspect = daily[(daily == 0) & (daily.index.dayofweek < 5) & ~daily.index.isin(hol)]
    return [d.date().isoformat() for d in suspect.index]


def confirmed_invalid_mask(index: pd.DatetimeIndex, periods=config.CONFIRMED_INVALID_PERIODS) -> np.ndarray:
    mask = np.zeros(len(index), dtype=bool)
    for start, end, _reason in periods:
        s, e = window_bounds(start, end)
        mask |= (index >= s) & (index < e)
    return mask


def split_labels(index: pd.DatetimeIndex, ratios=config.SPLIT_RATIOS) -> np.ndarray:
    """
    Chronological train/val/test labels. Each ratio boundary is moved to the nearest local
    midnight so a split never starts mid-day. No shuffling.
    """
    if len(ratios) != 3 or not np.isclose(sum(ratios), 1.0) or min(ratios) <= 0:
        raise ValueError("split ratios must be three positive values summing to 1")
    n = len(index)
    midnights = np.nonzero(index.tz_convert(config.LOCAL_TZ).hour == 0)[0]
    if len(midnights) < 3:
        raise ValueError("index too short to split on local midnights")

    def snap(pos: int) -> int:
        return int(midnights[np.argmin(np.abs(midnights - pos))])

    b1 = snap(int(n * ratios[0]))
    b2 = snap(int(n * (ratios[0] + ratios[1])))
    if not 0 < b1 < b2 < n:
        raise ValueError("split boundaries collapsed; index too short")
    labels = np.array(["test"] * n, dtype=object)
    labels[:b1] = "train"
    labels[b1:b2] = "val"
    return labels


# ===================================================================================
# 5. Scaling and sequences
# ===================================================================================
def fit_scalers(df: pd.DataFrame):
    """Fit min-max scalers on VALID TRAINING rows only; val/test are only transformed."""
    train = df[(df["split"] == "train") & df["input_valid"]]
    feature_scaler = MinMaxScaler().fit(train[config.SCALED_FEATURES].to_numpy())
    target_scaler = MinMaxScaler().fit(train[[config.TARGET]].to_numpy())
    return feature_scaler, target_scaler


def scaled_feature_matrix(df: pd.DataFrame, feature_scaler: MinMaxScaler) -> np.ndarray:
    """Rows with NaN inputs are kept as NaN; they are invalid and never enter a sequence."""
    scaled = feature_scaler.transform(df[config.SCALED_FEATURES].to_numpy())
    return np.hstack([scaled, df[config.UNSCALED_FEATURES].to_numpy(dtype=float)]).astype(np.float32)


def make_sequences(features: np.ndarray, target: np.ndarray, input_valid: np.ndarray,
                   target_valid: np.ndarray, seq_len: int = config.SEQUENCE_LENGTH,
                   horizon: int = config.HORIZON):
    """
    Sliding windows over consecutive rows of ONE split:
        X[k] = features[i : i + seq_len]      y[k] = target[i + seq_len + horizon - 1]
    Kept only if all seq_len input rows are input-valid and the target row is target-valid.
    Returns X (n, seq_len, n_features), y (n, 1), target_row_positions (n,).
    """
    n_feat = features.shape[1]
    n_win = len(features) - seq_len - horizon + 1
    if n_win <= 0:
        return np.empty((0, seq_len, n_feat), np.float32), np.empty((0, 1), np.float32), np.empty(0, int)
    inputs_ok = np.lib.stride_tricks.sliding_window_view(input_valid, seq_len)[:n_win].all(axis=1)
    target_pos = np.arange(n_win) + seq_len + horizon - 1
    keep = inputs_ok & target_valid[target_pos]
    starts = np.nonzero(keep)[0]
    if len(starts) == 0:
        return np.empty((0, seq_len, n_feat), np.float32), np.empty((0, 1), np.float32), np.empty(0, int)
    X = np.stack([features[s:s + seq_len] for s in starts]).astype(np.float32)
    y = target[target_pos[keep]].reshape(-1, 1).astype(np.float32)
    return X, y, target_pos[keep]


def build_split_sequences(df: pd.DataFrame, feature_scaler, target_scaler) -> dict:
    out = {}
    for split in SPLITS:
        part = df[df["split"] == split]
        feats = scaled_feature_matrix(part, feature_scaler)
        tgt = target_scaler.transform(part[[config.TARGET]].to_numpy()).ravel()
        X, y, pos = make_sequences(feats, tgt, part["input_valid"].to_numpy(), part["target_valid"].to_numpy())
        if np.isnan(X).any() or np.isnan(y).any():
            raise AssertionError(f"NaN leaked into {split} sequences")
        out[split] = {
            "X": X, "y": y,
            "y_unscaled": part[config.TARGET].to_numpy()[pos].reshape(-1, 1).astype(np.float32),
            "target_timestamp_utc": part.index[pos].strftime("%Y-%m-%dT%H:%M:%SZ").to_numpy(dtype="U20"),
        }
    return out


# ===================================================================================
# 6. Orchestration
# ===================================================================================
def run(raw_path=config.RAW_SESSIONS) -> dict:
    raw = load_sessions(raw_path)
    parsed = parse_timestamps(raw)
    validation = validate_sessions(raw, parsed)
    clean, cleaning = clean_sessions(parsed)

    index = hourly_index()
    capacity = installed_capacity(clean, index)
    site, per_space, merges = site_hourly(clean, index, capacity)
    site = add_history_features(add_time_features(site))

    site["suspected_outage"] = np.isin(_local_dates(site.index).strftime("%Y-%m-%d"),
                                       suspected_outage_days(site)).astype(int)
    site["confirmed_invalid"] = confirmed_invalid_mask(site.index).astype(int)
    ok = site["confirmed_invalid"] == 0
    site["input_valid"] = ok & site[config.FEATURES].notna().all(axis=1)
    site["target_valid"] = ok & site[config.TARGET].notna()
    site["split"] = split_labels(site.index)

    feature_scaler, target_scaler = fit_scalers(site)
    sequences = build_split_sequences(site, feature_scaler, target_scaler)
    return {"validation": validation, "clean": clean, "cleaning": cleaning, "capacity": capacity,
            "merged_overlaps": merges, "site": site, "per_space": per_space,
            "feature_scaler": feature_scaler, "target_scaler": target_scaler, "sequences": sequences}


def _stats(s: pd.Series, digits=4) -> dict:
    return {"mean": round(float(s.mean()), digits), "median": round(float(s.median()), digits),
            "p95": round(float(s.quantile(0.95)), digits), "max": round(float(s.max()), digits)}


def summarise(r: dict) -> dict:
    site, clean = r["site"], r["clean"]
    lo, hi = window_bounds()
    win = clean[(clean["connectionTime"] >= lo) & (clean["connectionTime"] < hi)]
    local = site.index.tz_convert(config.LOCAL_TZ)
    lim = int(config.SENSITIVITY_EXCLUDE_OVER_HOURS)
    days = _local_dates(site.index)
    daily_arrivals = site["arrivals"].groupby(days).sum()
    hol = holiday_dates(days.min(), days.max())
    normal_weekdays = daily_arrivals[(daily_arrivals.index.dayofweek < 5) & ~daily_arrivals.index.isin(hol)]

    splits = {}
    for s in SPLITS:
        part = site[site["split"] == s]
        seq = r["sequences"][s]
        splits[s] = {
            "start_local": str(part.index[0].tz_convert(config.LOCAL_TZ)),
            "end_local": str(part.index[-1].tz_convert(config.LOCAL_TZ)),
            "hours": int(len(part)),
            "share_of_hours": round(len(part) / len(site), 4),
            "input_valid_hours": int(part["input_valid"].sum()),
            "X_shape": list(seq["X"].shape),
            "y_shape": list(seq["y"].shape),
            "first_target_local": str(pd.Timestamp(str(seq["target_timestamp_utc"][0])).tz_convert(config.LOCAL_TZ)) if len(seq["y"]) else None,
            "last_target_local": str(pd.Timestamp(str(seq["target_timestamp_utc"][-1])).tz_convert(config.LOCAL_TZ)) if len(seq["y"]) else None,
            "utilization": _stats(part["utilization"]),
            "holidays": [d.date().isoformat() for d in hol
                         if part.index[0].tz_convert(config.LOCAL_TZ).tz_localize(None).normalize() <= d
                         <= part.index[-1].tz_convert(config.LOCAL_TZ).tz_localize(None)],
        }
    by_hour = site["utilization"].groupby([site["is_weekend"], local.hour]).mean().unstack(0)
    lag_nan = int(site["utilization_lag_168"].isna().sum())
    first_input_valid = site.index[site["input_valid"].to_numpy()][0]
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "raw_file": str(config.RAW_SESSIONS.relative_to(config.ROOT)).replace("\\", "/"),
        "site": config.SITE,
        "validation_full_raw_file": r["validation"],
        "cleaning": r["cleaning"],
        "window_local": [config.ANALYSIS_START, config.ANALYSIS_END],
        "hours_in_window": int(len(site)),
        "sessions_starting_in_window": int(len(win)),
        "sessions_overlapping_window": int(len(overlapping_window(clean, site.index))),
        "long_sessions_in_window": {f"over_{int(h)}h": int(win[f"over_{int(h)}h"].sum())
                                    for h in config.LONG_SESSION_FLAG_HOURS},
        "duration_hours_in_window": _stats(win["duration_h"], 3),
        "capacity_mode": config.CAPACITY_MODE,
        "installed_capacity_spaces": r["capacity"],
        "overlapping_intervals_merged": r["merged_overlaps"],
        "occupied_spaces": _stats(site["occupied_spaces"]),
        "utilization": _stats(site["utilization"]),
        "peak_occupied_spaces_max": int(site["peak_occupied_spaces"].max()),
        "hours_peak_at_capacity": int((site["peak_occupied_spaces"] >= r["capacity"]).sum()),
        "hours_zero_occupancy": int((site["occupied_spaces"] == 0).sum()),
        "hours_utilization_over": {f"{p}pct": int((site["utilization"] > p / 100).sum()) for p in (40, 70, 90)},
        "max_utilization_hour_local": str(site["utilization"].idxmax().tz_convert(config.LOCAL_TZ)),
        "mean_utilization_by_local_hour": {
            "weekday": [round(float(v), 4) for v in by_hour[0].to_numpy()],
            "weekend": [round(float(v), 4) for v in by_hour[1].to_numpy()],
        },
        "sensitivity": {
            f"utilization_excl_over_{lim}h": _stats(site[f"utilization_excl_over_{lim}h"]),
            f"mean_abs_diff_vs_main_excl_over_{lim}h": round(float((site["utilization"] - site[f"utilization_excl_over_{lim}h"]).abs().mean()), 5),
            "utilization_active_month": _stats(site["utilization_active_month"]),
            "active_spaces_month_range": [int(site["active_spaces_month"].min()), int(site["active_spaces_month"].max())],
        },
        "holidays_in_window": [d.date().isoformat() for d in hol],
        "daily_sessions_normal_weekday": {"median": float(normal_weekdays.median()), "min": int(normal_weekdays.min())},
        "daily_sessions_on_holidays": {d.date().isoformat(): int(daily_arrivals.get(d, 0)) for d in hol},
        "suspected_outage_days": sorted(set(_local_dates(site.index[site["suspected_outage"] == 1]).strftime("%Y-%m-%d"))),
        "confirmed_invalid_periods": [list(p) for p in config.CONFIRMED_INVALID_PERIODS],
        "hours_without_lag_168": lag_nan,
        "first_input_valid_hour_local": str(first_input_valid.tz_convert(config.LOCAL_TZ)),
        "arrivals_per_hour_mean": round(float(site["arrivals"].mean()), 3),
        "energy_kwh_completed_in_window": round(float(site["energy_kwh_completed"].sum()), 1),
        "splits": splits,
        "features": config.FEATURES,
        "scaled_features": config.SCALED_FEATURES,
        "feature_scaler_train_min": dict(zip(config.SCALED_FEATURES, [round(float(v), 6) for v in r["feature_scaler"].data_min_])),
        "feature_scaler_train_max": dict(zip(config.SCALED_FEATURES, [round(float(v), 6) for v in r["feature_scaler"].data_max_])),
        "target_scaler_train_range": [round(float(r["target_scaler"].data_min_[0]), 6),
                                      round(float(r["target_scaler"].data_max_[0]), 6)],
    }


def feature_config(summary: dict) -> dict:
    return {
        "site": config.SITE,
        "interval": config.INTERVAL,
        "local_timezone": config.LOCAL_TZ,
        "sequence_length": config.SEQUENCE_LENGTH,
        "horizon": config.HORIZON,
        "target": config.TARGET,
        "target_definition": "time-weighted mean occupied spaces in the hour / installed capacity",
        "installed_capacity_spaces": summary["installed_capacity_spaces"],
        "capacity_mode": config.CAPACITY_MODE,
        "features": config.FEATURES,
        "scaled_features": config.SCALED_FEATURES,
        "unscaled_features": config.UNSCALED_FEATURES,
        "rolling_window": config.ROLLING_WINDOW,
        "weekly_lag": config.WEEKLY_LAG,
        "interval_convention": "half-open [connectionTime, disconnectTime)",
        "energy_attribution": "kWhDelivered assigned to the hour of disconnectTime",
        "holidays": {"federal_not_observed": list(config.FEDERAL_HOLIDAYS_NOT_OBSERVED),
                     "institute_closures": [list(c) for c in config.INSTITUTE_CLOSURES]},
        "analysis_window_local": [config.ANALYSIS_START, config.ANALYSIS_END],
        "split_ratios": list(config.SPLIT_RATIOS),
        "split_periods_local": {s: [v["start_local"], v["end_local"]] for s, v in summary["splits"].items()},
        "feature_scaler": config.FEATURE_SCALER_FILE.name,
        "target_scaler": config.TARGET_SCALER_FILE.name,
    }


HOURLY_COLUMNS = [
    "timestamp_local", "split", "input_valid", "target_valid", "suspected_outage", "confirmed_invalid",
    "capacity", "occupied_spaces", "utilization", "arrivals", "energy_kwh_completed",
    "utilization_lag_168", "utilization_roll_mean_24",
    "hour", "day_of_week", "month", "is_weekend", "is_holiday", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    # reporting / sensitivity only
    "peak_occupied_spaces", "occupied_spaces_excl_over_48h", "utilization_excl_over_48h",
    "active_spaces_month", "utilization_active_month",
]


def write_outputs(r: dict, summary: dict) -> None:
    for d in (config.PROCESSED_DIR, config.MODELS_DIR, config.DOCS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    r["site"][HOURLY_COLUMNS].to_csv(config.HOURLY_SITE_FILE)

    ps = r["per_space"].copy()
    ps["timestamp_utc"] = ps["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    ps.to_csv(config.HOURLY_SPACE_FILE, index=False, compression="gzip")

    lo, hi = window_bounds()
    c = r["clean"]
    flags = c[(c["disconnectTime"] > lo) & (c["connectionTime"] < hi)]
    flags = flags[["_id", "stationID", "connectionTime", "disconnectTime", "kWhDelivered", "duration_h",
                   "over_24h", "over_48h"]].assign(duration_h=lambda d: d["duration_h"].round(4))
    flags.to_csv(config.SESSION_FLAGS_FILE, index=False)

    for split, arrays in r["sequences"].items():
        np.savez_compressed(config.SEQUENCE_FILES[split], **arrays)
    joblib.dump(r["feature_scaler"], config.FEATURE_SCALER_FILE)
    joblib.dump(r["target_scaler"], config.TARGET_SCALER_FILE)
    config.FEATURE_CONFIG_FILE.write_text(json.dumps(feature_config(summary), indent=2), encoding="utf-8")
    config.REPORT_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log.info("Raw file: %s", config.RAW_SESSIONS)
    r = run()
    summary = summarise(r)
    write_outputs(r, summary)

    import report  # markdown report + figures
    report.write(summary, r["site"], r["clean"])
    log.info("capacity=%d  utilization mean=%.4f max=%.4f", summary["installed_capacity_spaces"],
             summary["utilization"]["mean"], summary["utilization"]["max"])
    for s, v in summary["splits"].items():
        log.info("%-5s %s -> %s  X=%s y=%s", s, v["start_local"][:16], v["end_local"][:16], v["X_shape"], v["y_shape"])


if __name__ == "__main__":
    main()
