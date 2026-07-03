from bot.discord_bot.summary_embed import build_gainer_table_rows
from bot.discord_bot.summary_publisher import SummaryPublisher
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
    rows = build_gainer_table_rows(pub._effective_scans(), top_limit=pub.top_limit)
    assert rows[0][0] == "AAA"

    pub.update_scans([_scan("CCC", -3.0)])
    rows = build_gainer_table_rows(
        pub._effective_scans(),
        top_limit=pub.top_limit,
        preserve_order=pub._market_ordered,
    )
    assert rows[0][0] == "AAA"
    assert pub._build_table_file() is not None
    assert "**Top Gainers" in pub._build_header() or "Top Gainers" in pub._build_header()
    assert "Updated:" in pub._build_footer()
    assert "**News Types Key:**" in pub._build_footer()


def test_new_mover_replaces_previous():
    pub = SummaryPublisher()
    pub.update_scans([_scan("AAA", 12.0)])
    pub.update_scans([_scan("ZZZ", 20.0)])
    rows = build_gainer_table_rows(pub._effective_scans(), top_limit=pub.top_limit)
    assert rows[0][0] == "ZZZ"
    assert "AAA" not in [row[0] for row in rows]
