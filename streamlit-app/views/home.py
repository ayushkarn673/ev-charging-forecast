import streamlit as st

from evcharge import api
from evcharge.fmt import DEMAND, money, place_name, demand_badge
from evcharge.ui import STATIONS_PAGE, cached_stations, go_book, show_error

st.title("EVCharge")
st.markdown("Book a one-hour EV charging slot. Prices follow expected demand: quieter hours cost less.")

with st.container(horizontal=True):
    if st.button("Book a slot", type="primary"):
        go_book()
    if st.button("View stations"):
        st.switch_page(STATIONS_PAGE)

st.subheader("How it works")
steps = [
    ("1. Choose a station", "Select a charging station."),
    ("2. Choose an hour", "See which one-hour slots are available."),
    ("3. Confirm", "The price depends on the expected demand for that hour."),
]
for col, (title, text) in zip(st.columns(3), steps):
    with col.container(border=True):
        st.markdown(f"**{title}**")
        st.caption(text)

st.subheader("Demand levels")
effect = {
    "LOW": "Below the base price",
    "MEDIUM": "Slightly above the base price",
    "HIGH": "Peak pricing",
    "VERY_HIGH": "Highest price",
}
table = "| Demand | Price |\n|---|---|\n" + "".join(f"| {demand_badge(level)} | {effect[level]} |\n" for level in DEMAND)
st.markdown(table)

st.subheader("Stations")
try:
    stations = cached_stations()
except api.ApiError as err:
    show_error(err, retry_key="home-retry")
else:
    for col, s in zip(st.columns(max(1, len(stations))), stations):
        with col.container(border=True):
            st.markdown(f"**{place_name(s)}**")
            st.caption(f"{s['capacity']} chargers · base {money(s['basePricePerHour'], s['currency'])}/hr")
            if st.button("Book", key=f"home-book-{s['id']}"):
                go_book(station_id=s["id"])
