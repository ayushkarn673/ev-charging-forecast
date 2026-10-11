"""Shared Streamlit building blocks."""
from __future__ import annotations

import streamlit as st

from evcharge import api
from evcharge.fmt import hhmm

BOOK_PAGE = "views/book.py"
BOOKINGS_PAGE = "views/bookings.py"
STATIONS_PAGE = "views/stations.py"


@st.cache_data(ttl=60, show_spinner=False)
def cached_stations() -> list[dict]:
    """Stations change rarely; cached for a minute. Errors are not cached."""
    return api.stations()


def show_error(error: api.ApiError, *, retry_key: str | None = None) -> None:
    title, detail = api.friendly(error)
    lines = [f"**{title}**"]
    if detail:
        lines.append(detail)
    for field_name, message in error.errors.items():
        lines.append(f"- {api.FIELD_NAMES.get(field_name, field_name)}: {message}")
    st.error("\n\n".join(lines), icon=":material/error:")
    if retry_key and st.button("Try again", key=retry_key):
        st.cache_data.clear()
        st.rerun()


def go_book(station_id: int | None = None, date=None, start_time: str | None = None) -> None:
    """Open the Book page with an optional station / day / slot already chosen."""
    st.session_state["book_preset"] = {"station_id": station_id, "date": date, "start_time": start_time}
    st.switch_page(BOOK_PAGE)


# Mirrors the backend SlotStatus enum (slots[].status). Wording only; the backend decides the status.
_SLOT_TEXT = {
    "AVAILABLE": lambda s, cap: f"{s['available']}/{cap} free",
    "FULL": lambda s, cap: "Full",
    "STARTED": lambda s, cap: "Started",
    "NOT_OPEN": lambda s, cap: "Not open yet",
}
_SLOT_HELP = {
    "AVAILABLE": "Available",
    "FULL": "Fully booked",
    "STARTED": "Already started",
    "NOT_OPEN": "Opens for booking 14 days in advance",
}


def slot_status(slot: dict) -> str:
    status = slot.get("status")
    if status in _SLOT_TEXT:
        return status
    return "AVAILABLE" if slot.get("bookable") else ("FULL" if slot.get("available") == 0 else "STARTED")


def slot_grid(availability: dict, *, key_prefix: str, selected: str | None = None, on_select=None,
              per_row: int = 6) -> None:
    """24 one-hour slot buttons. Only AVAILABLE slots are clickable; clicking calls on_select(start_time)."""
    cap = availability["capacity"]
    slots = availability["slots"]
    for row_start in range(0, len(slots), per_row):
        cols = st.columns(per_row)
        for col, s in zip(cols, slots[row_start:row_start + per_row]):
            status = slot_status(s)
            label = f"{hhmm(s['startTime'])} · {_SLOT_TEXT[status](s, cap)}"
            col.button(
                label,
                key=f"{key_prefix}-{s['startTime']}",
                disabled=status != "AVAILABLE" or on_select is None,
                type="primary" if selected == s["startTime"] else "secondary",
                help=_SLOT_HELP[status],
                width="stretch",
                on_click=on_select,
                args=(s["startTime"],) if on_select else None,
            )
    st.caption("Available: chargers free · Full: all chargers booked · Started: already in progress · "
               "Not open yet: more than 14 days ahead")
