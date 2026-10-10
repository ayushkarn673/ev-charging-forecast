"""
Unit tests for preprocess.py. Inputs are small hand-made session tables so every expected
value can be checked by hand. Times are UTC; Jan 2019 local (PST) = UTC - 8 h.
"""
import numpy as np
import pandas as pd
import pytest

import config
import preprocess as pp

COLS = ["_id", "sessionID", "siteID", "stationID", "spaceID", "connectionTime", "disconnectTime",
        "doneChargingTime", "kWhDelivered", "timezone"]


def raw(rows):
    return pd.DataFrame(rows, columns=COLS)   # None = missing value


def row(i, start, end, station="S1", kwh="5.0", done=None):
    return [str(i), f"s{i}", "2", station, f"SP-{station}", start, end, done, kwh, config.LOCAL_TZ]


def sessions(rows):
    clean, _ = pp.clean_sessions(pp.parse_timestamps(raw(rows)))
    return clean


def local_index(start, end):
    return pp.hourly_index(start, end)


# ---------------------------------------------------------------- timestamp parsing
def test_parses_iso_offsets_to_utc():
    p = pp.parse_timestamps(raw([row(1, "2019-01-07T08:00:00-08:00", "2019-01-07T17:30:00+00:00")]))
    assert p["connectionTime"].iloc[0] == pd.Timestamp("2019-01-07T16:00:00Z")
    assert str(p["connectionTime"].dt.tz) == "UTC"


def test_unparseable_timestamps_become_nat_and_are_dropped_with_a_count():
    p = pp.parse_timestamps(raw([row(1, "not-a-date", "2019-01-07T18:00:00+00:00")]))
    assert p["connectionTime"].isna().all()
    clean, stats = pp.clean_sessions(p)
    assert clean.empty and stats["dropped_missing_or_unparseable_connectionTime"] == 1


def test_hourly_index_is_utc_and_handles_dst_days():
    spring = local_index("2019-03-10", "2019-03-11")   # 23 local hours
    autumn = local_index("2019-11-03", "2019-11-04")   # 25 local hours
    assert len(spring) == 23 and len(autumn) == 25
    assert spring.is_unique and autumn.is_unique and str(spring.tz) == "UTC"


def test_calendar_features_use_local_time():
    f = pp.add_time_features(pd.DataFrame(index=local_index("2019-01-07", "2019-01-08")))
    assert f["hour"].tolist() == list(range(24))           # local 00..23, not UTC
    assert (f["day_of_week"] == 0).all() and (f["is_weekend"] == 0).all()
    assert np.isclose(f.loc[f["hour"] == 6, "hour_sin"].iloc[0], 1.0)


# ---------------------------------------------------------------- missing / invalid values
def test_missing_disconnect_and_bad_intervals_dropped_and_counted():
    df = raw([
        row(1, "2019-01-07T16:00:00+00:00", "2019-01-07T18:00:00+00:00"),
        row(2, "2019-01-07T16:00:00+00:00", None, station="S2"),
        row(3, "2019-01-07T18:00:00+00:00", "2019-01-07T16:00:00+00:00", station="S3"),
        row(4, "2019-01-07T16:00:00+00:00", "2019-01-07T17:00:00+00:00", station="S4", kwh="-1"),
        row(5, "2019-01-07T16:00:00+00:00", "2019-01-07T17:00:00+00:00", station="S5", kwh="abc"),
    ])
    clean, stats = pp.clean_sessions(pp.parse_timestamps(df))
    assert clean["_id"].tolist() == ["1"]
    assert stats["dropped_missing_or_unparseable_disconnectTime"] == 1
    assert stats["dropped_disconnect_not_after_connect"] == 1
    assert stats["dropped_missing_or_negative_kWh"] == 2
    assert stats["output_rows"] == 1


def test_missing_doneChargingTime_is_kept_and_not_used():
    s = sessions([row(1, "2019-01-07T16:00:00+00:00", "2019-01-07T18:00:00+00:00", done=None)])
    assert len(s) == 1
    with_done = sessions([row(1, "2019-01-07T16:00:00+00:00", "2019-01-07T18:00:00+00:00",
                              done="2019-01-07T16:15:00+00:00")])
    idx = local_index("2019-01-07 08:00", "2019-01-07 10:00")
    a, *_ = pp.occupied_spaces(s, idx)
    b, *_ = pp.occupied_spaces(with_done, idx)
    assert a.tolist() == b.tolist() == [1.0, 1.0]    # occupancy ignores doneChargingTime


