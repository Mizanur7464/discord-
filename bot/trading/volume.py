"""Stock volume checks for high-risk low-liquidity filtering."""

from __future__ import annotations

from datetime import datetime

from bot.trading.schedule import EXTENDED_CLOSE, EXTENDED_OPEN, _now_et, is_extended_market_hours


def _bar_series(data_client, symbol: str, timeframe, *, limit: int | None = None, start=None, end=None):
    from alpaca.data.requests import StockBarsRequest

    kwargs: dict = {"symbol_or_symbols": symbol, "timeframe": timeframe}
    if limit is not None:
        kwargs["limit"] = limit
    if start is not None:
        kwargs["start"] = start
    if end is not None:
        kwargs["end"] = end
    bars = data_client.get_stock_bars(StockBarsRequest(**kwargs))
    if hasattr(bars, "data"):
        return bars.data.get(symbol, [])
    return bars[symbol]


def _daily_bar_volume(data_client, symbol: str) -> int:
    from alpaca.data.timeframe import TimeFrame

    series = _bar_series(data_client, symbol, TimeFrame.Day, limit=2)
    if not series:
        return 0
    return int(series[-1].volume or 0)


def _session_start_et(now: datetime) -> datetime | None:
    """Start of today's extended session (4:00 AM ET), or None if market closed."""
    current = _now_et(now)
    if current.weekday() >= 5:
        return None
    clock = current.time()
    if clock >= EXTENDED_CLOSE or clock < EXTENDED_OPEN:
        return None
    return current.replace(
        hour=EXTENDED_OPEN.hour,
        minute=EXTENDED_OPEN.minute,
        second=0,
        microsecond=0,
    )


def _intraday_session_volume(data_client, symbol: str, now: datetime | None = None) -> int:
    """Sum minute-bar volume from today's extended session open until now."""
    from alpaca.data.timeframe import TimeFrame

    current = _now_et(now)
    session_start = _session_start_et(current)
    if session_start is None:
        return 0
    try:
        series = _bar_series(
            data_client,
            symbol,
            TimeFrame.Minute,
            start=session_start,
            end=current,
        )
    except Exception:
        return 0
    if not series:
        return 0
    return sum(int(getattr(bar, "volume", 0) or 0) for bar in series)


def get_daily_volume(data_client, symbol: str) -> int:
    """Return today's volume — uses minute bars when the daily bar is still zero."""
    daily_vol = _daily_bar_volume(data_client, symbol)
    if is_extended_market_hours():
        session_vol = _intraday_session_volume(data_client, symbol)
        return max(daily_vol, session_vol)
    return daily_vol
