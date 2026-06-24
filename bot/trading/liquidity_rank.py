"""Cross-symbol liquidity ranking for scanner batches."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.trading.scanner import ScanResult


def _grade_from_score(score: int) -> str:
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def apply_liquidity_ranks(scans: list[ScanResult]) -> None:
    if not scans:
        return
    ranked = sorted(scans, key=lambda scan: scan.turnover_usd or 0, reverse=True)
    total = len(ranked)
    top_turnover = ranked[0].turnover_usd or 1
    for index, scan in enumerate(ranked):
        scan.liquidity_rank = index + 1
        scan.liquidity_percentile = round((1 - index / total) * 100) if total else 0
        turnover = scan.turnover_usd or 0
        scan.liquidity_score = min(100, round(turnover / top_turnover * 100))
        if scan.liquidity_rank <= 5:
            scan.score = min(100, scan.score + 6)
            scan.reasons.append(f"liquidity rank #{scan.liquidity_rank}")
            scan.grade = _grade_from_score(scan.score)


def apply_peak_rvol_ranks(scans: list[ScanResult]) -> None:
    if not scans:
        return
    ranked = sorted(scans, key=lambda scan: scan.peak_rvol or 0, reverse=True)
    for index, scan in enumerate(ranked):
        if scan.peak_rvol and scan.peak_rvol > 0:
            scan.peak_rvol_rank = index + 1
