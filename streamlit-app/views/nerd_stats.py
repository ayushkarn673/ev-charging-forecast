"""Under the hood: the LSTM forecast (historical replay), the pricing policy and the saved evaluation."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from evcharge import api, india
from evcharge.fmt import demand_badge, num, pct, wall_clock
from evcharge.ui import show_error

# The model's untouched test period. All of it is Pacific Standard Time (UTC-08:00).
TEST_FIRST, TEST_LAST = date(2019, 12, 20), date(2020, 2, 29)
PST = "-08:00"
PRESETS = [("Weekday 09:00", date(2020, 2, 5), 9), ("Weekday 13:00", date(2020, 2, 5), 13),
           ("Weekday 18:00", date(2020, 2, 5), 18), ("Saturday 13:00", date(2020, 2, 8), 13),
           ("Night 03:00", date(2020, 2, 6), 3)]
APPROACHES = [("lstm", "LSTM (this project)"), ("previousHour", "Baseline: previous hour"),
              ("sameHourLastWeek", "Baseline: same hour last week")]

ss = st.session_state


@st.cache_data(ttl=600, show_spinner=False)
def cached_evaluation() -> dict:
    return api.evaluation()


@st.cache_data(ttl=600, show_spinner=False)
def cached_series(start: str, end: str) -> dict:
    return api.evaluation_series(start, end)


st.title("Model insights")
st.caption("Demand forecasts, model accuracy and the pricing policy.")

# India is the primary model on this page. Its predictions are historical replays on simulated data and are never
# used for slot availability or prices; the Caltech model (used by the backend's pricing) stays available below.
MODELS = ["India", "Caltech (comparison)"]
if st.radio("Forecasting model", MODELS, horizontal=True, key="nerd_model") == MODELS[0]:
    india.render()
    st.stop()

# ---------------------------------------------------------------- service status
checks = [("Backend", api.health), ("MySQL", api.db_health), ("LSTM service", api.ml_status)]
for col, (label, call) in zip(st.columns(3), checks):
    try:
        call()
        col.markdown(f":green-badge[{label}: online]")
    except api.ApiError:
        col.markdown(f":red-badge[{label}: offline]")

st.info("**Historical replay of real charging data, not a live feed.** The LSTM was trained on ACN-Data "
        "sessions from the Caltech garage (54 charging spaces, Nov 2018 – Feb 2020). Each forecast below is produced "
        f"now by the trained model, using only observations that existed before the chosen time. Pick any hour in "
        f"the untouched test period ({TEST_FIRST} → {TEST_LAST}, Pacific time).")

# ---------------------------------------------------------------- forecast
ss.setdefault("nerd_day", date(2020, 2, 5))
ss.setdefault("nerd_hour", 10)


def use_preset(d: date, h: int) -> None:
    ss["nerd_day"], ss["nerd_hour"] = d, h


left, right = st.columns([3, 2], gap="large")
with left.container(border=True):
    st.markdown("#### Next-hour demand forecast")
    st.caption("LSTM · 24 hours of history in, 1 hour ahead out · historical replay, not live")
    c1, c2 = st.columns(2)
    day = c1.date_input("Forecast day (Pacific time)", min_value=TEST_FIRST, max_value=TEST_LAST, key="nerd_day")
    hour = c2.selectbox("Hour", list(range(24)), format_func=lambda h: f"{h:02d}:00", key="nerd_hour")
    for col, (label, d, h) in zip(st.columns(len(PRESETS)), PRESETS):
        col.button(label, key=f"preset-{label}", on_click=use_preset, args=(d, h), width="stretch")

    view = None
    try:
        with st.spinner("Loading forecast…"):
            view = api.forecast(f"{day.isoformat()}T{hour:02d}:00:00{PST}")
    except api.ApiError as err:
        show_error(err)
    if view:
        f, p = view["forecast"], view["forecast"]["prediction"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Predicted utilization", pct(p["utilization"]))
        m2.metric("Est. occupied spaces", f"{p['estimatedOccupiedSpacesRounded']} / {f['installedCapacitySpaces']}",
                  help=f"Hourly average {num(p['estimatedOccupiedSpaces'])}, rounded up")
        m3.metric("Est. available spaces", p["estimatedAvailableSpacesRounded"], help="Never overstated")
        m4.markdown("**Demand**  \n" + demand_badge(view["congestionLevel"]))
        observed = f.get("observedOutcome")
        details = {
            "Source": view["source"],
            "Mode": f["mode"] + (" (simulation)" if f["isSimulation"] else ""),
            "Target hour": f"{wall_clock(f['targetStart'])} – {wall_clock(f['targetEnd'], with_date=False)}",
            "Forecast made at": f"{wall_clock(f['forecastTime'])} ({f['forecastTimeUtc']})",
            "Horizon": f"{f['horizonHours']} hour",
            "Model": f["modelId"],
            "Recorded outcome": (f"{observed['utilizationPercent']}% (error "
                                 f"{num(p['utilizationPercent'] - observed['utilizationPercent'], 1)} pp)")
            if observed else "not in dataset",
        }
        st.table(pd.DataFrame({"": list(details.values())}, index=list(details.keys())))
        if observed:
            st.caption(observed["note"])
        for w in f.get("warnings") or []:
            st.warning(f"{w['message']} ({w['code']})")

with right.container(border=True):
    st.markdown("#### Demand-based pricing policy")
    st.caption("Price = station base price × band multiplier")
    if view:
        t, m = view["pricingPolicy"]["thresholds"], view["pricingPolicy"]["multipliers"]
        rows = [
            ("LOW", f"< {pct(t['medium'], 0)}", m["low"]),
            ("MEDIUM", f"{pct(t['medium'], 0)} – {pct(t['high'], 0)}", m["medium"]),
            ("HIGH", f"{pct(t['high'], 0)} – {pct(t['veryHigh'], 0)}", m["high"]),
            ("VERY_HIGH", f"≥ {pct(t['veryHigh'], 0)}", m["veryHigh"]),
        ]
        table = "| Band | Predicted utilization | Multiplier |\n|---|---|---:|\n"
        for level, rng, mult in rows:
            here = " (current forecast)" if level == view["congestionLevel"] else ""
            table += f"| {demand_badge(level)}{here} | {rng} | × {num(mult)} |\n"
        st.markdown(table)
    else:
        st.caption("Shown once a forecast loads.")
    st.caption("These thresholds and multipliers are an operator **policy** set in configuration. They are not "
               "learned by the LSTM. The model supplies the predicted utilization; the policy turns it into a price. "
               "Lower bounds are inclusive.")

# ---------------------------------------------------------------- evaluation
with st.container(border=True):
    st.markdown("#### Model performance on the untouched test set")
    try:
        e = cached_evaluation()
    except api.ApiError as err:
        show_error(err, retry_key="nerd-eval-retry")
        e = None
    if e:
        lstm = e["overall"]["lstm"]
        st.caption(f"{lstm['n']} hourly forecasts, {wall_clock(e['testPeriodLocal'][0], with_time=False)} – "
                   f"{wall_clock(e['testPeriodLocal'][1], with_time=False)} · pp = percentage points of utilization")
        k1, k2, k3 = st.columns(3)
        k1.metric("LSTM MAE", f"{num(lstm['maePp'])} pp", help=f"≈ {num(lstm['maeSpaces'])} of "
                  f"{e['installedCapacitySpaces']} spaces")
        k2.metric("LSTM RMSE", f"{num(lstm['rmsePp'])} pp", help=f"≈ {num(lstm['rmseSpaces'])} spaces")
        k3.metric("LSTM WAPE", f"{num(lstm['wapePercent'], 1)}%", help="Σ|error| ÷ Σ actual (a percentage error)")
        rows = []
        for key, label in APPROACHES:
            r = e["overall"][key]
            cmp = e["comparisons"].get(f"lstmVs{key[0].upper()}{key[1:]}") if key != "lstm" else None
            rows.append({
                "Approach": label,
                "MAE (pp)": round(r["maePp"], 3),
                "RMSE (pp)": round(r["rmsePp"], 3),
                "WAPE (%)": round(r["wapePercent"], 1),
                "LSTM vs this": (f"LSTM {num(cmp['maeReductionPercent'], 1)}% lower MAE "
                                 f"(95% CI of difference [{num(cmp['maeDifferenceCi95Pp'][0])}, "
                                 f"{num(cmp['maeDifferenceCi95Pp'][1])}] pp)") if cmp else "—",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        weekend = (e.get("bySubset") or {}).get("weekend") or {}
        if weekend:
            st.caption(f"From the same evaluation: on weekends the simple previous-hour baseline had a lower MAE than "
                       f"the LSTM ({num(weekend['previousHour']['maePp'])} vs {num(weekend['lstm']['maePp'])} pp). "
                       f"The test period never exceeded 70% utilization, so the HIGH and VERY_HIGH bands are untested "
                       f"on real data.")

with st.container(border=True):
    st.markdown("#### Actual vs predicted utilization (saved test-set results)")
    st.caption("One-hour-ahead predictions from the evaluation, on data the model never saw during training.")
    c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
    week = c1.date_input("Week starting", value=date(2020, 2, 3), min_value=TEST_FIRST,
                         max_value=TEST_LAST - timedelta(days=6), key="nerd_week")
    baseline = c2.checkbox("Show previous-hour baseline", key="nerd_baseline")
    try:
        with st.spinner("Loading saved results…"):
            series = cached_series(week.isoformat(), (week + timedelta(days=6)).isoformat())
    except api.ApiError as err:
        show_error(err)
        series = None
    if series and series.get("points"):
        df = pd.DataFrame(series["points"])
        df["time"] = pd.to_datetime(df["targetTime"].str.slice(0, 19))   # site wall-clock time
        cols = {"actual": "Actual (recorded)", "lstm": "LSTM prediction"}
        if baseline:
            cols["previousHour"] = "Previous-hour baseline"
        chart = df.set_index("time")[list(cols)].rename(columns=cols) * 100
        st.line_chart(chart, y_label="Utilization (%)", x_label="Pacific time")
        st.caption(series.get("source", ""))
    elif series is not None:
        st.caption("No data for this range.")
