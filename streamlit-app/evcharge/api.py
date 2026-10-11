"""
HTTP client for the Spring Boot backend. Streamlit never talks to MySQL or FastAPI directly:
forecasts and evaluation go through the backend's /api/forecast/* endpoints.

Configuration (environment variables, read on every call so they can change between runs):
  EVCHARGE_API_URL      backend base URL (default http://127.0.0.1:8080)
  EVCHARGE_API_TIMEOUT  request timeout in seconds (default 20)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote as urlquote

import requests

DEFAULT_API_URL = "http://127.0.0.1:8080"
DEFAULT_TIMEOUT_S = 20.0


def base_url() -> str:
    return os.environ.get("EVCHARGE_API_URL", DEFAULT_API_URL).rstrip("/")


def timeout_s() -> float:
    try:
        return float(os.environ.get("EVCHARGE_API_TIMEOUT", DEFAULT_TIMEOUT_S))
    except ValueError:
        return DEFAULT_TIMEOUT_S


@dataclass
class ApiError(Exception):
    """A failed call. status 0 means the backend could not be reached at all."""

    status: int
    title: str
    detail: str = ""
    errors: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.status} {self.title}: {self.detail}"


def _request(method: str, path: str, *, params: dict | None = None, json: Any = None) -> Any:
    url = base_url() + path
    clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
    try:
        res = requests.request(method, url, params=clean, json=json, timeout=timeout_s(),
                               headers={"Accept": "application/json"})
    except requests.Timeout:
        raise ApiError(0, "Backend timed out", "The backend did not answer in time.") from None
    except requests.RequestException:
        raise ApiError(0, "Backend unreachable", f"Cannot reach the backend at {base_url()}.") from None
    try:
        body = res.json() if res.content else None
    except ValueError:
        body = None
    if not res.ok:
        problem = body if isinstance(body, dict) else {}
        raise ApiError(
            status=res.status_code,
            title=str(problem.get("title") or res.reason or "Request failed"),
            detail=str(problem.get("detail") or ""),
            errors={str(k): str(v) for k, v in (problem.get("errors") or {}).items()},
        )
    return body


# ---------------------------------------------------------------- health
def health() -> dict:
    return _request("GET", "/api/health")


def db_health() -> dict:
    return _request("GET", "/api/health/db")


def ml_status() -> dict:
    return _request("GET", "/api/forecast/status")


# ---------------------------------------------------------------- forecasting (via backend -> FastAPI)
def forecast(forecast_time: str) -> dict:
    return _request("GET", "/api/forecast/next-hour", params={"forecastTime": forecast_time})


def evaluation() -> dict:
    return _request("GET", "/api/forecast/evaluation")


def evaluation_series(date_from: str, date_to: str) -> dict:
    return _request("GET", "/api/forecast/evaluation/series", params={"from": date_from, "to": date_to})


# ---------------------------------------------------------------- stations, slots, pricing, bookings
def stations() -> list[dict]:
    return _request("GET", "/api/stations")


def availability(station_id: int, date: str) -> dict:
    return _request("GET", "/api/slots/availability", params={"stationId": station_id, "date": date})


def quote(station_id: int, start_time: str) -> dict:
    return _request("GET", "/api/pricing/quote", params={"stationId": station_id, "startTime": start_time})


def bookings(station_id: int | None = None) -> list[dict]:
    return _request("GET", "/api/bookings", params={"stationId": station_id})


def create_booking(station_id: int, customer_name: str, start_time: str, quoted_final_price: Any = None) -> dict:
    body = {"stationId": station_id, "customerName": customer_name, "startTime": start_time}
    if quoted_final_price is not None:
        body["quotedFinalPrice"] = quoted_final_price
    return _request("POST", "/api/bookings", json=body)


def cancel_booking(booking_id: int) -> dict:
    return _request("POST", f"/api/bookings/{urlquote(str(booking_id), safe='')}/cancel")


# ---------------------------------------------------------------- user-facing wording
_FRIENDLY_TITLES = {
    "Duplicate booking": "You already have this booking",
    "Slot unavailable": "This slot is no longer available",
    "Price changed": "The price has changed",
    "Cancellation not allowed": "This booking can no longer be cancelled",
    "Validation failed": "Please check your details",
    "Booking rejected": "This slot cannot be booked",
    "Invalid request": "Invalid date",
    "Not found": "Not found",
}

FIELD_NAMES = {"customerName": "Name", "stationId": "Station", "startTime": "Slot", "quotedFinalPrice": "Price"}


def friendly(error: ApiError) -> tuple[str, str]:
    """(headline, explanation) for showing an error to a user. The backend's 4xx details are plain
    English and are kept; connection and server failures get a non-technical message."""
    if error.status == 0 or error.status in (502, 504):
        return "Cannot reach the server", "Check that the backend is running and try again."
    if error.status == 503:
        return ("Pricing is temporarily unavailable",
                "The forecast service is offline, so a price cannot be calculated. Please try again shortly.")
    if error.status >= 500:
        return "An unexpected error occurred", "Please try again."
    return _FRIENDLY_TITLES.get(error.title, error.title or "Something went wrong"), error.detail
