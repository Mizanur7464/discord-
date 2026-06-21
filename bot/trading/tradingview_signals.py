"""TradingView indicator signals via tradingview-ta library."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TradingViewSnapshot:
    symbol: str
    exchange: str = "NASDAQ"
    recommendation: str = "NEUTRAL"
    buy_signals: int = 0
    sell_signals: int = 0
    neutral_signals: int = 0
    indicators: dict[str, str] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        return f"{self.recommendation} (buy {self.buy_signals}/sell {self.sell_signals})"


def fetch_tradingview_analysis(
    symbol: str,
    *,
    exchange: str = "NASDAQ",
    screener: str = "america",
    interval: str = "5m",
) -> TradingViewSnapshot | None:
    try:
        from tradingview_ta import Interval, TA_Handler
    except ImportError:
        logger.warning("tradingview-ta not installed — pip install tradingview-ta")
        return None

    interval_map = {
        "1m": Interval.INTERVAL_1_MINUTE,
        "5m": Interval.INTERVAL_5_MINUTES,
        "15m": Interval.INTERVAL_15_MINUTES,
        "30m": Interval.INTERVAL_30_MINUTES,
        "1h": Interval.INTERVAL_1_HOUR,
        "1d": Interval.INTERVAL_1_DAY,
    }
    tv_interval = interval_map.get(interval, Interval.INTERVAL_5_MINUTES)
    try:
        handler = TA_Handler(
            symbol=symbol.upper(),
            exchange=exchange,
            screener=screener,
            interval=tv_interval,
        )
        analysis = handler.get_analysis()
    except Exception as exc:
        logger.warning("TradingView TA failed for %s: %s", symbol, exc)
        return None

    summary = analysis.summary if hasattr(analysis, "summary") else {}
    indicators = analysis.indicators if hasattr(analysis, "indicators") else {}
    snap = TradingViewSnapshot(
        symbol=symbol.upper(),
        exchange=exchange,
        recommendation=str(summary.get("RECOMMENDATION", "NEUTRAL")),
        buy_signals=int(summary.get("BUY", 0) or 0),
        sell_signals=int(summary.get("SELL", 0) or 0),
        neutral_signals=int(summary.get("NEUTRAL", 0) or 0),
    )
    for key in ("RSI", "MACD.macd", "Stoch.K", "ADX", "BB.upper", "BB.lower", "VWMA"):
        if key in indicators and indicators[key] is not None:
            snap.indicators[key] = str(indicators[key])
    return snap


def score_tradingview(snap: TradingViewSnapshot | None) -> tuple[int, list[str], list[str]]:
    if not snap:
        return 0, [], []
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []
    rec = snap.recommendation.upper()
    if rec in ("STRONG_BUY", "BUY"):
        score += 8
        reasons.append(f"TradingView {rec}")
    elif rec == "NEUTRAL":
        score += 2
    elif rec in ("SELL", "STRONG_SELL"):
        score -= 6
        warnings.append(f"TradingView {rec}")
    if snap.buy_signals > snap.sell_signals + 3:
        score += 4
        reasons.append(f"TV buy signals {snap.buy_signals} vs sell {snap.sell_signals}")
    return score, reasons, warnings
