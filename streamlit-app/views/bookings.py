"""My bookings: history from the backend, with the backend's cancel endpoint."""
import streamlit as st

from evcharge import api
from evcharge.fmt import has_started, money, multiplier_change, place_name, demand_badge, wall_clock
from evcharge.ui import cached_stations, go_book, show_error

ss = st.session_state

head, filt, refresh = st.columns([4, 2, 1], vertical_alignment="bottom")
head.title("My bookings")

try:
    stations = cached_stations()
except api.ApiError:
    stations = []   # the filter is optional; the list below still loads
station_ids = [None] + [s["id"] for s in stations]
names = {s["id"]: place_name(s) for s in stations}
station_id = filt.selectbox("Station", station_ids, format_func=lambda i: "All stations" if i is None else names[i],
                            key="bookings_station")
refresh.button("Refresh", key="bookings_refresh", width="stretch")

if msg := ss.pop("bookings_flash", None):
    st.success(msg)
if err := ss.pop("bookings_flash_error", None):
    show_error(err)

try:
    with st.spinner("Loading bookings…"):
        items = api.bookings(station_id)
except api.ApiError as err:
    show_error(err, retry_key="bookings-retry")
    st.stop()

st.caption(f"{len(items)} booking{'s' if len(items) != 1 else ''}")

if not items:
    with st.container(border=True):
        st.markdown("**No bookings yet**")
        st.caption("Your bookings will appear here.")
        if st.button("Book a slot", type="primary"):
            go_book()
    st.stop()


def ask_cancel(booking_id: int) -> None:
    ss["bookings_confirming"] = booking_id


def keep(_: int) -> None:
    ss.pop("bookings_confirming", None)


def do_cancel(booking_id: int) -> None:
    ss.pop("bookings_confirming", None)
    try:
        api.cancel_booking(booking_id)
        ss["bookings_flash"] = f"Booking #{booking_id} has been cancelled."
    except api.ApiError as err:
        ss["bookings_flash_error"] = err


cols = st.columns(2)
for i, b in enumerate(items):
    cancelled = b["status"] == "CANCELLED"
    with cols[i % 2].container(border=True):
        top, pill = st.columns([4, 1])
        top.markdown(f"**{place_name(b)}**  \n{wall_clock(b['startTime'])} – {wall_clock(b['endTime'], with_date=False)}")
        pill.markdown(":gray-badge[Cancelled]" if cancelled else ":green-badge[Confirmed]")
        st.markdown(f"{demand_badge(b['congestionLevel'])} base {money(b['basePrice'], b['currency'])} · "
                    f"{multiplier_change(b['priceMultiplier'])}")
        price, action = st.columns([2, 3], vertical_alignment="bottom")
        amount = money(b["finalPrice"], b["currency"])
        price.caption(f"#{b['id']} · {b['customerName']}")
        price.markdown(f"### ~~{amount}~~" if cancelled else f"### {amount}")
        # Cancel is offered only for confirmed bookings whose slot has not started; the backend
        # enforces the same rule (409) if this display hint is wrong.
        if cancelled:
            continue
        if has_started(b["startTime"]):
            action.caption("Slot started")
        elif ss.get("bookings_confirming") == b["id"]:
            yes, no = action.columns(2)
            yes.button("Confirm cancellation", key=f"bk-yes-{b['id']}", type="primary", on_click=do_cancel, args=(b["id"],),
                       width="stretch")
            no.button("Keep booking", key=f"bk-keep-{b['id']}", on_click=keep, args=(b["id"],), width="stretch")
        else:
            action.button("Cancel booking", key=f"bk-cancel-{b['id']}", on_click=ask_cancel, args=(b["id"],),
                          help=f"Cancel booking {b['id']}")
