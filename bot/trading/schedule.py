"""US market trading window checks (Eastern Time)."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EXTENDED_OPEN = time(4, 0)   # pre-market start
EXTENDED_CLOSE = time(20, 0)  # after-hours end


def _now_et(now: datetime | None = None) -> datetime:
    current = now or datetime.now(ET)
    if current.tzinfo is None:
        return current.replace(tzinfo=ET)
    return current.astimezone(ET)


def is_premarket_hours(now: datetime | None = None) -> bool:
    """True during US pre-market: Mon–Fri 4:00 AM–9:30 AM ET."""
    current = _now_et(now)
    if current.weekday() >= 5:
        return False
    t = current.time()
    return EXTENDED_OPEN <= t < REGULAR_OPEN


def is_regular_market_hours(now: datetime | None = None) -> bool:
    """True during US regular session: Mon–Fri 9:30 AM–4:00 PM ET."""
    current = _now_et(now)
    if current.weekday() >= 5:
        return False
    t = current.time()
    return REGULAR_OPEN <= t < REGULAR_CLOSE


def is_extended_market_hours(now: datetime | None = None) -> bool:
    """True during Alpaca extended session: Mon–Fri 4:00 AM–8:00 PM ET."""
    current = _now_et(now)
    if current.weekday() >= 5:
        return False
    t = current.time()
    return EXTENDED_OPEN <= t < EXTENDED_CLOSE


def is_overnight_closed(now: datetime | None = None) -> bool:
    """True during full market close on weekdays (8:00 PM–4:00 AM ET)."""
    current = _now_et(now)
    if current.weekday() >= 5:
        return True
    t = current.time()
    return t >= EXTENDED_CLOSE or t < EXTENDED_OPEN


def trading_block_reason(
    *,
    block_saturday: bool,
    block_sunday: bool,
    block_monday_premarket: bool,
    regular_market_hours_only: bool = False,
    extended_hours_trading: bool = True,
    now: datetime | None = None,
) -> str:
    """Return a reason string if trading is blocked, else empty string."""
    current = _now_et(now)
    weekday = current.weekday()

    if block_saturday and weekday == 5:
        return "Trading blocked on Saturday"

    if block_sunday and weekday == 6:
        return "Trading blocked on Sunday"

    if regular_market_hours_only:
        if weekday >= 5:
            return "Trading blocked — market closed (weekend)"
        t = current.time()
        if t < REGULAR_OPEN:
            return "Trading blocked — pre-market (regular hours start 9:30 AM ET)"
        if t >= REGULAR_CLOSE:
            return "Trading blocked — after hours (regular hours end 4:00 PM ET)"
        return ""

    if extended_hours_trading:
        if is_overnight_closed(current):
            return "Trading blocked — market fully closed (8:00 PM–4:00 AM ET)"
        return ""

    if block_monday_premarket and weekday == 0:
        market_open = current.replace(hour=9, minute=30, second=0, microsecond=0)
        if current < market_open:
            return "Trading blocked Monday pre-market (before 9:30 AM ET)"

    return ""
