"""Multi-timeframe bar analysis (1m, 3m, 5m, 15m, 30m)."""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.trading.indicators import Bar, IndicatorSnapshot, compute_indicators


@dataclass
class TimeframeSnapshot:
    label: str
    bars: int
    trend: str = "neutral"
    change_pct: float | None = None
    volume_trend: str = "flat"
    indicators: IndicatorSnapshot | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class MultiTimeframeAnalysis:
    snapshots: dict[str, TimeframeSnapshot] = field(default_factory=dict)
    aligned_bullish: int = 0
    aligned_bearish: int = 0
    summary: str = ""

    @property
    def consensus(self) -> str:
        if self.aligned_bullish >= 3:
            return "bullish"
        if self.aligned_bearish >= 3:
            return "bearish"
        return "mixed"


def aggregate_bars(bars_1m: list[Bar], minutes: int) -> list[Bar]:
    if minutes <= 1:
        return list(bars_1m)
    grouped: list[Bar] = []
    chunk: list[Bar] = []
    for bar in bars_1m:
        chunk.append(bar)
        if len(chunk) == minutes:
            grouped.append(_merge_bars(chunk))
            chunk = []
    if chunk:
        grouped.append(_merge_bars(chunk))
    return grouped


def _merge_bars(chunk: list[Bar]) -> Bar:
    return Bar(
        open=chunk[0].open,
        high=max(bar.high for bar in chunk),
        low=min(bar.low for bar in chunk),
        close=chunk[-1].close,
        volume=sum(bar.volume for bar in chunk),
    )


def analyze_timeframe(bars: list[Bar], label: str, *, avg_volume: float | None = None) -> TimeframeSnapshot:
    snap = TimeframeSnapshot(label=label, bars=len(bars))
    if len(bars) < 2:
        snap.notes.append("insufficient bars")
        return snap

    first = bars[0].open or bars[0].close
    last = bars[-1].close
    if first > 0:
        snap.change_pct = round((last / first - 1) * 100, 2)

    if snap.change_pct is not None:
        if snap.change_pct >= 2:
            snap.trend = "bullish"
        elif snap.change_pct <= -2:
            snap.trend = "bearish"

    recent_vol = bars[-1].volume
    prior_vol = bars[-2].volume if len(bars) >= 2 else recent_vol
    if recent_vol > prior_vol * 1.2:
        snap.volume_trend = "rising"
    elif recent_vol < prior_vol * 0.8:
        snap.volume_trend = "falling"

    snap.indicators = compute_indicators(bars, avg_volume=avg_volume)
    if snap.indicators.price_above_vwap:
        snap.notes.append("above VWAP")
    if snap.volume_trend == "rising":
        snap.notes.append("volume rising")
    return snap


def analyze_multi_timeframe(
    bars_1m: list[Bar],
    *,
    avg_volume: float | None = None,
) -> MultiTimeframeAnalysis:
    analysis = MultiTimeframeAnalysis()
    if not bars_1m:
        analysis.summary = "no intraday bars"
        return analysis

    for minutes, label in ((1, "1m"), (3, "3m"), (5, "5m"), (15, "15m"), (30, "30m")):
        bars = aggregate_bars(bars_1m, minutes)
        if len(bars) < 2 and minutes > 1:
            continue
        snapshot = analyze_timeframe(bars, label, avg_volume=avg_volume)
        analysis.snapshots[label] = snapshot
        if snapshot.trend == "bullish":
            analysis.aligned_bullish += 1
        elif snapshot.trend == "bearish":
            analysis.aligned_bearish += 1

    consensus = analysis.consensus
    parts = [f"{label}:{snap.trend}" for label, snap in analysis.snapshots.items()]
    analysis.summary = f"{consensus} ({', '.join(parts)})"
    return analysis
