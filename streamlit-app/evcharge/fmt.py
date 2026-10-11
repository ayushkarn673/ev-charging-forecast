"""Display formatting only. Times from the API already carry the right offset and are shown as written."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

# Backend CongestionLevel -> (label, Streamlit badge colour). Wording only; the backend sets the level.
DEMAND = {
    "LOW": ("Low", "green"),
    "MEDIUM": ("Moderate", "blue"),
    "HIGH": ("High", "orange"),
    "VERY_HIGH": ("Very high", "red"),
}

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def money(amount, currency: str = "INR") -> str:
    if amount is None:
        return "—"
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    symbol = _SYMBOLS.get(currency)
    return f"{symbol}{value:,.2f}" if symbol else f"{value:,.2f} {currency}"


def pct(ratio, digits: int = 1) -> str:
    return "—" if ratio is None else f"{float(ratio) * 100:.{digits}f}%"


def num(value, digits: int = 2) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def wall_clock(iso: str | None, *, with_date: bool = True, with_time: bool = True) -> str:
    """'2030-01-16T10:00:00+05:30' -> '16 Jan 2030, 10:00' (the wall-clock time as given)."""
    if not iso:
        return "—"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", iso)
    if not m:
        return iso
    d = f"{int(m[3])} {_MONTHS[int(m[2]) - 1]} {m[1]}"
    t = f"{m[4]}:{m[5]}" if m[4] else ""
    return ", ".join(p for p in (with_date and d, with_time and t) if p)


def hhmm(iso: str | None) -> str:
    return iso[11:16] if iso else "—"


def place_name(item: dict | None) -> str:
    """'Demo Station 01 - City Centre' -> 'City Centre' (works for stations and bookings)."""
    name = (item or {}).get("name") or (item or {}).get("stationName") or ""
    return name.split(" - ", 1)[1] if " - " in name else name


def multiplier_change(m) -> str:
    """0.9 -> '−10%', 1.15 -> '+15%', 1 -> 'no change'."""
    change = round((float(m) - 1) * 100)
    if change == 0:
        return "no change"
    return f"+{change}%" if change > 0 else f"−{abs(change)}%"


def demand_badge(level: str | None) -> str:
    """Markdown badge for a congestion level, e.g. ':green-badge[Low demand]'."""
    if level not in DEMAND:
        return ""
    label, colour = DEMAND[level]
    return f":{colour}-badge[{label} demand]"


def today_in(tz_name: str, now: datetime | None = None) -> date:
    """Today's date in an IANA time zone (the station's)."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(ZoneInfo(tz_name)).date()


def plus_days(d: date, days: int) -> date:
    return d + timedelta(days=days)


def has_started(iso: str, now: datetime | None = None) -> bool:
    """Display hint only (the backend enforces the rule)."""
    now = now or datetime.now(timezone.utc)
    return datetime.fromisoformat(iso) <= now
