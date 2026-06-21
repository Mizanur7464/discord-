"""Tape reading, quote spread, and short-interest proxies."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import quote

logger = logging.getLogger(__name__)


@dataclass
class MicrostructureSnapshot:
    symbol: str
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    tape_bias: str = "neutral"
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    spread_pct: float | None = None
    book_imbalance: float | None = None
    short_interest_pct: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"tape {self.tape_bias}"]
        if self.spread_pct is not None:
            parts.append(f"spread {self.spread_pct:.2f}%")
        if self.book_imbalance is not None:
            parts.append(f"L2 imbalance {self.book_imbalance:+.0f}%")
        if self.short_interest_pct is not None:
            parts.append(f"short {self.short_interest_pct:.1f}%")
        return " | ".join(parts)


def analyze_quote_spread(bid: float | None, ask: float | None) -> tuple[float | None, list[str]]:
    notes: list[str] = []
    if not bid or not ask or bid <= 0 or ask <= 0:
        return None, notes
    mid = (bid + ask) / 2
    spread_pct = (ask - bid) / mid * 100 if mid > 0 else None
    if spread_pct is not None and spread_pct <= 1.0:
        notes.append("tight spread")
    elif spread_pct is not None and spread_pct > 3.0:
        notes.append("wide spread — low liquidity")
    return spread_pct, notes


def analyze_recent_trades(trades) -> tuple[float, float, str]:
    buy_volume = 0.0
    sell_volume = 0.0
    prev_price: float | None = None
    for trade in trades:
        price = float(getattr(trade, "price", 0) or 0)
        size = float(getattr(trade, "size", 0) or getattr(trade, "volume", 0) or 0)
        if price <= 0 or size <= 0:
            continue
        if prev_price is None:
            buy_volume += size
        elif price >= prev_price:
            buy_volume += size
        else:
            sell_volume += size
        prev_price = price
    total = buy_volume + sell_volume
    if total <= 0:
        return 0.0, 0.0, "neutral"
    ratio = buy_volume / total
    if ratio >= 0.6:
        return buy_volume, sell_volume, "buyers"
    if ratio <= 0.4:
        return buy_volume, sell_volume, "sellers"
    return buy_volume, sell_volume, "neutral"


def fetch_short_interest_sync(symbol: str, finnhub_api_key: str) -> float | None:
    if not finnhub_api_key:
        return None
    try:
        import json
        import urllib.request

        url = (
            "https://finnhub.io/api/v1/stock/short-interest"
            f"?symbol={quote(symbol.upper())}&token={quote(finnhub_api_key)}"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        data = payload.get("data") if isinstance(payload, dict) else None
        if not data:
            return None
        latest = data[-1]
        short_pct = latest.get("shortInterestRatio") or latest.get("shortPercent")
        if short_pct is None:
            return None
        return float(short_pct)
    except Exception as exc:
        logger.warning("Short interest lookup failed for %s: %s", symbol, exc)
        return None


def analyze_microstructure(
    data_client,
    symbol: str,
    *,
    finnhub_api_key: str = "",
    trade_limit: int = 100,
) -> MicrostructureSnapshot:
    from alpaca.data.requests import StockLatestQuoteRequest, StockTradesRequest
    from datetime import datetime, timedelta, timezone

    symbol = symbol.upper()
    snap = MicrostructureSnapshot(symbol=symbol)

    try:
        quote = data_client.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbol)
        )[symbol]
        snap.bid = float(quote.bid_price) if quote.bid_price else None
        snap.ask = float(quote.ask_price) if quote.ask_price else None
        snap.bid_size = float(quote.bid_size) if getattr(quote, "bid_size", None) else None
        snap.ask_size = float(quote.ask_size) if getattr(quote, "ask_size", None) else None
        snap.spread_pct, spread_notes = analyze_quote_spread(snap.bid, snap.ask)
        snap.notes.extend(spread_notes)
        if snap.bid_size and snap.ask_size and (snap.bid_size + snap.ask_size) > 0:
            snap.book_imbalance = (snap.bid_size - snap.ask_size) / (snap.bid_size + snap.ask_size) * 100
            if snap.book_imbalance >= 20:
                snap.notes.append("Level 2 bid-side imbalance")
            elif snap.book_imbalance <= -20:
                snap.notes.append("Level 2 ask-side pressure")
    except Exception as exc:
        logger.warning("Quote lookup failed for %s: %s", symbol, exc)

    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=15)
        trades_resp = data_client.get_stock_trades(
            StockTradesRequest(symbol_or_symbols=symbol, start=start, end=end, limit=trade_limit)
        )
        if hasattr(trades_resp, "data"):
            series = trades_resp.data.get(symbol, [])
        else:
            series = trades_resp.get(symbol, [])
        buy_vol, sell_vol, bias = analyze_recent_trades(series)
        snap.buy_volume = buy_vol
        snap.sell_volume = sell_vol
        snap.tape_bias = bias
        if bias == "buyers":
            snap.notes.append("tape shows buyer aggression")
        elif bias == "sellers":
            snap.notes.append("tape shows seller pressure")
    except Exception as exc:
        logger.warning("Tape lookup failed for %s: %s", symbol, exc)

    snap.short_interest_pct = fetch_short_interest_sync(symbol, finnhub_api_key)
    if snap.short_interest_pct is not None and snap.short_interest_pct >= 15:
        snap.notes.append("elevated short interest")

    return snap


def score_microstructure(snap: MicrostructureSnapshot | None) -> tuple[int, list[str], list[str]]:
    if not snap:
        return 0, [], []
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []
    if snap.tape_bias == "buyers":
        score += 6
        reasons.append("tape reading: buyer aggression")
    elif snap.tape_bias == "sellers":
        score -= 4
        warnings.append("tape reading: seller pressure")
    if snap.spread_pct is not None and snap.spread_pct <= 1.0:
        score += 3
        reasons.append("tight bid/ask spread")
    elif snap.spread_pct is not None and snap.spread_pct > 3.0:
        warnings.append("wide spread — liquidity risk")
    if snap.short_interest_pct is not None and snap.short_interest_pct >= 15:
        score += 4
        reasons.append(f"short interest {snap.short_interest_pct:.1f}%")
    if snap.book_imbalance is not None and snap.book_imbalance >= 15:
        score += 4
        reasons.append(f"L2 bid imbalance {snap.book_imbalance:.0f}%")
    elif snap.book_imbalance is not None and snap.book_imbalance <= -15:
        score -= 3
        warnings.append(f"L2 ask pressure {snap.book_imbalance:.0f}%")
    for note in snap.notes[:2]:
        if note not in reasons and note not in warnings:
            reasons.append(note)
    return score, reasons, warnings
