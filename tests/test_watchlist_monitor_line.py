from bot.trading.scanner import ScanResult
from bot.discord_bot.watchlist_monitor_line import build_watchlist_monitor_line


def _scan(**kwargs) -> ScanResult:
    return ScanResult(**kwargs)


def test_watchlist_monitor_line_nb_style():
    scan = _scan(
        symbol="NTCL",
        price=0.42,
        session_change_pct=27.0,
        float_shares=11_800_000,
        current_rvol=40,
        daily_volume=4_800_000,
        liquidity_rank=2,
        mosquito_nhod=True,
        score=78,
        grade="B",
    )
    line = build_watchlist_monitor_line(scan, country_flag="🇸🇬")
    assert "**NTCL**" in line
    assert "< $.50c" in line
    assert "27%" in line
    assert "`NHOD`" in line
    assert "🇸🇬" in line
    assert "**Float:** 11.8 M" in line
    assert "**RVol:** 40x" in line
    assert "**Score:**" in line