def test_duplicates_removed():
    s = sessions([
        row(1, "2019-01-07T16:00:00+00:00", "2019-01-07T18:00:00+00:00"),
        row(1, "2019-01-07T16:00:00+00:00", "2019-01-07T18:00:00+00:00"),
        row(2, "2019-01-07T16:00:00+00:00", "2019-01-07T19:00:00+00:00"),   # same space + start
    ])
    assert s["_id"].tolist() == ["1"]


def test_load_rejects_missing_columns(tmp_path):
    p = tmp_path / "bad.csv"
    pd.DataFrame({"_id": ["1"], "connectionTime": ["x"]}).to_csv(p, index=False)
    with pytest.raises(ValueError, match="missing required columns"):
        pp.load_sessions(p)


# ---------------------------------------------------------------- occupancy + hour boundaries
IDX_3H = ("2019-01-07 08:00", "2019-01-07 11:00")   # local 08-11 = UTC 16-19


def test_time_weighted_occupancy_exact_fractions():
    s = sessions([
        row(1, "2019-01-07T16:00:00+00:00", "2019-01-07T16:30:00+00:00", station="A"),   # 0.5 h
        row(2, "2019-01-07T16:45:00+00:00", "2019-01-07T18:15:00+00:00", station="B"),   # spans 3 h
    ])
    occ, *_ = pp.occupied_spaces(s, local_index(*IDX_3H))
    assert np.allclose(occ.to_numpy(), [0.5 + 0.25, 1.0, 0.25])


def test_session_ending_exactly_on_the_hour_does_not_occupy_next_hour():
    s = sessions([row(1, "2019-01-07T16:20:00+00:00", "2019-01-07T17:00:00+00:00")])
    occ, per_space, *_ = pp.occupied_spaces(s, local_index(*IDX_3H))
    assert np.allclose(occ.to_numpy(), [40 / 60, 0.0, 0.0])
    assert len(per_space) == 1                       # no zero-length entry for 17:00


def test_session_starting_exactly_on_the_hour_counts_from_that_hour():
    s = sessions([row(1, "2019-01-07T17:00:00+00:00", "2019-01-07T17:30:00+00:00")])
    occ, *_ = pp.occupied_spaces(s, local_index(*IDX_3H))
    assert np.allclose(occ.to_numpy(), [0.0, 0.5, 0.0])


def test_session_started_before_window_counts_inside_it():
    s = sessions([row(1, "2019-01-07T14:00:00+00:00", "2019-01-07T16:30:00+00:00")])
    occ, *_ = pp.occupied_spaces(s, local_index(*IDX_3H))
    assert np.allclose(occ.to_numpy(), [0.5, 0.0, 0.0])
    assert pp.installed_capacity(s, local_index(*IDX_3H)) == 1


def test_peak_concurrency_is_max_simultaneous():
    s = sessions([
        row(1, "2019-01-07T16:00:00+00:00", "2019-01-07T16:20:00+00:00", station="A"),
        row(2, "2019-01-07T16:20:00+00:00", "2019-01-07T16:40:00+00:00", station="B"),  # back-to-back
        row(3, "2019-01-07T16:30:00+00:00", "2019-01-07T17:30:00+00:00", station="C"),
    ])
    iv, _ = pp.merge_space_intervals(s)
    peak = pp.peak_concurrency(iv, local_index(*IDX_3H))
    assert peak.tolist() == [2, 1, 0]   # A ends exactly when B starts -> never 3 at once


# ---------------------------------------------------------------- capacity constraints
def test_overlapping_sessions_on_one_space_are_merged_not_double_counted():
    s = sessions([
        row(1, "2019-01-07T16:00:00+00:00", "2019-01-07T17:30:00+00:00"),
        row(2, "2019-01-07T16:30:00+00:00", "2019-01-07T18:00:00+00:00"),   # same space, overlaps
    ])
    occ, per_space, _, merges = pp.occupied_spaces(s, local_index(*IDX_3H))
    assert merges == 1
    assert occ.max() <= 1.0 and per_space["occupied_fraction"].max() <= 1.0
    assert np.allclose(occ.to_numpy(), [1.0, 1.0, 0.0])


def test_site_utilization_never_exceeds_capacity():
    rows = [row(i, "2019-01-07T16:00:00+00:00", "2019-01-07T19:00:00+00:00", station=f"S{i}") for i in range(5)]
    s = sessions(rows)
    idx = local_index(*IDX_3H)
    df, *_ = pp.site_hourly(s, idx, capacity=5)
    assert (df["utilization"] == 1.0).all() and (df["occupied_spaces"] <= 5).all()


def test_capacity_violation_raises():
    rows = [row(i, "2019-01-07T16:00:00+00:00", "2019-01-07T19:00:00+00:00", station=f"S{i}") for i in range(3)]
    with pytest.raises(AssertionError, match="exceeds installed capacity"):
        pp.site_hourly(sessions(rows), local_index(*IDX_3H), capacity=2)


