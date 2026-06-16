"""Stock volume checks for high-risk low-liquidity filtering."""

from __future__ import annotations


def get_daily_volume(data_client, symbol: str) -> int:
    """Return the latest daily bar volume from Alpaca (today or last session)."""
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    bars = data_client.get_stock_bars(
        StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, limit=2)
    )
    if hasattr(bars, "data"):
        series = bars.data.get(symbol, [])
    else:
        series = bars[symbol]
    if not series:
        return 0
    return int(series[-1].volume)
