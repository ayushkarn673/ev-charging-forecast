"""
Test fixtures: a stub of the Spring Boot API on a random local port (standard library only).
Responses use the backend's real JSON shapes; every request is recorded so tests can assert what
the Streamlit app sent.
"""
from __future__ import annotations

import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
import streamlit as st

STATIONS = [
    {"id": 1, "code": "DEMO-01", "name": "Demo Station 01 - City Centre", "address": "Demo", "capacity": 4,
     "timeZone": "Asia/Kolkata", "basePricePerHour": 120.0, "currency": "INR"},
    {"id": 2, "code": "DEMO-02", "name": "Demo Station 02 - Tech Park", "address": "Demo", "capacity": 2,
     "timeZone": "Asia/Kolkata", "basePricePerHour": 150.0, "currency": "INR"},
]


def slot(hour: int, status: str, booked: int = 0, cap: int = 4, day: str = "2030-01-16") -> dict:
    start = f"{day}T{hour:02d}:00:00+05:30"
    end_hour = (hour + 1) % 24
    end = f"{day}T{end_hour:02d}:00:00+05:30"
    available = cap - booked if status in ("AVAILABLE", "FULL") else 0
    return {"startTime": start, "endTime": end, "booked": booked, "available": available,
            "bookable": status == "AVAILABLE", "status": status}


def availability(station_id: int = 1, cap: int = 4) -> dict:
    slots = [slot(h, "STARTED", cap=cap) for h in range(0, 6)]
    slots += [slot(h, "AVAILABLE", booked=1, cap=cap) for h in range(6, 10)]
    slots += [slot(10, "FULL", booked=cap, cap=cap)]
    slots += [slot(h, "AVAILABLE", cap=cap) for h in range(11, 24)]
    return {"stationId": station_id, "stationCode": f"DEMO-0{station_id}", "date": "2030-01-16",
            "timeZone": "Asia/Kolkata", "capacity": cap, "basePricePerHour": 120.0, "currency": "INR", "slots": slots}


QUOTE = {
    "stationId": 1, "stationCode": "DEMO-01", "slotStart": "2030-01-16T13:00:00+05:30",
    "slotEnd": "2030-01-16T14:00:00+05:30", "currency": "INR",
    "price": {"basePrice": 120.0, "utilization": 0.472, "congestionLevel": "MEDIUM", "multiplier": 1.15,
              "finalPrice": 138.0},
    "forecast": {"source": "LSTM (FastAPI ml-service)", "mode": "historical_replay", "isSimulation": True,
                 "modelId": "ev_demand_lstm@sha256:14c51f034f14", "replayForecastTime": "2020-02-05T13:00:00-08:00",
                 "targetStart": "2020-02-05T13:00:00-08:00", "targetEnd": "2020-02-05T14:00:00-08:00",
                 "horizonHours": 1, "predictedUtilizationPercent": 47.2, "mapping": "Demand signal...",
                 "notice": "Historical replay", "warnings": []},
}


def booking(booking_id: int, start: str, status: str = "CONFIRMED") -> dict:
    return {"id": booking_id, "stationId": 1, "stationCode": "DEMO-01", "stationName": "Demo Station 01 - City Centre",
            "customerName": "Priya Sharma", "startTime": start, "endTime": start.replace("T13:", "T14:"),
            "status": status, "basePrice": 120.0, "priceMultiplier": 1.15, "finalPrice": 138.0, "currency": "INR",
            "predictedUtilization": 0.472, "congestionLevel": "MEDIUM", "forecastMode": "historical_replay",
            "forecastReferenceTime": "2020-02-05T21:00:00Z", "modelId": "ev_demand_lstm@sha256:14c51f034f14",
            "createdAt": "2026-10-11T10:00:00Z"}


FORECAST_VIEW = {
    "source": "LSTM (FastAPI ml-service)",
    "forecast": {"mode": "historical_replay", "isSimulation": True, "notice": "Historical replay", "siteId": "caltech",
                 "installedCapacitySpaces": 54, "forecastTime": "2020-02-05T10:00:00-08:00",
                 "forecastTimeUtc": "2020-02-05T18:00:00Z", "targetStart": "2020-02-05T10:00:00-08:00",
                 "targetEnd": "2020-02-05T11:00:00-08:00", "horizonHours": 1,
                 "prediction": {"utilization": 0.3785, "utilizationPercent": 37.8, "estimatedOccupiedSpaces": 20.44,
                                "estimatedOccupiedSpacesRounded": 21, "estimatedAvailableSpacesRounded": 33,
                                "rawUtilization": 0.3785},
                 "observedOutcome": {"utilization": 0.419, "utilizationPercent": 41.9, "averageOccupiedSpaces": 22.6,
                                     "note": "Recorded outcome, shown for comparison only."},
                 "modelId": "ev_demand_lstm@sha256:14c51f034f14",
                 "warnings": [{"code": "WEEKEND_TARGET", "message": "Weekend hour."}]},
    "congestionLevel": "LOW",
    "pricingPolicy": {"thresholds": {"medium": 0.40, "high": 0.70, "veryHigh": 0.90},
                      "multipliers": {"low": 0.90, "medium": 1.15, "high": 1.35, "veryHigh": 1.60}},
}

