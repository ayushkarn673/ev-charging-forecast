import streamlit as st

from evcharge import api
from evcharge.fmt import money, place_name, plus_days, today_in
from evcharge.ui import cached_stations, go_book, show_error, slot_grid

st.title("Stations")
st.caption("Choose a day to see available hours. Select an available hour to book it.")

try:
    stations = cached_stations()
except api.ApiError as err:
    show_error(err, retry_key="stations-retry")
    st.stop()

for s in stations:
    with st.container(border=True):
        head, action = st.columns([5, 1])
        head.markdown(f"#### {place_name(s)}")
        head.caption(f"Demo station · {s['capacity']} chargers · base "
                     f"{money(s['basePricePerHour'], s['currency'])}/hr")
        today = today_in(s["timeZone"])
        day = st.date_input("Day", value=today, min_value=today, max_value=plus_days(today, 14),
                            key=f"stations-day-{s['id']}")
        if action.button("Book", key=f"stations-book-{s['id']}"):
            go_book(station_id=s["id"], date=day)
        try:
            with st.spinner("Loading availability…"):
                availability = api.availability(s["id"], day.isoformat())
        except api.ApiError as err:
            show_error(err)
            continue
        free = sum(1 for slot in availability["slots"] if slot.get("bookable"))
        st.markdown("No available hours on this day." if free == 0 else f"**{free}** available hour{'s' if free != 1 else ''}")
        slot_grid(availability, key_prefix=f"stations-{s['id']}",
                  on_select=lambda start, sid=s["id"], d=day: st.session_state.update(stations_pick=(sid, d, start)))

# A slot click only records the pick (callbacks can't navigate); navigate from the script body.
pick = st.session_state.pop("stations_pick", None)
if pick:
    go_book(station_id=pick[0], date=pick[1], start_time=pick[2])
