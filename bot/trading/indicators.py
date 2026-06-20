"""Technical indicators for scanner scoring."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class IndicatorSnapshot:
    ma_fast: float | None = None
    ma_slow: float | None = None
    boll_upper: float | None = None
    boll_mid: float | None = None
    boll_lower: float | None = None
    mavol: float | None = None
    rvol: float | None = None
    vwap: float | None = None
    kdj_k: float | None = None
    kdj_d: float | None = None
    kdj_j: float | None = None
    price_above_vwap: bool | None = None
    price_above_ma_fast: bool | None = None
    bullish_signals: list[str] = field(default_factory=list)
    bearish_signals: list[str] = field(default_factory=list)


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    window = values[-period:]
    return sum(window) / period


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    multiplier = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    for price in values[period:]:
        ema_val = (price - ema_val) * multiplier + ema_val
    return ema_val


def bollinger_bands(
    closes: list[float],
    period: int = 20,
    std_mult: float = 2.0,
) -> tuple[float | None, float | None, float | None]:
    mid = sma(closes, period)
    if mid is None or len(closes) < period:
        return None, None, None
    window = closes[-period:]
    variance = sum((value - mid) ** 2 for value in window) / period
    std = math.sqrt(variance)
    return mid + std_mult * std, mid, mid - std_mult * std


def vwap(bars: list[Bar]) -> float | None:
    if not bars:
        return None
    total_pv = 0.0
    total_volume = 0.0
    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / 3
        total_pv += typical * bar.volume
        total_volume += bar.volume
    if total_volume <= 0:
        return None
    return total_pv / total_volume


def kdj(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 9,
) -> tuple[float | None, float | None, float | None]:
    if len(closes) < period:
        return None, None, None
    recent_high = max(highs[-period:])
    recent_low = min(lows[-period:])
    if recent_high == recent_low:
        rsv = 50.0
    else:
        rsv = (closes[-1] - recent_low) / (recent_high - recent_low) * 100

    k_values: list[float] = []
    d_values: list[float] = []
    prev_k = 50.0
    prev_d = 50.0
    for idx in range(period - 1, len(closes)):
        window_high = max(highs[idx - period + 1 : idx + 1])
        window_low = min(lows[idx - period + 1 : idx + 1])
        if window_high == window_low:
            rsv_i = 50.0
        else:
            rsv_i = (closes[idx] - window_low) / (window_high - window_low) * 100
        prev_k = (2 / 3) * prev_k + (1 / 3) * rsv_i
        prev_d = (2 / 3) * prev_d + (1 / 3) * prev_k
        k_values.append(prev_k)
        d_values.append(prev_d)

    if not k_values:
        return None, None, None
    k_val = k_values[-1]
    d_val = d_values[-1]
    j_val = 3 * k_val - 2 * d_val
    return k_val, d_val, j_val


def compute_indicators(bars: list[Bar], *, avg_volume: float | None = None) -> IndicatorSnapshot:
    if not bars:
        return IndicatorSnapshot()

    closes = [bar.close for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    volumes = [bar.volume for bar in bars]
    price = closes[-1]

    snap = IndicatorSnapshot(
        ma_fast=sma(closes, 9),
        ma_slow=sma(closes, 21),
        mavol=sma(volumes, 20),
        vwap=vwap(bars),
        rvol=(volumes[-1] / avg_volume) if avg_volume and avg_volume > 0 else None,
    )
    upper, mid, lower = bollinger_bands(closes, period=min(20, len(closes)))
    snap.boll_upper, snap.boll_mid, snap.boll_lower = upper, mid, lower
    snap.kdj_k, snap.kdj_d, snap.kdj_j = kdj(highs, lows, closes, period=min(9, len(closes)))

    if snap.vwap is not None:
        snap.price_above_vwap = price >= snap.vwap
        if snap.price_above_vwap:
            snap.bullish_signals.append("price above VWAP")
        else:
            snap.bearish_signals.append("price below VWAP")

    if snap.ma_fast is not None:
        snap.price_above_ma_fast = price >= snap.ma_fast
        if snap.price_above_ma_fast:
            snap.bullish_signals.append("price above MA9")
        else:
            snap.bearish_signals.append("price below MA9")

    if snap.ma_fast is not None and snap.ma_slow is not None:
        if snap.ma_fast > snap.ma_slow:
            snap.bullish_signals.append("MA9 > MA21")
        else:
            snap.bearish_signals.append("MA9 < MA21")

    if snap.boll_mid is not None and price > snap.boll_mid:
        snap.bullish_signals.append("price above Bollinger mid")
    if snap.kdj_k is not None and snap.kdj_d is not None:
        if snap.kdj_k > snap.kdj_d and snap.kdj_k < 80:
            snap.bullish_signals.append("KDJ bullish crossover")
        elif snap.kdj_k > 85:
            snap.bearish_signals.append("KDJ overbought")

    if snap.mavol is not None and volumes[-1] > snap.mavol * 1.5:
        snap.bullish_signals.append("volume above MAVOL")

    return snap
