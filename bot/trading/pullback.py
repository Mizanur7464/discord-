"""Pullback entry logic — avoid chasing extended moves."""

from __future__ import annotations

from dataclasses import dataclass

from bot.trading.indicators import Bar


@dataclass
class PullbackSetup:
    current_price: float
    recent_high: float
    recent_low: float
    extension_pct: float
    pullback_pct: float
    suggested_limit: float
    is_chasing: bool
    ready_to_enter: bool
    note: str

    @property
    def summary(self) -> str:
        state = "chasing — wait for pullback" if self.is_chasing else "pullback zone"
        return (
            f"{state} | high ${self.recent_high:.2f} | "
            f"suggested limit ${self.suggested_limit:.2f} | {self.note}"
        )


def analyze_pullback(
    bars: list[Bar],
    current_price: float,
    *,
    lookback_bars: int = 30,
    pullback_percent: float = 3.0,
    max_chase_percent: float = 2.0,
    limit_buffer_percent: float = 0.5,
) -> PullbackSetup | None:
    if not bars or current_price <= 0:
        return None

    window = bars[-lookback_bars:] if len(bars) >= lookback_bars else bars
    recent_high = max(bar.high for bar in window)
    recent_low = min(bar.low for bar in window)
    if recent_high <= 0:
        return None

    extension_pct = (current_price / recent_high - 1) * 100
    pullback_level = recent_high * (1 - pullback_percent / 100)
    buffer = max(0.0, limit_buffer_percent) / 100
    suggested_limit = round(pullback_level * (1 + buffer), 4 if pullback_level < 1 else 2)

    is_chasing = extension_pct >= -max_chase_percent
    ready = current_price <= pullback_level * (1 + buffer)

    if is_chasing and not ready:
        note = f"price within {max_chase_percent:g}% of recent high — wait for pullback"
    elif ready:
        note = "price reached pullback zone"
    else:
        note = "below recent high — limit entry available"

    return PullbackSetup(
        current_price=current_price,
        recent_high=recent_high,
        recent_low=recent_low,
        extension_pct=round(extension_pct, 2),
        pullback_pct=pullback_percent,
        suggested_limit=suggested_limit,
        is_chasing=is_chasing and not ready,
        ready_to_enter=ready or not is_chasing,
        note=note,
    )
