from bot.discord_bot.summary_publisher import SummaryPublisher
from bot.news.benzinga import CatalystResult  # noqa: F401  (kept for parity)
from bot.trading.scanner import ScanResult


def _scan(symbol: str, pct: float) -> ScanResult:
    return ScanResult(
        symbol=symbol,
        session_change_pct=pct,
        price=10.0,
        daily_volume=250_000,
        catalyst_label="Earnings",
        score=80,
        grade="A",
    )


def test_keeps_previous_movers_when_market_goes_quiet():
    pub = SummaryPublisher()
    pub.update_scans([_scan("AAA", 12.0), _scan("BBB", 8.0)])
    assert "AAA" in pub._build_content()

    # Next scan has no positive movers — board should still show AAA/BBB.
    pub.update_scans([_scan("CCC", -3.0)])
    content = pub._build_content()
    assert "AAA" in content
    assert "No positive movers" not in content


def test_new_mover_replaces_previous():
    pub = SummaryPublisher()
    pub.update_scans([_scan("AAA", 12.0)])
    pub.update_scans([_scan("ZZZ", 20.0)])
    content = pub._build_content()
    assert "ZZZ" in content
