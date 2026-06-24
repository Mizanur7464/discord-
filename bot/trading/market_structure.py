"""Intraday market structure analysis."""

from __future__ import annotations

from dataclasses import dataclass

from bot.trading.indicators import Bar


@dataclass
class MarketStructureSnapshot:
    state: str = "unknown"
    quality_score: int = 0
    session_high: float | None = None
    session_low: float | None = None
    hod_break: bool = False
    distance_from_hod_pct: float | None = None
    higher_lows: bool = False
    lower_highs: bool = False

    @property
    def summary(self) -> str:
        parts = [self.state.replace("_", " ").title()]
        if self.hod_break:
            parts.append("HOD break")
        if self.distance_from_hod_pct is not None:
            parts.append(f"{self.distance_from_hod_pct:+.1f}% from HOD")
        if self.higher_lows:
            parts.append("higher lows")
        if self.lower_highs:
            parts.append("lower highs")
        return " · ".join(parts)


def analyze_market_structure(bars: list[Bar], *, current_price: float | None = None) -> MarketStructureSnapshot:
    if len(bars) < 10:
        return MarketStructureSnapshot(state="insufficient_data")

    price = current_price if current_price is not None else bars[-1].close
    session_high = max(bar.high for bar in bars)
    session_low = min(bar.low for bar in bars)
    distance_from_hod = None
    if session_high > 0:
        distance_from_hod = round((price / session_high - 1) * 100, 2)

    mid = len(bars) // 2
    first_half_low = min(bar.low for bar in bars[:mid])
    second_half_low = min(bar.low for bar in bars[mid:])
    first_half_high = max(bar.high for bar in bars[:mid])
    second_half_high = max(bar.high for bar in bars[mid:])
    higher_lows = second_half_low > first_half_low
    lower_highs = second_half_high < first_half_high

    recent_high = max(bar.high for bar in bars[-5:])
    prior_high = max(bar.high for bar in bars[-10:-5]) if len(bars) >= 10 else recent_high
    hod_break = recent_high > prior_high and price >= recent_high * 0.995

    if hod_break and higher_lows:
        state = "uptrend_breakout"
    elif higher_lows and not lower_highs:
        state = "uptrend"
    elif lower_highs and not higher_lows:
        state = "downtrend"
    else:
        state = "range"

    quality = 40
    if state in {"uptrend", "uptrend_breakout"}:
        quality += 25
    if hod_break:
        quality += 15
    if higher_lows:
        quality += 10
    if distance_from_hod is not None and distance_from_hod > -3:
        quality += 10
    if lower_highs:
        quality -= 15

    return MarketStructureSnapshot(
        state=state,
        quality_score=max(0, min(100, quality)),
        session_high=session_high,
        session_low=session_low,
        hod_break=hod_break,
        distance_from_hod_pct=distance_from_hod,
        higher_lows=higher_lows,
        lower_highs=lower_highs,
    )