_overall = {"n": 1728, "maePp": 1.599, "rmsePp": 2.384, "maeSpaces": 0.863, "rmseSpaces": 1.287, "biasPp": -0.08,
            "wapePercent": 14.7}
EVALUATION = {
    "source": "Saved evaluation", "modelId": "ev_demand_lstm@sha256:14c51f034f14",
    "testPeriodLocal": ["2019-12-20 00:00-0800", "2020-02-29 23:00-0800"], "horizonHours": 1,
    "installedCapacitySpaces": 54,
    "overall": {"lstm": _overall,
                "previousHour": {**_overall, "maePp": 2.533, "rmsePp": 5.004, "wapePercent": 23.4},
                "sameHourLastWeek": {**_overall, "maePp": 5.023, "rmsePp": 9.611, "wapePercent": 46.3}},
    "comparisons": {"lstmVsPreviousHour": {"maeDifferencePp": -0.934, "maeDifferenceCi95Pp": [-1.22, -0.62],
                                           "maeReductionPercent": 36.9},
                    "lstmVsSameHourLastWeek": {"maeDifferencePp": -3.42, "maeDifferenceCi95Pp": [-4.39, -2.58],
                                               "maeReductionPercent": 68.2}},
    "bySubset": {"weekend": {"n": 504, "lstm": {"maePp": 0.88, "rmsePp": 1.18},
                             "previousHour": {"maePp": 0.69, "rmsePp": 1.23}}},
    "maePpByLocalHour": {}, "seriesAvailable": True, "defaultSeriesWindow": ["2020-01-06", "2020-01-20"],
}
SERIES = {"source": "Saved test-set predictions; no new inference.", "units": "utilization ratio (0..1)",
          "points": [{"targetTime": f"2020-02-03T{h:02d}:00:00-08:00", "actual": 0.1 * (h % 5), "lstm": 0.1 * (h % 5) + 0.01,
                      "previousHour": 0.0, "sameHourLastWeek": 0.0} for h in range(24)]}


def default_routes() -> dict:
    return {
        ("GET", "/api/health"): (200, {"status": "UP", "service": "evcharge-backend"}),
        ("GET", "/api/health/db"): (200, {"status": "UP", "database": "mysql"}),
        ("GET", "/api/forecast/status"): (200, {"status": "ok", "modelLoaded": True, "modelId": "m",
                                                "observationsLoaded": 11665}),
        ("GET", "/api/forecast/next-hour"): (200, FORECAST_VIEW),
        ("GET", "/api/forecast/evaluation"): (200, EVALUATION),
        ("GET", "/api/forecast/evaluation/series"): (200, SERIES),
        ("GET", "/api/stations"): (200, STATIONS),
        ("GET", "/api/slots/availability"): (200, availability()),
        ("GET", "/api/pricing/quote"): (200, QUOTE),
        ("GET", "/api/bookings"): (200, [booking(19, "2030-01-16T13:00:00+05:30"),
                                         booking(17, "2020-01-01T13:00:00+05:30"),
                                         booking(18, "2030-01-17T13:00:00+05:30", status="CANCELLED")]),
        ("POST", "/api/bookings"): (201, booking(42, "2030-01-16T13:00:00+05:30")),
        ("POST", "/api/bookings/19/cancel"): (200, booking(19, "2030-01-16T13:00:00+05:30", status="CANCELLED")),
    }


class StubBackend:
    def __init__(self):
        self.routes = copy.deepcopy(default_routes())
        self.calls: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self):
                parsed = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                stub.calls.append({"method": self.command, "path": parsed.path,
                                   "query": {k: v[0] for k, v in parse_qs(parsed.query).items()},
                                   "json": json.loads(raw) if raw else None})
                status, body = stub.routes.get((self.command, parsed.path),
                                               (404, {"title": "Not found", "detail": f"no stub for {parsed.path}"}))
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/problem+json" if status >= 400 else "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = _serve
            do_POST = _serve

            def log_message(self, *args):  # keep test output quiet
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def calls_to(self, method: str, path: str) -> list[dict]:
        return [c for c in self.calls if c["method"] == method and c["path"] == path]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub(monkeypatch):
    backend = StubBackend()
    monkeypatch.setenv("EVCHARGE_API_URL", backend.url)
    monkeypatch.setenv("EVCHARGE_API_TIMEOUT", "5")
    st.cache_data.clear()
    yield backend
    backend.close()
    st.cache_data.clear()
