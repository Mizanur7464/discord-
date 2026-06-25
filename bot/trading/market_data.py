"""Fetch intraday and daily market data for scanner modules."""

from __future__ import annotations

import json
import logging
from urllib.parse import quote
from urllib.request import Request, urlopen

from bot.trading.indicators import Bar

logger = logging.getLogger(__name__)


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


def fetch_float_shares_sync(symbol: str, finnhub_api_key: str) -> float | None:
    """Return float shares from Finnhub metrics when available."""
    if not finnhub_api_key:
        return None
    url = (
        "https://finnhub.io/api/v1/stock/metric"
        f"?symbol={quote(symbol.upper())}&metric=all&token={quote(finnhub_api_key)}"
    )
    try:
        with urlopen(Request(url, headers={"User-Agent": "discord-news-bot/1.0"}), timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("Finnhub float fetch failed for %s: %s", symbol, exc)
        return None

    metric = payload.get("metric") or {}
    raw = metric.get("floatShares") or metric.get("shareOutstanding")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    # Finnhub sometimes returns float in millions for smaller caps.
    if 0 < value < 10_000:
        value *= 1_000_000
    return value


def fetch_company_profile_sync(symbol: str, finnhub_api_key: str) -> tuple[str, str]:
    """Return (company_name, country_flag_emoji)."""
    if not finnhub_api_key:
        return "", "🇺🇸"
    url = (
        "https://finnhub.io/api/v1/stock/profile2"
        f"?symbol={quote(symbol.upper())}&token={quote(finnhub_api_key)}"
    )
    try:
        with urlopen(Request(url, headers={"User-Agent": "discord-news-bot/1.0"}), timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("Finnhub profile fetch failed for %s: %s", symbol, exc)
        return "", "🇺🇸"

    name = str(payload.get("name") or "").strip()
    country = str(payload.get("country") or "US").upper()
    flags = {
        "US": "🇺🇸",
        "CN": "🇨🇳",
        "HK": "🇭🇰",
        "CA": "🇨🇦",
        "GB": "🇬🇧",
        "IL": "🇮🇱",
        "IN": "🇮🇳",
        "JP": "🇯🇵",
        "KR": "🇰🇷",
        "TW": "🇹🇼",
        "AU": "🇦🇺",
        "DE": "🇩🇪",
        "FR": "🇫🇷",
        "SG": "🇸🇬",
    }
    return name, flags.get(country, "🇺🇸")
