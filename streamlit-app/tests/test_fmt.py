from datetime import date, datetime, timezone

import pytest

from evcharge import fmt


@pytest.mark.parametrize("amount, currency, expected", [
    (138, "INR", "₹138.00"), (1234.5, "INR", "₹1,234.50"), ("172.50", "INR", "₹172.50"),
    (10, "USD", "$10.00"), (5, "XYZ", "5.00 XYZ"), (None, "INR", "—"),
])
def test_money(amount, currency, expected):
    assert fmt.money(amount, currency) == expected


def test_wall_clock_keeps_the_given_local_time():
    assert fmt.wall_clock("2030-01-16T10:00:00+05:30") == "16 Jan 2030, 10:00"
    assert fmt.wall_clock("2030-01-16T10:00:00+05:30", with_date=False) == "10:00"
    assert fmt.wall_clock("2019-12-20 00:00-0800", with_time=False) == "20 Dec 2019"
    assert fmt.wall_clock(None) == "—"
    assert fmt.hhmm("2030-01-16T23:00:00+05:30") == "23:00"


def test_place_name_for_stations_and_bookings():
    assert fmt.place_name({"name": "Demo Station 01 - City Centre"}) == "City Centre"
    assert fmt.place_name({"stationName": "Demo Station 02 - Tech Park"}) == "Tech Park"
    assert fmt.place_name({"name": "Plain"}) == "Plain"


@pytest.mark.parametrize("m, expected", [(0.9, "−10%"), (1.15, "+15%"), (1.0, "no change"), (1.6, "+60%")])
def test_multiplier_change(m, expected):
    assert fmt.multiplier_change(m) == expected


def test_demand_badges():
    assert fmt.demand_badge("LOW") == ":green-badge[Low demand]"
    assert fmt.demand_badge("MEDIUM") == ":blue-badge[Moderate demand]"
    assert fmt.demand_badge("VERY_HIGH") == ":red-badge[Very high demand]"
    assert fmt.demand_badge("UNKNOWN") == ""


def test_today_in_station_zone():
    late_utc = datetime(2030, 1, 15, 20, 0, tzinfo=timezone.utc)   # 01:30 next day in IST
    assert fmt.today_in("Asia/Kolkata", late_utc) == date(2030, 1, 16)
    assert fmt.today_in("America/Los_Angeles", late_utc) == date(2030, 1, 15)


def test_has_started():
    now = datetime(2030, 1, 16, 8, 0, tzinfo=timezone.utc)   # 13:30 IST
    assert fmt.has_started("2030-01-16T13:00:00+05:30", now) is True
    assert fmt.has_started("2030-01-16T14:00:00+05:30", now) is False
