from types import SimpleNamespace

from bot.trading.market_structure import MarketStructureSnapshot
from bot.trading.scanner import ScanResult
from bot.trading.scanner_gates import qualifies_scanner_alert


def _cfg(**overrides):
    base = dict(
        scanner_min_turnover_usd=1_000_000,
        scanner_premarket_min_turnover_usd=1_000_000,
        scanner_min_change_pct=10.0,
        scanner_min_range_pct=8.0,
        scanner_premarket_min_range_pct=8.0,
        scanner_max_market_cap_usd=3_000_000_000,
        scanner_gate_min_rvol=1.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _scan(**kwargs) -> ScanResult:
    defaults = dict(
        symbol="TEST",
        turnover_usd=1_500_000,
        session_change_pct=12.0,
        gap_pct=0.0,
        rvol=1.5,
        market_cap_usd=500_000_000,
        score=60,
        structure=MarketStructureSnapshot(session_high=11.0, session_low=10.0),
    )
    defaults.update(kwargs)
    return ScanResult(**defaults)


def test_qualifies_when_all_buyer_gates_pass():
    assert qualifies_scanner_alert(_scan(), _cfg(), min_score=50) is True


def test_rejects_low_turnover():
    assert qualifies_scanner_alert(_scan(turnover_usd=500_000), _cfg(), min_score=0) is False


def test_rejects_low_change_pct():
    assert qualifies_scanner_alert(_scan(session_change_pct=8.0), _cfg(), min_score=0) is False


def test_rejects_low_range():
    scan = _scan(structure=MarketStructureSnapshot(session_high=10.5, session_low=10.0))
    assert qualifies_scanner_alert(scan, _cfg(), min_score=0) is False


def test_rejects_large_cap():
    assert qualifies_scanner_alert(_scan(market_cap_usd=4_000_000_000), _cfg(), min_score=0) is False


def test_rejects_low_rvol():
    assert qualifies_scanner_alert(_scan(rvol=0.9), _cfg(), min_score=0) is False


def test_rejects_low_score():
    assert qualifies_scanner_alert(_scan(score=40), _cfg(), min_score=50) is False
