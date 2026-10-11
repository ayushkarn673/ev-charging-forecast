"""
Experimental India city demand dashboard (standalone; separate from the booking app).

Shows historical-replay predictions made by the experimental LSTM (model/india_synthetic_lstm.keras)
on SIMULATED data. The predictions are produced by replay_predict.py, which loads the model and
scalers in the ml-service environment (the Streamlit environment has no TensorFlow). This page
checks that the model, scalers and data still match the recorded hashes before showing anything.
Not connected to bookings, pricing or the production ML API.

Run from the repo root (uses the existing streamlit-app environment; installs nothing):
    streamlit-app/.venv/Scripts/python.exe -B -m streamlit run experiments/india_ev_lstm/dashboard.py \
        --server.port 8502 --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
"""
from datetime import time as Time

import pandas as pd
import streamlit as st

import dashboard_core as core

st.set_page_config(page_title="India EV demand (experimental)", page_icon=":material/science:", layout="wide")

st.title("India city demand: experimental")
st.warning(core.BANNER, icon=":material/science:")
st.caption("Historical replay: each prediction uses only the 24 hours before it in the simulated dataset. "
           "It is not a live forecast. The booking app and its pricing keep using the production Caltech model; "
           "this page is not connected to them.")


@st.cache_data(show_spinner=False)
def check_integrity() -> list[str]:
    return core.integrity_problems()


@st.cache_data(show_spinner=False)
def history() -> pd.DataFrame:
    return core.load_history()


@st.cache_data(show_spinner=False)
def replay() -> pd.DataFrame:
    return core.load_replay()


if not core.MANIFEST.exists() or not core.REPLAY.exists():
    st.error("No replay predictions found. Run replay_predict.py first (see README.md).")
    st.stop()
problems = check_integrity()
if problems:
    st.error("The model, scalers or data no longer match the saved predictions, so nothing is shown:\n\n- "
             + "\n- ".join(problems) + "\n\nRe-run replay_predict.py.")
    st.stop()

hist, rep = history(), replay()
missing = [c for c in core.CITIES if c not in set(hist.city) or c not in set(rep.city)]
if missing:
    st.error(f"Missing cities in the data: {', '.join(missing)}")
    st.stop()

# ---------------------------------------------------------------- selection
c1, c2, c3 = st.columns([2, 2, 1])
city = c1.selectbox("City", core.CITIES, key="city")
city_rep = rep[rep.city == city]
first_day, last_day = city_rep.target_time.min().date(), city_rep.target_time.max().date()
last_actual = city_rep[city_rep.actual_utilization.notna()].target_time.max()
day = c2.date_input("Prediction for (date, IST)", value=last_actual.date(), min_value=first_day,
                    max_value=last_day, key="day")
hour = c3.selectbox("Hour", list(range(24)), index=18, format_func=lambda h: f"{h:02d}:00", key="hour")
target = pd.Timestamp.combine(day, Time(hour))

row = core.lookup(rep, city, target)
if row is None:
    st.info(f"No valid prediction for {city} at {target:%d %b %Y %H:%M}. The model needs a complete 24-hour "
            "input window, including the value from one week earlier. The first 8 days of the dataset cannot be "
            "predicted, and neither can anything more than one hour after the dataset ends.")
    st.stop()

# ---------------------------------------------------------------- prediction
installed = int(hist.loc[hist.city == city, "installed_chargers"].iloc[0])
pred = float(row.predicted_utilization)
category = core.demand_category(pred)

st.subheader(f"{city}: next hour {target:%a %d %b %Y, %H:%M} IST")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Predicted utilization", f"{pred * 100:.1f}%", help=f"≈ {pred * installed:.0f} of {installed} installed chargers")
if category:
    m2.markdown(f"**Demand category**\n\n:{category[1]}-badge[{category[0]}]")
else:
    m2.metric("Demand category", "n/a")
    st.warning(f"The model output {pred:.4f} is outside 0–1. It is shown unclipped and has no demand category.")
if pd.notna(row.actual_utilization):
    actual = float(row.actual_utilization)
    m3.metric("Actual (simulated)", f"{actual * 100:.1f}%", delta=f"{(pred - actual) * 100:+.1f} pp prediction error",
              delta_color="off")
else:
    m3.metric("Actual (simulated)", "n/a")
m4.markdown(f"**Period**\n\n{core.PERIODS[row.period]}")
st.caption(f"Inputs: {row.input_end - pd.Timedelta(hours=23):%d %b %H:%M} – {row.input_end:%d %b %H:%M} IST "
           f"(24 hourly steps). Demand bands as in the production pricing policy: Low < 40% ≤ Moderate < 70% ≤ High "
           f"< 90% ≤ Very high.")

# ---------------------------------------------------------------- chart
frame = core.chart_frame(hist, rep, city, target)
st.markdown("#### Utilization, previous 7 days")
st.line_chart(frame, x_label="Time (IST)", y_label="Utilization (%)", color=["#1d4ed8", "#ea580c"])
st.caption(f"{city} · {frame.index.min():%d %b %Y %H:%M} → {frame.index.max():%d %b %Y %H:%M} IST · "
           f"installed chargers {installed:,} · simulated data")

with st.expander("About this experiment"):
    st.markdown(f"**Held-out test accuracy for {city}** (2026-03-04 → 03-29, simulated data):")
    st.dataframe(core.city_test_metrics(city), width="content")
    st.markdown(
        "- Model: LSTM, same architecture as the production Caltech model, trained on four-city simulated data.\n"
        "- Target: occupied chargers ÷ installed chargers, per city and hour.\n"
        "- Station names and locations in the source are real; every hourly value is simulated.\n"
        "- Details: `experiments/india_ev_lstm/README.md`.")
