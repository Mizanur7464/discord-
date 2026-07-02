"""Scanner alert qualification gates (buyer liquidity focus)."""

from __future__ import annotations

from bot.trading.scanner import ScanResult
from bot.trading.schedule import is_regular_market_hours
from bot.utils.config import TradingConfig


def total_change_pct(scan: ScanResult) -> float | None:
    """Total move from previous close (gap + session compound)."""
    if scan.gap_pct is not None and scan.session_change_pct is not None:
        return round(
            ((1 + scan.gap_pct / 100) * (1 + scan.session_change_pct / 100) - 1) * 100,
            2,
        )
    if scan.gap_pct is not None:
        return scan.gap_pct
    return scan.session_change_pct


def session_range_pct(scan: ScanResult) -> float | None:
    structure = scan.structure
    if not structure or structure.session_high is None or structure.session_low is None:
        return None
    low = structure.session_low
    if low <= 0:
        return None
    return round((structure.session_high - low) / low * 100, 2)


def meets_turnover_threshold(scan: ScanResult, cfg: TradingConfig) -> bool:
    """Pre-market and regular session turnover must clear the buyer floor."""
    if is_regular_market_hours():
        min_turnover = cfg.scanner_min_turnover_usd
    else:
        min_turnover = getattr(cfg, "scanner_premarket_min_turnover_usd", 0) or 0
    if min_turnover <= 0:
        return True
    return scan.turnover_usd is not None and scan.turnover_usd >= min_turnover


def qualifies_scanner_alert(
    scan: ScanResult,
    cfg: TradingConfig,
    *,
    min_score: int = 0,
) -> bool:
    """Buyer scanner gates: turnover, chg%, range, MC, session RVOL, score."""
    if not meets_turnover_threshold(scan, cfg):
        return False

    min_change = getattr(cfg, "scanner_min_change_pct", 0) or 0
    if min_change > 0:
        change_pct = total_change_pct(scan)
        if change_pct is None or change_pct < min_change:
            return False

    min_range = getattr(cfg, "scanner_min_range_pct", None)
    if min_range is None:
        min_range = getattr(cfg, "scanner_premarket_min_range_pct", 8.0) or 0
    if min_range > 0:
        range_pct = session_range_pct(scan)
        if range_pct is None or range_pct < min_range:
            return False

    max_cap = getattr(cfg, "scanner_max_market_cap_usd", 0) or 0
    if max_cap > 0 and scan.market_cap_usd is not None and scan.market_cap_usd >= max_cap:
        return False

    min_rvol = getattr(cfg, "scanner_gate_min_rvol", 1.0) or 0
    if min_rvol > 0:
        if scan.rvol is None or scan.rvol <= min_rvol:
            return False

    if min_score > 0 and scan.score < min_score:
        return False
    return True
