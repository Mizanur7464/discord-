"""Volume, RVOL, turnover and price expansion metrics."""

from __future__ import annotations

from dataclasses import dataclass

from bot.trading.indicators import Bar, sma


@dataclass
class ExpansionMetrics:
    intraday_rvol: float | None = None
    rvol_expansion_pct: float | None = None
    volume_expansion_pct: float | None = None
    turnover_expansion_pct: float | None = None
    price_acceleration_pct: float | None = None
    liquidity_expansion_score: int = 0
    bollinger_bandwidth_pct: float | None = None

    @property
    def summary(self) -> str:
        parts: list[str] = []
        if self.intraday_rvol is not None:
            parts.append(f"RVOL {self.intraday_rvol:.1f}x")
        if self.rvol_expansion_pct is not None:
            parts.append(f"RVOL exp {self.rvol_expansion_pct:+.0f}%")
        if self.volume_expansion_pct is not None:
            parts.append(f"Vol exp {self.volume_expansion_pct:+.0f}%")
        if self.price_acceleration_pct is not None:
            parts.append(f"Accel {self.price_acceleration_pct:+.1f}%")
        return " · ".join(parts) if parts else "—"


def compute_expansion_metrics(
    bars: list[Bar],
    *,
    daily_rvol: float | None,
    avg_volume: float | None,
    turnover_usd: float | None,
    price: float | None,
) -> ExpansionMetrics:
    if not bars:
        return ExpansionMetrics()

    volumes = [bar.volume for bar in bars]
    closes = [bar.close for bar in bars]
    metrics = ExpansionMetrics()

    if avg_volume and avg_volume > 0:
        metrics.intraday_rvol = round(volumes[-1] / avg_volume, 2)

    mavol = sma(volumes, min(20, len(volumes)))
    if mavol and mavol > 0:
        metrics.volume_expansion_pct = round((volumes[-1] / mavol - 1) * 100, 1)

    if len(volumes) >= 10:
        early = sum(volumes[:5]) / 5
        late = sum(volumes[-5:]) / 5
        if early > 0:
            metrics.turnover_expansion_pct = round((late / early - 1) * 100, 1)

    if len(closes) >= 10:
        prev_change = (closes[-5] / closes[-10] - 1) * 100 if closes[-10] else 0
        recent_change = (closes[-1] / closes[-5] - 1) * 100 if closes[-5] else 0
        metrics.price_acceleration_pct = round(recent_change - prev_change, 2)

    rvol_now = metrics.intraday_rvol or daily_rvol
    if len(volumes) >= 6 and avg_volume and avg_volume > 0:
        prior_rvol = volumes[-6] / avg_volume
        if prior_rvol > 0 and rvol_now is not None:
            metrics.rvol_expansion_pct = round((rvol_now / prior_rvol - 1) * 100, 1)

    if len(closes) >= 20:
        window = closes[-20:]
        mid = sum(window) / len(window)
        variance = sum((value - mid) ** 2 for value in window) / len(window)
        import math

        std = math.sqrt(variance)
        if mid > 0:
            metrics.bollinger_bandwidth_pct = round((2 * std / mid) * 100, 2)

    score = 0
    if rvol_now is not None and rvol_now >= 2:
        score += 20
    if metrics.volume_expansion_pct is not None and metrics.volume_expansion_pct > 25:
        score += 20
    if metrics.turnover_expansion_pct is not None and metrics.turnover_expansion_pct > 20:
        score += 15
    if metrics.price_acceleration_pct is not None and metrics.price_acceleration_pct > 1:
        score += 20
    if metrics.rvol_expansion_pct is not None and metrics.rvol_expansion_pct > 15:
        score += 15
    if turnover_usd and turnover_usd >= 1_000_000:
        score += 10
    metrics.liquidity_expansion_score = min(100, score)
    return metrics
