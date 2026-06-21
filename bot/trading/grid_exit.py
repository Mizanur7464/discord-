"""Flexible grid exit — volume-adjusted profit tiers for hold vs early sell."""

from __future__ import annotations

from dataclasses import dataclass

from bot.trading.exit_manager import ExitTier


@dataclass
class VolumeContext:
    daily_volume: int = 0
    avg_volume_30d: int = 0
    rvol: float | None = None
    recent_1m_volume: int = 0
    volume_trend: str = "flat"  # rising | falling | flat

    @property
    def trend_label(self) -> str:
        parts = [f"daily {self.daily_volume:,}"]
        if self.rvol is not None:
            parts.append(f"RVOL {self.rvol:.1f}x")
        parts.append(f"1m trend {self.volume_trend}")
        return ", ".join(parts)


def fetch_volume_context(data_client, symbol: str) -> VolumeContext:
    """Load daily + intraday volume stats for grid/AI exit decisions."""
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    ctx = VolumeContext()
    symbol = symbol.upper()

    try:
        daily = data_client.get_stock_bars(
            StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, limit=31)
        )
        if hasattr(daily, "data"):
            series = daily.data.get(symbol, [])
        else:
            series = daily[symbol]
        if series:
            ctx.daily_volume = int(series[-1].volume)
            if len(series) >= 2:
                avg_vals = [int(bar.volume) for bar in series[:-1][-30:]]
                ctx.avg_volume_30d = int(sum(avg_vals) / len(avg_vals)) if avg_vals else 0
            if ctx.avg_volume_30d > 0:
                ctx.rvol = round(ctx.daily_volume / ctx.avg_volume_30d, 2)
    except Exception:
        pass

    try:
        minute = data_client.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame(1, TimeFrameUnit.Minute),
                limit=8,
            )
        )
        if hasattr(minute, "data"):
            bars = minute.data.get(symbol, [])
        else:
            bars = minute[symbol]
        if bars:
            ctx.recent_1m_volume = int(bars[-1].volume)
            if len(bars) >= 4:
                recent = sum(int(b.volume) for b in bars[-3:]) / 3
                older = sum(int(b.volume) for b in bars[-6:-3]) / max(1, len(bars[-6:-3]))
                if recent > older * 1.15:
                    ctx.volume_trend = "rising"
                elif recent < older * 0.85:
                    ctx.volume_trend = "falling"
    except Exception:
        pass

    return ctx


def adjust_tier_threshold(
    tier: ExitTier,
    ctx: VolumeContext,
    *,
    rvol_strong: float,
    rvol_weak: float,
    adjust_percent: float,
) -> float:
    """Shift grid tier up (hold longer) or down (sell earlier) based on volume."""
    threshold = tier.profit_percent
    delta = max(0.0, adjust_percent)

    if ctx.rvol is not None and ctx.rvol >= rvol_strong and ctx.volume_trend == "rising":
        return threshold + delta
    if ctx.rvol is not None and ctx.rvol <= rvol_weak:
        return max(1.0, threshold - delta)
    if ctx.volume_trend == "falling":
        return max(1.0, threshold - delta * 0.6)
    if ctx.volume_trend == "rising" and ctx.rvol is not None and ctx.rvol >= rvol_weak:
        return threshold + delta * 0.4
    return threshold


def build_adjusted_tiers(
    tiers: list[ExitTier],
    ctx: VolumeContext,
    *,
    rvol_strong: float,
    rvol_weak: float,
    adjust_percent: float,
) -> list[tuple[int, ExitTier, float]]:
    """Return (index, tier, adjusted_profit_percent) for each grid level."""
    adjusted: list[tuple[int, ExitTier, float]] = []
    for idx, tier in enumerate(tiers):
        level = adjust_tier_threshold(
            tier,
            ctx,
            rvol_strong=rvol_strong,
            rvol_weak=rvol_weak,
            adjust_percent=adjust_percent,
        )
        adjusted.append((idx, tier, level))
    return adjusted
