"""API client: request shapes, error parsing, configuration."""
import socket

import pytest

from evcharge import api


def test_base_url_and_timeout_come_from_environment(monkeypatch):
    monkeypatch.setenv("EVCHARGE_API_URL", "http://example.test:9999/")
    monkeypatch.setenv("EVCHARGE_API_TIMEOUT", "7.5")
    assert api.base_url() == "http://example.test:9999"
    assert api.timeout_s() == 7.5
    monkeypatch.delenv("EVCHARGE_API_URL")
    monkeypatch.setenv("EVCHARGE_API_TIMEOUT", "not-a-number")
    assert api.base_url() == "http://127.0.0.1:8080"
    assert api.timeout_s() == api.DEFAULT_TIMEOUT_S


def test_reads_go_to_the_backend_endpoints(stub):
    assert api.stations()[0]["code"] == "DEMO-01"
    api.availability(1, "2030-01-16")
    api.quote(1, "2030-01-16T13:00:00+05:30")
    api.bookings(2)
    api.bookings()
    assert stub.calls_to("GET", "/api/slots/availability")[0]["query"] == {"stationId": "1", "date": "2030-01-16"}
    # "+" in the offset must arrive intact (URL-encoded on the wire)
    assert stub.calls_to("GET", "/api/pricing/quote")[0]["query"] == {"stationId": "1",
                                                                      "startTime": "2030-01-16T13:00:00+05:30"}
    assert [c["query"] for c in stub.calls_to("GET", "/api/bookings")] == [{"stationId": "2"}, {}]


def test_create_booking_sends_quoted_price_for_backend_verification(stub):
    api.create_booking(1, "Priya", "2030-01-16T13:00:00+05:30", 138.0)
    api.create_booking(1, "Priya", "2030-01-16T14:00:00+05:30")
    first, second = stub.calls_to("POST", "/api/bookings")
    assert first["json"] == {"stationId": 1, "customerName": "Priya", "startTime": "2030-01-16T13:00:00+05:30",
                             "quotedFinalPrice": 138.0}
    assert "quotedFinalPrice" not in second["json"]


def test_cancel_posts_to_the_cancel_endpoint(stub):
    assert api.cancel_booking(19)["status"] == "CANCELLED"
    assert len(stub.calls_to("POST", "/api/bookings/19/cancel")) == 1


def test_problem_details_become_api_errors(stub):
    stub.routes[("POST", "/api/bookings")] = (409, {"title": "Duplicate booking", "status": 409,
                                                    "detail": "Priya already has a confirmed booking"})
    with pytest.raises(api.ApiError) as e:
        api.create_booking(1, "Priya", "2030-01-16T13:00:00+05:30")
    assert (e.value.status, e.value.title) == (409, "Duplicate booking")
    assert "already has" in e.value.detail
    stub.routes[("POST", "/api/bookings")] = (400, {"title": "Validation failed", "detail": "One or more fields",
                                                    "errors": {"customerName": "must not be blank"}})
    with pytest.raises(api.ApiError) as e:
        api.create_booking(1, " ", "2030-01-16T13:00:00+05:30")
    assert e.value.errors == {"customerName": "must not be blank"}


def test_unreachable_backend_is_status_zero(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("EVCHARGE_API_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("EVCHARGE_API_TIMEOUT", "2")
    with pytest.raises(api.ApiError) as e:
        api.stations()
    assert e.value.status == 0


@pytest.mark.parametrize("status, title, expected", [
    (0, "Backend unreachable", "Cannot reach the server"),
    (503, "Forecast unavailable", "Pricing is temporarily unavailable"),
    (500, "Internal error", "An unexpected error occurred"),
    (409, "Slot unavailable", "This slot is no longer available"),
    (409, "Duplicate booking", "You already have this booking"),
    (409, "Cancellation not allowed", "This booking can no longer be cancelled"),
    (400, "Invalid request", "Invalid date"),
    (418, "Some new title", "Some new title"),
])
def test_friendly_messages(status, title, expected):
    headline, _ = api.friendly(api.ApiError(status, title, "detail text"))
    assert headline == expected


def test_friendly_keeps_backend_detail_for_client_errors():
    assert api.friendly(api.ApiError(409, "Price changed", "The price is now 172.50 INR"))[1] == \
        "The price is now 172.50 INR"
