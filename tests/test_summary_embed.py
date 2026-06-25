from bot.discord_bot.summary_embed import build_live_summary_embed, _top_gainers
from bot.trading.scanner import ScanResult


def _scan(symbol: str, pct: float, score: int = 60) -> ScanResult:
    return ScanResult(symbol=symbol, session_change_pct=pct, score=score, grade="B")


def test_top_gainers_limit_and_sort():
    scans = [_scan("AAA", 5), _scan("BBB", 20), _scan("CCC", -1), _scan("DDD", 12)]
    gainers = _top_gainers(scans, limit=2)
    assert [scan.symbol for scan in gainers] == ["BBB", "DDD"]


def test_live_summary_embed_footer():
    embed = build_live_summary_embed([_scan("AAA", 10)], top_limit=15)
    assert embed.title == "📊 Top Gainers (Live)"
    assert "**AAA**" in embed.description
    assert "Last update:" in embed.footer.text