# ---------------------------------------------------------------- long sessions
def test_long_sessions_kept_flagged_and_only_excluded_in_sensitivity_series():
    s = sessions([
        row(1, "2019-01-05T16:00:00+00:00", "2019-01-07T17:00:00+00:00", station="A"),   # 49 h
        row(2, "2019-01-07T16:00:00+00:00", "2019-01-07T17:00:00+00:00", station="B"),   # 1 h
    ])
    assert len(s) == 2
    assert s.set_index("_id").loc["1", "over_24h"] and s.set_index("_id").loc["1", "over_48h"]
    assert not s.set_index("_id").loc["2", "over_24h"]
    df, *_ = pp.site_hourly(s, local_index(*IDX_3H), capacity=2)
    assert df["occupied_spaces"].iloc[0] == 2.0                       # main target keeps it
    assert df["occupied_spaces_excl_over_48h"].iloc[0] == 1.0          # sensitivity drops it


# ---------------------------------------------------------------- energy attribution
def test_energy_counted_in_hour_session_ends():
    s = sessions([row(1, "2019-01-07T16:10:00+00:00", "2019-01-07T18:20:00+00:00", kwh="7.5")])
    df, *_ = pp.site_hourly(s, local_index(*IDX_3H), capacity=1)
    assert df["energy_kwh_completed"].tolist() == [0.0, 0.0, 7.5]
    assert df["arrivals"].tolist() == [1, 0, 0]


# ---------------------------------------------------------------- holidays / outages
def test_holidays_exclude_working_federal_days_and_include_closures():
    h = set(pp.holiday_dates(pd.Timestamp("2018-11-01"), pd.Timestamp("2020-02-29")).date)
    assert pd.Timestamp("2018-11-12").date() not in h      # Veterans Day: normal demand at site
    assert pd.Timestamp("2019-10-14").date() not in h      # Columbus Day
    assert pd.Timestamp("2019-11-28").date() in h          # Thanksgiving
    assert pd.Timestamp("2018-12-27").date() in h          # Institute winter closure
    assert pd.Timestamp("2019-12-24").date() not in h      # 2019 closure starts on the 25th


def test_suspected_outage_is_flagged_not_excluded():
    idx = local_index("2019-01-07", "2019-01-09")            # Mon, Tue
    df = pd.DataFrame({"arrivals": 0}, index=idx)
    df.iloc[30, 0] = 3                                       # activity on Tuesday only
    assert pp.suspected_outage_days(df) == ["2019-01-07"]
    assert not pp.confirmed_invalid_mask(idx).any()          # nothing confirmed -> nothing excluded


def test_confirmed_invalid_period_masks_only_its_hours():
    idx = local_index("2019-01-07", "2019-01-08")
    mask = pp.confirmed_invalid_mask(idx, periods=(("2019-01-07 10:00", "2019-01-07 12:00", "test"),))
    assert mask.sum() == 2 and mask[10] and mask[11]


# ---------------------------------------------------------------- lag-168 and rolling leakage
def _series(n):
    idx = local_index("2019-01-07", "2019-02-07")[:n]
    return pd.DataFrame({"utilization": np.arange(n, dtype=float)}, index=idx)


def test_lag_168_is_exact_and_nan_without_history():
    f = pp.add_history_features(_series(200))
    assert f["utilization_lag_168"].iloc[:168].isna().all()
    assert (f["utilization_lag_168"].iloc[168:] == np.arange(32)).all()


def test_rolling_mean_is_trailing_and_inclusive_of_t():
    f = pp.add_history_features(_series(30))
    assert f["utilization_roll_mean_24"].iloc[:23].isna().all()
    assert f["utilization_roll_mean_24"].iloc[23] == np.mean(np.arange(24))
    assert f["utilization_roll_mean_24"].iloc[29] == np.mean(np.arange(6, 30))


@pytest.mark.parametrize("t", [170, 185, 199])
def test_history_features_never_use_future_values(t):
    base = _series(250)
    changed = base.copy()
    changed.iloc[t + 1:, 0] = 999.0                          # tamper with everything after t
    a, b = pp.add_history_features(base), pp.add_history_features(changed)
    cols = ["utilization_lag_168", "utilization_roll_mean_24"]
    pd.testing.assert_frame_equal(a[cols].iloc[:t + 1], b[cols].iloc[:t + 1])


