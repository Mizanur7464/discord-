"""Fetch intraday and daily market data for scanner modules."""

from __future__ import annotations

from bot.trading.indicators import Bar


def _series(data_client, symbol: str, timeframe, limit: int):
    from alpaca.data.requests import StockBarsRequest

    bars = data_client.get_stock_bars(
        StockBarsRequest(symbol_or_symbols=symbol, timeframe=timeframe, limit=limit)
    )
    if hasattr(bars, "data"):
        return bars.data.get(symbol, [])
    return bars[symbol]


def fetch_intraday_bars(data_client, symbol: str, *, limit: int = 120) -> list[Bar]:
    from alpaca.data.timeframe import TimeFrame

    series = _series(data_client, symbol, TimeFrame.Minute, limit)
    return [
        Bar(
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )
        for bar in series
    ]


def fetch_gap_and_session_change(data_client, symbol: str, current_price: float) -> tuple[float | None, float | None]:
    from alpaca.data.timeframe import TimeFrame

    daily = _series(data_client, symbol, TimeFrame.Day, 2)
    if len(daily) < 1:
        return None, None

    today = daily[-1]
    prev_close = float(daily[-2].close) if len(daily) >= 2 else float(today.open)
    today_open = float(today.open)
    gap_pct = None
    if prev_close > 0:
        gap_pct = round((today_open / prev_close - 1) * 100, 2)

    session_change_pct = None
    if today_open > 0 and current_price > 0:
        session_change_pct = round((current_price / today_open - 1) * 100, 2)
    return gap_pct, session_change_pct
