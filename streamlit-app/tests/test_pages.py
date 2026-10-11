"""
Screen tests with Streamlit's AppTest against the stub backend: each page renders without
exceptions, shows backend data, sends the right API calls and handles errors.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from evcharge.fmt import pct

ROOT = Path(__file__).resolve().parents[1]
SLOT_13 = "2030-01-16T13:00:00+05:30"
CALTECH = "Caltech (comparison)"   # Model insights opens on the India model; the Caltech view is selected explicitly


def run(page: str, **state) -> AppTest:
    at = AppTest.from_file(str(ROOT / page), default_timeout=60)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def text_of(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [t.value for t in at.title]
    parts += [e.value for e in at.error] + [s.value for s in at.success] + [w.value for w in at.warning]
    return "\n".join(str(p) for p in parts)


# ---------------------------------------------------------------- app shell
def test_app_shell_runs_with_navigation(stub):
    at = run("app.py")
    assert "Book a one-hour EV charging slot" in text_of(at)   # Home is the default page


# ---------------------------------------------------------------- home
def test_home_lists_stations_from_backend(stub):
    at = run("views/home.py")
    txt = text_of(at)
    assert "City Centre" in txt and "Tech Park" in txt
    assert "4 chargers · base ₹120.00/hr" in txt
    assert ":green-badge[Low demand]" in txt and ":red-badge[Very high demand]" in txt
    assert at.button(key="home-book-1").label == "Book"


def test_home_shows_friendly_error_when_backend_is_down(stub):
    stub.routes[("GET", "/api/stations")] = (500, {"title": "Internal error", "detail": "boom"})
    at = run("views/home.py")
    assert "An unexpected error occurred" in at.error[0].value
    assert "boom" not in at.error[0].value          # technical detail is not shown


# ---------------------------------------------------------------- stations
def test_stations_shows_backend_slot_statuses(stub):
    at = run("views/stations.py")
    started = at.button(key=f"stations-1-2030-01-16T00:00:00+05:30")
    full = at.button(key=f"stations-1-2030-01-16T10:00:00+05:30")
    free = at.button(key=f"stations-1-{SLOT_13}")
    assert started.label == "00:00 · Started" and started.disabled
    assert full.label == "10:00 · Full" and full.disabled
    assert free.label == "13:00 · 4/4 free" and not free.disabled
    assert "**17** available hours" in text_of(at)
    assert {c["query"]["stationId"] for c in stub.calls_to("GET", "/api/slots/availability")} == {"1", "2"}


# ---------------------------------------------------------------- book
def test_booking_flow_uses_backend_price_and_sends_quote(stub):
    at = run("views/book.py")
    assert not stub.calls_to("GET", "/api/pricing/quote")            # no price before a slot is picked
    assert at.button(key="book_submit").disabled

    at.button(key=f"book-{SLOT_13}").click().run()
    assert not at.exception
    quote_calls = stub.calls_to("GET", "/api/pricing/quote")
    assert quote_calls[-1]["query"] == {"stationId": "1", "startTime": SLOT_13}
    txt = text_of(at)
    assert "₹138.00" in txt and ":blue-badge[Moderate demand]" in txt and "+15%" in txt

    at.text_input(key="book_name").input("Priya Sharma").run()
    assert len(stub.calls_to("GET", "/api/pricing/quote")) == len(quote_calls)   # typing doesn't re-price
    submit = at.button(key="book_submit")
    assert submit.label == "Confirm booking · ₹138.00" and not submit.disabled
    submit.click().run()

    assert not at.exception
    post = stub.calls_to("POST", "/api/bookings")[-1]["json"]
    assert post == {"stationId": 1, "customerName": "Priya Sharma", "startTime": SLOT_13, "quotedFinalPrice": 138.0}
    assert "Booking confirmed" in text_of(at)


def test_unbookable_slots_are_disabled_on_book_page(stub):
    at = run("views/book.py")
    assert at.button(key="book-2030-01-16T00:00:00+05:30").disabled
    assert at.button(key="book-2030-01-16T10:00:00+05:30").disabled


@pytest.mark.parametrize("status, title, detail, expected", [
    (409, "Price changed", "The price for this slot is now 172.50 INR", "The price has changed"),
    (409, "Slot unavailable", "All 4 chargers are booked", "This slot is no longer available"),
    (409, "Duplicate booking", "Priya Sharma already has a booking", "You already have this booking"),
])
def test_booking_errors_from_backend_are_shown(stub, status, title, detail, expected):
    stub.routes[("POST", "/api/bookings")] = (status, {"title": title, "status": status, "detail": detail})
    at = run("views/book.py")
    at.button(key=f"book-{SLOT_13}").click().run()
    at.text_input(key="book_name").input("Priya Sharma").run()
    at.button(key="book_submit").click().run()
    assert not at.exception
    err = at.error[0].value
    assert expected in err and detail in err
    assert "Booking confirmed" not in text_of(at)


def test_no_price_when_forecast_service_is_down(stub):
    stub.routes[("GET", "/api/pricing/quote")] = (503, {"title": "Forecast unavailable", "detail": "x"})
    at = run("views/book.py")
    at.button(key=f"book-{SLOT_13}").click().run()
    assert "Pricing is temporarily unavailable" in at.error[0].value
    assert at.button(key="book_submit").disabled


def test_book_page_when_backend_unreachable(stub, monkeypatch):
    monkeypatch.setenv("EVCHARGE_API_URL", "http://127.0.0.1:9")   # nothing listens on port 9
    at = run("views/book.py")
    assert "Cannot reach the server" in at.error[0].value


# ---------------------------------------------------------------- my bookings
def test_bookings_cancel_is_two_step_and_calls_backend(stub):
    at = run("views/bookings.py")
    txt = text_of(at)
    assert "3 bookings" in txt and "~~₹138.00~~" in txt          # cancelled booking shown struck through
    assert "Slot started" in txt                                 # booking 17 is in the past
    keys = {b.key for b in at.button}
    assert "bk-cancel-19" in keys and "bk-cancel-17" not in keys and "bk-cancel-18" not in keys

    at.button(key="bk-cancel-19").click().run()
    assert not stub.calls_to("POST", "/api/bookings/19/cancel")   # first click only asks
    at.button(key="bk-keep-19").click().run()
    assert "bk-cancel-19" in {b.key for b in at.button}

    at.button(key="bk-cancel-19").click().run()
    at.button(key="bk-yes-19").click().run()
    assert not at.exception
    assert len(stub.calls_to("POST", "/api/bookings/19/cancel")) == 1
    assert "Booking #19 has been cancelled." in at.success[0].value


def test_bookings_cancel_rejected_by_backend(stub):
    stub.routes[("POST", "/api/bookings/19/cancel")] = (409, {"title": "Cancellation not allowed",
                                                             "detail": "its slot started"})
    at = run("views/bookings.py")
    at.button(key="bk-cancel-19").click().run()
    at.button(key="bk-yes-19").click().run()
    assert "This booking can no longer be cancelled" in at.error[0].value


def test_bookings_filter_passes_station(stub):
    at = run("views/bookings.py")
    at.selectbox(key="bookings_station").select(2).run()
    assert stub.calls_to("GET", "/api/bookings")[-1]["query"] == {"stationId": "2"}


def test_empty_bookings(stub):
    stub.routes[("GET", "/api/bookings")] = (200, [])
    at = run("views/bookings.py")
    assert "No bookings yet" in text_of(at)


# ---------------------------------------------------------------- nerd stats
def test_nerd_stats_shows_forecast_policy_and_evaluation(stub):
    at = run("views/nerd_stats.py", nerd_model=CALTECH)
    assert stub.calls_to("GET", "/api/forecast/next-hour")[-1]["query"] == {"forecastTime": "2020-02-05T10:00:00-08:00"}
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Predicted utilization"] == pct(0.3785)          # value from the stubbed forecast
    assert metrics["Est. occupied spaces"] == "21 / 54"
    assert metrics["LSTM MAE"] == "1.60 pp" and metrics["LSTM WAPE"] == "14.7%"
    txt = text_of(at)
    assert ":green-badge[Backend: online]" in txt and ":green-badge[LSTM service: online]" in txt
    assert "(current forecast)" in txt and "× 0.90" in txt
    assert "WEEKEND_TARGET" in txt
    series_call = stub.calls_to("GET", "/api/forecast/evaluation/series")[-1]["query"]
    assert series_call == {"from": "2020-02-03", "to": "2020-02-09"}
    assert len(at.get("vega_lite_chart")) == 1   # the actual-vs-predicted chart


def test_nerd_stats_preset_changes_forecast_time(stub):
    at = run("views/nerd_stats.py", nerd_model=CALTECH)
    at.button(key="preset-Night 03:00").click().run()
    assert stub.calls_to("GET", "/api/forecast/next-hour")[-1]["query"] == {"forecastTime": "2020-02-06T03:00:00-08:00"}


def test_nerd_stats_reports_ml_down(stub):
    stub.routes[("GET", "/api/forecast/status")] = (503, {"title": "Forecast unavailable", "detail": "x"})
    stub.routes[("GET", "/api/forecast/next-hour")] = (503, {"title": "Forecast unavailable", "detail": "x"})
    at = run("views/nerd_stats.py", nerd_model=CALTECH)
    txt = text_of(at)
    assert ":red-badge[LSTM service: offline]" in txt
    assert "Pricing is temporarily unavailable" in at.error[0].value
