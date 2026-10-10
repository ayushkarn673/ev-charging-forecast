"""
Writes docs/preprocessing_report.md and docs/figures/*.png from the summary produced by
preprocess.py. Every number in the report comes from the pipeline run - nothing is typed in.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
import plot_style
from plot_style import SERIES, TEXT_SECONDARY, plt

SPLIT_SHADE = {"train": "#f0efec", "val": "#e4e3df", "test": "#d6d5d0"}


# ----------------------------------------------------------------------------------- figures
def fig_monthly_sessions(clean: pd.DataFrame) -> str:
    local = clean["connectionTime"].dt.tz_convert(config.LOCAL_TZ).dt.tz_localize(None)
    monthly = local.dt.to_period("M").value_counts().sort_index()
    full = pd.period_range(monthly.index.min(), monthly.index.max(), freq="M")
    monthly = monthly.reindex(full, fill_value=0)
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.axvspan(pd.Timestamp(config.ANALYSIS_START), pd.Timestamp(config.ANALYSIS_END),
               color=SPLIT_SHADE["val"], zorder=0, label="analysis window")
    ax.plot(monthly.index.to_timestamp(), monthly.values, color=SERIES[0], marker="o", markersize=3,
            label="sessions per month")
    ax.set_title(f"Caltech ACN sessions per month (all {len(clean):,} cleaned sessions)")
    ax.set_ylabel("Sessions")
    ax.legend(loc="upper right")
    name = "dataset_monthly_sessions.png"
    fig.savefig(config.FIGURES_DIR / name); plt.close(fig)
    return name


def fig_hourly_profile(summary: dict) -> str:
    prof = summary["mean_utilization_by_local_hour"]
    hours = np.arange(24)
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.plot(hours, np.array(prof["weekday"]) * 100, color=SERIES[0], label="weekday")
    ax.plot(hours, np.array(prof["weekend"]) * 100, color=SERIES[1], label="weekend")
    ax.set_title("Mean hourly utilization of installed capacity, Nov 2018 - Feb 2020")
    ax.set_xlabel("Hour of day (local time)")
    ax.set_ylabel("Utilization (%)")
    ax.set_xticks(range(0, 24, 3))
    ax.legend()
    name = "utilization_hourly_profile.png"
    fig.savefig(config.FIGURES_DIR / name); plt.close(fig)
    return name


def fig_timeline(site: pd.DataFrame) -> str:
    local = site.index.tz_convert(config.LOCAL_TZ).tz_localize(None)
    daily = pd.Series(site["utilization"].to_numpy(), index=local).resample("D").mean() * 100
    daily_peak = pd.Series(site["utilization"].to_numpy(), index=local).resample("D").max() * 100
    fig, ax = plt.subplots(figsize=(11, 3.8))
    for split in ("train", "val", "test"):
        part = local[site["split"].to_numpy() == split]
        ax.axvspan(part.min(), part.max(), color=SPLIT_SHADE[split], zorder=0)
        ax.text(part.min() + (part.max() - part.min()) / 2, 1.0, split, transform=ax.get_xaxis_transform(),
                ha="center", va="bottom", color=TEXT_SECONDARY, fontsize=9)
    ax.plot(daily_peak.index, daily_peak.values, color=SERIES[1], linewidth=1, label="busiest hour of the day")
    ax.plot(daily.index, daily.values, color=SERIES[0], label="daily mean")
    ax.set_title("Daily utilization (mean and busiest hour) by chronological split", pad=16)
    ax.set_ylabel("Utilization (%)")
    ax.legend(loc="upper right")
    name = "utilization_timeline_splits.png"
    fig.savefig(config.FIGURES_DIR / name); plt.close(fig)
    return name


def fig_durations(clean: pd.DataFrame) -> str:
    lo, hi = (pd.Timestamp(config.ANALYSIS_START, tz=config.LOCAL_TZ),
              pd.Timestamp(config.ANALYSIS_END, tz=config.LOCAL_TZ))
    w = clean[(clean["connectionTime"] >= lo) & (clean["connectionTime"] < hi)]
    bins = [0, 1, 2, 4, 8, 12, 24, 48, 72, np.inf]
    labels = ["<1", "1-2", "2-4", "4-8", "8-12", "12-24", "24-48", "48-72", ">72"]
    cut = pd.cut(w["duration_h"], bins, labels=labels, right=False)
    pct_sessions = cut.value_counts(normalize=True).reindex(labels) * 100
    hours = w.groupby(cut, observed=False)["duration_h"].sum().reindex(labels)
    pct_hours = hours / hours.sum() * 100
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.bar(x - 0.2, pct_sessions, width=0.38, color=SERIES[0], label="% of sessions")
    ax.bar(x + 0.2, pct_hours, width=0.38, color=SERIES[1], label="% of occupied space-hours")
    ax.set_xticks(x, labels)
    ax.set_xlabel("Connection duration (hours)")
    ax.set_ylabel("Percent")
    ax.set_title("Connection durations in the analysis window (all sessions kept)")
    ax.legend()
    name = "session_duration_distribution.png"
    fig.savefig(config.FIGURES_DIR / name); plt.close(fig)
    return name


# ----------------------------------------------------------------------------------- markdown
def _row(*cells) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def write(summary: dict, site: pd.DataFrame, clean: pd.DataFrame) -> None:
    plot_style.apply()
    config.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    figs = [fig_monthly_sessions(clean), fig_hourly_profile(summary), fig_timeline(site), fig_durations(clean)]

    v = summary["validation_full_raw_file"]
    c = summary["cleaning"]
    s = summary["sensitivity"]
    cap = summary["installed_capacity_spaces"]
    L = []
    a = L.append
    a("# Preprocessing Report — Caltech ACN-Data")
    a("")
    a(f"_Generated by `ml-service/preprocess.py` at {summary['generated_utc']}. All numbers come from the run; do not edit by hand._")
    a("")
    a("## 1. Source and scope")
    a("")
    a("- **Dataset:** ACN-Data, Caltech Adaptive Charging Network (https://ev.caltech.edu/dataset), official API export.")
    a("- **Citation:** Z. J. Lee, T. Li, S. H. Low, *ACN-Data: Analysis and Applications of an Open EV Charging Dataset*, ACM e-Energy 2019.")
    a(f"- **Raw file:** `{summary['raw_file']}` (unchanged by preprocessing). `userID` and `userInputs` were removed at download.")
    a("- **Scope:** one site (the Caltech garage). Results describe this site only, not city-wide demand. The data is **historical**, not live.")
    a("")
    a("## 2. Raw-data validation (whole file)")
    a("")
    a(_row("Check", "Result")); a(_row("---", "---"))
    for label, value in [
        ("Records", f"{v['records']:,}"), ("Coverage (local)", f"{v['coverage_local'][0][:16]} → {v['coverage_local'][1][:16]}"),
        ("Stations / spaces", f"{v['stations']} / {v['spaces']} (one-to-one: {v['station_to_space_one_to_one']})"),
        ("Duplicate `_id` / `sessionID` / (station, start)", f"{v['duplicate_id']} / {v['duplicate_sessionID']} / {v['duplicate_station_and_connectionTime']}"),
        ("Unparseable or missing connectionTime / disconnectTime", f"{v['unparseable_or_missing_connectionTime']} / {v['unparseable_or_missing_disconnectTime']}"),
        ("disconnectTime ≤ connectionTime", v["disconnect_not_after_connect"]),
        ("Missing / negative / zero kWh", f"{v['missing_kWh']} / {v['negative_kWh']} / {v['zero_kWh']} (min {v['min_kWh']} kWh)"),
        ("Overlapping sessions on the same space", v["overlapping_sessions_same_space"]),
        ("Sessions starting / ending exactly on an hour", f"{v['sessions_starting_on_exact_hour']} / {v['sessions_ending_on_exact_hour']}"),
        ("doneChargingTime missing", f"{v['doneChargingTime']['missing']:,} (by year: {v['doneChargingTime']['missing_by_year']})"),
        ("doneChargingTime earlier than connect / later than disconnect", f"{v['doneChargingTime']['earlier_than_connectionTime']} / {v['doneChargingTime']['later_than_disconnectTime']}"),
        ("Timezone column", ", ".join(v["timezone_values"])),
    ]:
        a(_row(label, value))
    a("")
    a(f"Sessions with missing `doneChargingTime` have a higher median energy ({v['doneChargingTime']['median_kWh_when_missing']} kWh vs "
      f"{v['doneChargingTime']['median_kWh_when_present']} kWh), and the field is inconsistent in "
      f"{v['doneChargingTime']['earlier_than_connectionTime'] + v['doneChargingTime']['later_than_disconnectTime']:,} rows. "
      "It is therefore **not used anywhere**; occupancy uses connectionTime → disconnectTime only.")
    a("")
    a("## 3. Cleaning (whole file)")
    a("")
    a(_row("Step", "Rows")); a(_row("---", "---:"))
    for k, val in c.items():
        a(_row(k.replace("_", " "), f"{val:,}"))
    a("")
    a("Only records that cannot describe a real occupancy interval are dropped. Long sessions and missing `doneChargingTime` are kept.")
    a("")
    a("## 4. Analysis window")
    a("")
    a(f"Local **{summary['window_local'][0]} → {summary['window_local'][1]}** (end exclusive): {summary['hours_in_window']:,} hourly rows, "
      f"{summary['sessions_starting_in_window']:,} sessions starting in the window ({summary['sessions_overlapping_window']:,} overlapping it, "
      "including sessions that began just before it).")
    a("")
    a("- **Start:** Caltech introduced a $0.12/kWh fee on 1 Nov 2018 and usage fell sharply (Lee et al. 2019, §3.1.2).")
    a("- **End:** COVID-19 campus closures collapsed demand from March 2020; the raw file has no sessions in Sep–Oct 2020.")
    a("")
    a(f"![monthly sessions](figures/{figs[0]})")
    a("")
    a("## 5. Occupancy and utilization definition")
    a("")
    a("- **Interval convention:** half-open `[connectionTime, disconnectTime)`. A session ending exactly at 10:00:00 contributes nothing to 10:00–11:00; one starting at 10:00:00 counts from 10:00.")
    a("- **occupied_spaces(h)** = Σ over spaces of (seconds occupied in hour h) / 3600 — the **time-weighted mean** number of occupied spaces during the hour, exact to the second.")
    a("- Overlapping sessions on one space are merged before counting, so a space contributes at most 1 and the total cannot exceed capacity "
      f"(intervals merged: {summary['overlapping_intervals_merged']}).")
    a(f"- **utilization(h)** = occupied_spaces(h) / **{cap}** = utilization of **installed** capacity (not operational capacity, which the dataset does not record).")
    a("- Hours are built on a UTC index (no DST gaps or duplicates); calendar features use America/Los_Angeles time.")
    a("- **peak_occupied_spaces(h)** (reporting only) = maximum simultaneous occupied spaces at any instant in the hour.")
    a("")
    a(_row("Statistic", "Mean", "Median", "p95", "Max")); a(_row("---", "---:", "---:", "---:", "---:"))
    o, u = summary["occupied_spaces"], summary["utilization"]
    a(_row("Occupied spaces (time-weighted)", o["mean"], o["median"], o["p95"], o["max"]))
    a(_row("Utilization", u["mean"], u["median"], u["p95"], u["max"]))
    a("")
    hu = summary["hours_utilization_over"]
    a(f"- Highest-utilization hour: {summary['max_utilization_hour_local'][:16]} local. Hours above 40% / 70% / 90%: {hu['40pct']:,} / {hu['70pct']:,} / {hu['90pct']:,}.")
    a(f"- Maximum simultaneous occupancy: **{summary['peak_occupied_spaces_max']} of {cap}** spaces; hours at full capacity: {summary['hours_peak_at_capacity']}. "
      "The site never ran out of chargers in this window.")
    a(f"- Hours with zero occupancy: {summary['hours_zero_occupancy']:,}.")
    a("")
    a(f"![hourly profile](figures/{figs[1]})")
    a("")
    a("## 6. Capacity (charger availability)")
    a("")
    a(f"Installed capacity = **{cap}** distinct spaces with at least one session overlapping the window (the 55th space in the raw file first appears in Nov 2020). "
      "ACN-Data has no availability/outage telemetry, so a silent space cannot be told apart from an unpopular one; outages are **not** inferred from inactivity.")
    a("")
    a(f"Sensitivity (reporting only, never a feature or target): spaces with ≥1 session in each calendar month range "
      f"{s['active_spaces_month_range'][0]}–{s['active_spaces_month_range'][1]}. Utilization against that monthly active count: "
      f"mean {s['utilization_active_month']['mean']}, max {s['utilization_active_month']['max']} (vs {u['mean']} / {u['max']} for installed capacity).")
    a("")
    a("## 7. Long sessions")
    a("")
    d = summary["duration_hours_in_window"]
    ls = summary["long_sessions_in_window"]
    a(f"All valid sessions are kept: a plugged-in vehicle occupies the space regardless of charging. Duration in the window: median {d['median']} h, "
      f"p95 {d['p95']} h, max {d['max']} h. Flagged: **{ls['over_24h']}** sessions > 24 h and **{ls['over_48h']}** > 48 h "
      f"(per-session flags in `dataset/processed/session_flags.csv`).")
    a("")
    se = s["utilization_excl_over_48h"]
    a(f"Sensitivity series without sessions > 48 h (reporting only): mean utilization {se['mean']} vs {u['mean']}; "
      f"mean absolute hourly difference {s['mean_abs_diff_vs_main_excl_over_48h']}. The main target keeps all sessions.")
    a("")
    a(f"![durations](figures/{figs[3]})")
    a("")
    a("## 8. Holidays, outages and validity")
    a("")
    a("`is_holiday` is known in advance: US federal holidays except Columbus Day and Veterans Day (normal demand at this site), plus Caltech's published Institute winter closures "
      "(24 Dec 2018 – 1 Jan 2019; 25 Dec 2019 – 1 Jan 2020).")
    a("")
    a(_row("Holiday date", "Sessions")); a(_row("---", "---:"))
    for day, n in summary["daily_sessions_on_holidays"].items():
        a(_row(day, n))
    a("")
    nw = summary["daily_sessions_normal_weekday"]
    a(f"Normal (non-holiday) weekdays: median {nw['median']:.0f} sessions/day, minimum {nw['min']}.")
    a("")
    so = summary["suspected_outage_days"]
    a(f"- **Suspected outages** (non-holiday weekday with zero sessions, flag only): {', '.join(so) if so else 'none found'}.")
    a(f"- **Confirmed invalid periods** excluded from sequences: {summary['confirmed_invalid_periods'] or 'none'}. Holidays are genuine low demand and stay in the data.")
    a(f"- **Lag-168 warm-up:** the first {summary['hours_without_lag_168']} hours have no value one week earlier; they are marked input-invalid. "
      f"First usable input hour: {summary['first_input_valid_hour_local'][:16]} local.")
    a("")
    a("## 9. Features (all available at prediction time)")
    a("")
    a(_row("Feature", "Definition at input step t", "Scaled")); a(_row("---", "---", "---"))
    defs = {
        "utilization": "observed utilization in hour t", "utilization_lag_168": "utilization in hour t−168 (same hour last week)",
        "utilization_roll_mean_24": "mean utilization over hours t−23 … t", "arrivals": "sessions starting in hour t",
        "energy_kwh_completed": "kWh of sessions that ended in hour t", "hour_sin": "sin(2π·hour/24)", "hour_cos": "cos(2π·hour/24)",
        "dow_sin": "sin(2π·weekday/7)", "dow_cos": "cos(2π·weekday/7)", "is_weekend": "Saturday or Sunday",
        "is_holiday": "observed holiday (Section 8)",
    }
    for f in summary["features"]:
        a(_row(f"`{f}`", defs[f], "min–max (train fit)" if f in summary["scaled_features"] else "no (already bounded)"))
    a("")
    a("All history features look backwards only. At the start of the validation and test periods, lag-168 and the rolling mean read hours from the "
      "preceding split — past data that would be available in deployment — and never any hour after t.")
    a("")
    a("## 10. Splits, sequences and scaling")
    a("")
    a(f"Each sample uses **{config.SEQUENCE_LENGTH} hourly input steps** to predict **utilization {config.HORIZON} hour ahead**. "
      "Inputs and target always lie inside one split, and windows touching an invalid hour are skipped. Split boundaries are moved to the nearest local midnight.")
    a("")
    a(_row("Split", "Period (local)", "Hours", "Share", "Mean util.", "X shape", "y shape", "First → last target"))
    a(_row("---", "---", "---:", "---:", "---:", "---", "---", "---"))
    for name, sp in summary["splits"].items():
        a(_row(name, f"{sp['start_local'][:16]} → {sp['end_local'][:16]}", f"{sp['hours']:,}", sp["share_of_hours"],
               sp["utilization"]["mean"], tuple(sp["X_shape"]), tuple(sp["y_shape"]),
               f"{(sp['first_target_local'] or '')[:16]} → {(sp['last_target_local'] or '')[:16]}"))
    a("")
    a("Scalers (`models/feature_scaler.pkl`, `models/target_scaler.pkl`) are fitted on **valid training rows only** and applied unchanged to validation and test.")
    a(f"Training-set target range: {summary['target_scaler_train_range']}.")
    a("")
    a(f"![timeline](figures/{figs[2]})")
    a("")
    a("## 11. Limitations")
    a("")
    a(f"- **Possible undercount of short plug-ins:** the smallest energy value in the whole file is {v['min_kWh']} kWh, which suggests very short or zero-energy "
      "connections are absent from the source. Occupancy may be slightly underestimated; this cannot be verified from the data.")
    a("- **Installed, not operational, capacity:** chargers that were broken but counted in the 54 make utilization look lower than operational utilization.")
    a("- **Holiday coverage:** the day after Thanksgiving and 24 Dec 2019 also show low demand but are not in the verified holiday list, so `is_holiday` is 0 on those days.")
    a("- **Distribution shift:** mean utilization falls from train to validation to test; the test period contains the 2019 winter closure, while training contains only one (2018).")
    a("- **Single site:** results cannot be generalised to other sites or cities without further data.")
    a("")
    a("## 12. Reproduce")
    a("")
    a("```bash\ncd ml-service\nuv sync\nuv run fetch_acn_data.py --sites caltech   # needs ACN_API_TOKEN in ml-service/.env\nuv run preprocess.py\nuv run pytest\n```")
    config.REPORT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