# ---------------------------------------------------------------- chronological splits
def test_split_is_ordered_contiguous_and_on_local_midnights():
    idx = local_index("2019-01-01", "2019-04-01")
    labels = pp.split_labels(idx)
    order = {"train": 0, "val": 1, "test": 2}
    codes = np.array([order[x] for x in labels])
    assert (np.diff(codes) >= 0).all()                       # train -> val -> test, never back
    local = idx.tz_convert(config.LOCAL_TZ)
    for boundary in np.nonzero(np.diff(codes))[0] + 1:
        assert local[boundary].hour == 0
    shares = pd.Series(labels).value_counts(normalize=True)
    assert abs(shares["train"] - 0.70) < 0.02 and abs(shares["val"] - 0.15) < 0.02


def test_split_rejects_bad_ratios():
    with pytest.raises(ValueError):
        pp.split_labels(local_index("2019-01-01", "2019-02-01"), ratios=(0.5, 0.2, 0.2))


# ---------------------------------------------------------------- scaler leakage
def _feature_frame(n=100):
    idx = local_index("2019-01-07", "2019-01-20")[:n]
    rng = np.random.default_rng(0)
    df = pd.DataFrame({c: rng.random(n) for c in config.SCALED_FEATURES}, index=idx)
    for c in config.UNSCALED_FEATURES:
        df[c] = 0.0
    n_train, n_val = int(n * 0.7), int(n * 0.15)
    df["split"] = ["train"] * n_train + ["val"] * n_val + ["test"] * (n - n_train - n_val)
    df["input_valid"] = True
    df["target_valid"] = True
    return df


def test_scalers_fit_on_training_rows_only():
    df = _feature_frame()
    fs, ts = pp.fit_scalers(df)
    train = df[df["split"] == "train"]
    assert np.allclose(fs.data_min_, train[config.SCALED_FEATURES].min())
    assert np.allclose(fs.data_max_, train[config.SCALED_FEATURES].max())
    tampered = df.copy()
    tampered.loc[tampered["split"] != "train", config.SCALED_FEATURES] = 1e6   # extreme val/test
    fs2, ts2 = pp.fit_scalers(tampered)
    assert np.allclose(fs.data_max_, fs2.data_max_) and np.allclose(ts.data_max_, ts2.data_max_)


def test_scalers_ignore_invalid_training_rows():
    df = _feature_frame()
    df.loc[df.index[0], "utilization"] = 50.0
    df.loc[df.index[0], "input_valid"] = False
    fs, _ = pp.fit_scalers(df)
    assert fs.data_max_[0] < 1.0


# ---------------------------------------------------------------- sequences
def test_sequence_shapes_and_target_alignment():
    n, f = 40, 3
    feats = np.arange(n * f, dtype=np.float32).reshape(n, f)
    target = np.arange(n, dtype=np.float32) / 100
    ok = np.ones(n, bool)
    X, y, pos = pp.make_sequences(feats, target, ok, ok, seq_len=24, horizon=1)
    assert X.shape == (16, 24, 3) and y.shape == (16, 1)
    assert np.array_equal(X[0], feats[0:24]) and y[0, 0] == target[24]
    assert pos[-1] == n - 1


def test_sequences_skip_windows_touching_invalid_rows():
    n = 40
    feats = np.zeros((n, 2), np.float32)
    target = np.zeros(n, np.float32)
    input_ok = np.ones(n, bool)
    input_ok[30] = False                       # invalid input hour
    target_ok = np.ones(n, bool)
    target_ok[25] = False                      # invalid target hour
    _, _, pos = pp.make_sequences(feats, target, input_ok, target_ok, seq_len=24, horizon=1)
    for p in pos:
        assert 30 not in range(p - 24, p)      # no window uses row 30 as input
        assert p != 25
    assert set(pos) == {24, 26, 27, 28, 29, 30}   # windows starting at 0,2..6; later ones contain row 30


def test_too_short_split_gives_empty_sequences():
    X, y, pos = pp.make_sequences(np.zeros((10, 4), np.float32), np.zeros(10), np.ones(10, bool),
                                  np.ones(10, bool), seq_len=24)
    assert X.shape == (0, 24, 4) and y.shape == (0, 1) and len(pos) == 0


def test_sequences_do_not_cross_split_boundaries():
    df = _feature_frame(120)
    df["split"] = ["train"] * 84 + ["val"] * 18 + ["test"] * 18
    fs, ts = pp.fit_scalers(df)
    seqs = pp.build_split_sequences(df, fs, ts)
    for split, n_rows in [("train", 84), ("val", 18), ("test", 18)]:
        assert seqs[split]["X"].shape[0] == max(n_rows - config.SEQUENCE_LENGTH, 0)
        part_times = set(df[df["split"] == split].index.strftime("%Y-%m-%dT%H:%M:%SZ"))
        assert set(seqs[split]["target_timestamp_utc"]) <= part_times
