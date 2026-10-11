"""Book a slot. Availability, price and every booking rule come from the backend."""
from datetime import date as Date

import streamlit as st

from evcharge import api
from evcharge.fmt import money, multiplier_change, pct, place_name, plus_days, today_in, demand_badge, wall_clock
from evcharge.ui import BOOKINGS_PAGE, cached_stations, show_error, slot_grid

ss = st.session_state

# ---------------------------------------------------------------- confirmation view
if ss.get("book_confirmed"):
    b = ss["book_confirmed"]
    _, mid, _ = st.columns([1, 2, 1])
    with mid.container(border=True):
        st.success("Booking confirmed", icon=":material/check_circle:")
        st.markdown(f"**{place_name(b)}** · {wall_clock(b['startTime'])} – {wall_clock(b['endTime'], with_date=False)}")
        st.markdown(
            f"| | |\n|---|---:|\n| Booking | #{b['id']} · {b['customerName']} |\n"
            f"| Demand | {demand_badge(b['congestionLevel'])} |\n| Base price | {money(b['basePrice'], b['currency'])} |\n"
            f"| Demand adjustment | {multiplier_change(b['priceMultiplier'])} |\n"
            f"| **Total** | **{money(b['finalPrice'], b['currency'])}** |"
        )
        c1, c2 = st.columns(2)
        if c1.button("My bookings", type="primary", width="stretch"):
            ss.pop("book_confirmed", None)
            st.switch_page(BOOKINGS_PAGE)
        if c2.button("Book another slot", width="stretch"):
            ss.pop("book_confirmed", None)
            st.rerun()
    st.stop()

# ---------------------------------------------------------------- selection
st.title("Book a slot")
st.caption("Choose a station, a day and an available hour.")

try:
    stations = cached_stations()
except api.ApiError as err:
    show_error(err, retry_key="book-retry")
    st.stop()
if not stations:
    st.info("No stations yet.")
    st.stop()

by_id = {s["id"]: s for s in stations}
preset = ss.pop("book_preset", None) or {}
if preset.get("station_id") in by_id:
    ss["book_station"] = preset["station_id"]
if ss.get("book_station") not in by_id:
    ss["book_station"] = stations[0]["id"]
if preset.get("start_time"):
    ss["book_slot"] = preset["start_time"]

left, right = st.columns([3, 2], gap="large")

with left.container(border=True):
    st.markdown("#### 1. Station and date")
    c1, c2 = st.columns(2)
    station_id = c1.selectbox("Station", options=list(by_id), format_func=lambda i: place_name(by_id[i]),
                              key="book_station")
    station = by_id[station_id]
    today = today_in(station["timeZone"])
    if isinstance(preset.get("date"), Date) and today <= preset["date"] <= plus_days(today, 14):
        ss["book_day"] = preset["date"]
    if not isinstance(ss.get("book_day"), Date) or not today <= ss["book_day"] <= plus_days(today, 14):
        ss["book_day"] = today
    day = c2.date_input("Day", min_value=today, max_value=plus_days(today, 14), key="book_day")

    # Forget a chosen slot that belongs to another station or day.
    if ss.get("book_slot_owner") != (station_id, day.isoformat()) and not preset.get("start_time"):
        ss.pop("book_slot", None)
    ss["book_slot_owner"] = (station_id, day.isoformat())

    try:
        with st.spinner("Checking free hours…"):
            availability = api.availability(station_id, day.isoformat())
    except api.ApiError as err:
        show_error(err)
        availability = None
    if availability:
        valid = {s["startTime"] for s in availability["slots"] if s.get("bookable")}
        if ss.get("book_slot") not in valid:
            ss.pop("book_slot", None)
        slot_grid(availability, key_prefix="book", selected=ss.get("book_slot"), per_row=4,
                  on_select=lambda start: ss.update(book_slot=start))

slot = ss.get("book_slot")

# ---------------------------------------------------------------- price (quote from the backend)
quote = None
with right.container(border=True):
    st.markdown("#### 2. Price")
    if not slot:
        st.caption("Select an available hour to see its price.")
    else:
        cache_key = (station_id, slot)
        if ss.get("book_quote_key") != cache_key:
            ss.pop("book_quote", None)
            try:
                with st.spinner("Calculating price…"):
                    ss["book_quote"] = api.quote(station_id, slot)
                ss["book_quote_key"] = cache_key
            except api.ApiError as err:
                show_error(err)
        quote = ss.get("book_quote") if ss.get("book_quote_key") == cache_key else None
        if quote:
            p = quote["price"]
            st.markdown(f"**{wall_clock(quote['slotStart'])} – {wall_clock(quote['slotEnd'], with_date=False)}**")
            st.markdown(
                f"| | |\n|---|---:|\n| Base price | {money(p['basePrice'], quote['currency'])} |\n"
                f"| Demand | {demand_badge(p['congestionLevel'])} (expected occupancy {pct(p['utilization'], 0)}) |\n"
                f"| Demand adjustment | {multiplier_change(p['multiplier'])} |\n"
                f"| **Total** | **{money(p['finalPrice'], quote['currency'])}** |"
            )
            with st.expander("How is this price calculated?"):
                st.write("A forecasting model estimates how busy this hour is likely to be, using historical EV "
                         "charging data. Low-demand hours are discounted and high-demand hours cost more. In this "
                         "demonstration the forecast comes from historical data, not live traffic.")

# ---------------------------------------------------------------- confirm
with right.container(border=True):
    st.markdown("#### 3. Confirm")
    if ss.pop("book_clear_name", False):
        ss["book_name"] = ""
    name = st.text_input("Your name", max_chars=100, placeholder="Full name", key="book_name")
    label = f"Confirm booking · {money(quote['price']['finalPrice'], quote['currency'])}" if quote else "Confirm booking"
    if st.button(label, type="primary", width="stretch", disabled=not (quote and name.strip()),
                 key="book_submit"):
        try:
            with st.spinner("Confirming…"):
                booking = api.create_booking(station_id, name, slot, quote["price"]["finalPrice"])
        except api.ApiError as err:
            ss.pop("book_quote_key", None)   # refresh the price on the next run (it may have changed)
            show_error(err)
        else:
            for k in ("book_slot", "book_quote", "book_quote_key"):
                ss.pop(k, None)
            ss["book_clear_name"] = True   # widget values can only be reset before the widget is drawn
            ss["book_confirmed"] = booking
            st.rerun()
    st.caption("Availability and price are checked again when you confirm.")
