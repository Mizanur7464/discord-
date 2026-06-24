"""Intraday bar metrics for SPM-style mosquito alerts."""

from __future__ import annotations

from dataclasses import dataclass

from bot.trading.indicators import Bar


@dataclass
class MosquitoBarMetrics:
    volume_1m: int | None = None
    volume_2m: int | None = None
    volume_5m: int | None = None
    nhod: bool = False
    nlod: bool = False


def compute_mosquito_bar_metrics(bars: list[Bar], *, price: float | None = None) -> MosquitoBarMetrics:
    if not bars:
        return MosquitoBarMetrics()

    metrics = MosquitoBarMetrics(
        volume_1m=int(bars[-1].volume),
        volume_2m=int(sum(bar.volume for bar in bars[-2:])),
        volume_5m=int(sum(bar.volume for bar in bars[-5:])),
    )

    if len(bars) < 2:
        return metrics

    prior_high = max(bar.high for bar in bars[:-1])
    prior_low = min(bar.low for bar in bars[:-1])
    last = bars[-1]
    px = price if price is not None else last.close

    metrics.nhod = last.high > prior_high and px >= prior_high * 0.995
    metrics.nlod = last.low < prior_low and px <= prior_low * 1.005
    return metrics
