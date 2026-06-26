"""Fetch intraday and daily market data for scanner modules."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from bot.trading.indicators import Bar

logger = logging.getLogger(__name__)

# Disk-backed cache of float shares so a transient API failure never blanks
# the "F:" field — floats change rarely, so a remembered value stays valid.
_FLOAT_CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "float_cache.json"
_float_cache: dict[str, float] | None = None


def _load_float_cache() -> dict[str, float]:
    global _float_cache
    if _float_cache is None:
        try:
            raw = json.loads(_FLOAT_CACHE_FILE.read_text(encoding="utf-8"))
            _float_cache = {str(k): float(v) for k, v in raw.items() if v}
        except Exception:
            _float_cache = {}
    return _float_cache


def _save_float_cache() -> None:
    if _float_cache is None:
        return
    try:
        _FLOAT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _FLOAT_CACHE_FILE.write_text(json.dumps(_float_cache), encoding="utf-8")
    except Exception as exc:
        logger.debug("Float cache save failed: %s", exc)


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


def _normalize_equity_symbol(symbol: str) -> str:
    cleaned = str(symbol or "").upper().strip()
    if ":" in cleaned:
        cleaned = cleaned.split(":")[-1]
    if not cleaned.isalpha() or not 1 <= len(cleaned) <= 5:
        return ""
    return cleaned


def _shares_from_finnhub_profile(symbol: str, finnhub_api_key: str) -> float | None:
    url = (
        "https://finnhub.io/api/v1/stock/profile2"
        f"?symbol={quote(symbol)}&token={quote(finnhub_api_key)}"
    )
    try:
        with urlopen(Request(url, headers={"User-Agent": "discord-news-bot/1.0"}), timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("Finnhub profile float fallback failed for %s: %s", symbol, exc)
        return None
    raw = payload.get("shareOutstanding")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value * 1_000_000


def _shares_from_massive(symbol: str, massive_api_key: str) -> float | None:
    url = (
        f"https://api.massive.com/v3/reference/tickers/{quote(symbol)}"
        f"?apiKey={quote(massive_api_key)}"
    )
    try:
        with urlopen(Request(url, headers={"User-Agent": "discord-news-bot/1.0"}), timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("Massive share lookup failed for %s: %s", symbol, exc)
        return None
    result = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return None
    raw = result.get("share_class_shares_outstanding") or result.get("weighted_shares_outstanding")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def fetch_float_shares_sync(
    symbol: str,
    finnhub_api_key: str,
    *,
    massive_api_key: str = "",
) -> float | None:
    """Return share count for float display (Massive → Finnhub metric → profile).

    Falls back to a remembered value when every live source fails, so a
    transient timeout never blanks the float.
    """
    equity_symbol = _normalize_equity_symbol(symbol)
    if not equity_symbol:
        return None

    cache = _load_float_cache()

    def _remember(value: float | None) -> float | None:
        if value and value > 0:
            if cache.get(equity_symbol) != value:
                cache[equity_symbol] = value
                _save_float_cache()
            return value
        return None

    if massive_api_key:
        shares = _shares_from_massive(equity_symbol, massive_api_key)
        if shares:
            return _remember(shares)

    if finnhub_api_key:
        url = (
            "https://finnhub.io/api/v1/stock/metric"
            f"?symbol={quote(equity_symbol)}&metric=all&token={quote(finnhub_api_key)}"
        )
        try:
            with urlopen(Request(url, headers={"User-Agent": "discord-news-bot/1.0"}), timeout=8) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            metric = payload.get("metric") or {}
            raw = metric.get("floatShares") or metric.get("shareOutstanding")
            if raw is not None:
                value = float(raw)
                if 0 < value < 10_000:
                    value *= 1_000_000
                if value > 0:
                    return _remember(value)
        except Exception as exc:
            logger.debug("Finnhub metric float fetch failed for %s: %s", equity_symbol, exc)

        shares = _shares_from_finnhub_profile(equity_symbol, finnhub_api_key)
        if shares:
            return _remember(shares)

    # All live sources failed — use the last known value if we have one.
    return cache.get(equity_symbol)


_LOW_CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "low52_cache.json"
_low52_cache: dict[str, float] | None = None


def _load_low52_cache() -> dict[str, float]:
    global _low52_cache
    if _low52_cache is None:
        try:
            raw = json.loads(_LOW_CACHE_FILE.read_text(encoding="utf-8"))
            _low52_cache = {str(k): float(v) for k, v in raw.items() if v}
        except Exception:
            _low52_cache = {}
    return _low52_cache


def _save_low52_cache() -> None:
    if _low52_cache is None:
        return
    try:
        _LOW_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LOW_CACHE_FILE.write_text(json.dumps(_low52_cache), encoding="utf-8")
    except Exception as exc:
        logger.debug("52w-low cache save failed: %s", exc)


def fetch_52week_low_sync(symbol: str, finnhub_api_key: str) -> float | None:
    """Return the 52-week low (Finnhub metric), cached to survive API hiccups."""
    equity_symbol = _normalize_equity_symbol(symbol)
    if not equity_symbol or not finnhub_api_key:
        return None
    cache = _load_low52_cache()
    url = (
        "https://finnhub.io/api/v1/stock/metric"
        f"?symbol={quote(equity_symbol)}&metric=all&token={quote(finnhub_api_key)}"
    )
    try:
        with urlopen(Request(url, headers={"User-Agent": "discord-news-bot/1.0"}), timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        metric = payload.get("metric") or {}
        raw = metric.get("52WeekLow")
        if raw is not None:
            value = float(raw)
            if value > 0:
                if cache.get(equity_symbol) != value:
                    cache[equity_symbol] = value
                    _save_low52_cache()
                return value
    except Exception as exc:
        logger.debug("Finnhub 52w-low fetch failed for %s: %s", equity_symbol, exc)
    return cache.get(equity_symbol)


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
        "CH": "🇨🇭",
        "SG": "🇸🇬",
    }
    return name, flags.get(country, "🇺🇸")
