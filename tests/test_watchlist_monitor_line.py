from bot.news.benzinga import CatalystResult
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
    assert "[Link]" not in line


def test_watchlist_monitor_line_nb_arrangement_score_at_back():
    scan = _scan(
        symbol="WYY",
        price=6.5,
        session_change_pct=12.0,
        float_shares=2_000_000,
        daily_volume=1_000_000,
        score=85,
        grade="A",
    )
    line = build_watchlist_monitor_line(scan)
    # NB-style arrangement: Float/RVol/Vol up front, our Score at the very back.
    assert line.rstrip().endswith("**Score:** A 85/100")
    # NB format does not include our extra SI / HOD / Theme fields.
    assert "SI:" not in line
    assert "from **HOD**" not in line
    assert "Theme:" not in line


def test_watchlist_monitor_line_boxes_important_values():
    scan = _scan(symbol="HKIT", price=0.42, session_change_pct=48.0, score=60, grade="C")
    line = build_watchlist_monitor_line(scan)
    # Important values rendered in `code` boxes like NB.
    assert "`< $.50c`" in line
    assert "`48%`" in line


def test_watchlist_monitor_line_52w_low():
    scan = _scan(symbol="WYY", price=6.5, session_change_pct=12.0, score=70, grade="B")
    line = build_watchlist_monitor_line(scan, pct_from_52w_low=31.2)
    assert "`+31.2% from 52W-Low`" in line


def test_watchlist_monitor_line_sec_tag():
    scan = _scan(
        symbol="ABCD",
        price=3.0,
        session_change_pct=9.0,
        score=70,
        grade="B",
        catalyst=CatalystResult(symbol="ABCD", headline="Company files Form 8-K with the SEC"),
    )
    line = build_watchlist_monitor_line(scan)
    assert "`SEC`" in line


def test_watchlist_monitor_line_turnover():
    scan = _scan(
        symbol="WYY",
        price=6.5,
        session_change_pct=12.0,
        turnover_usd=1_250_000,
        score=70,
        grade="B",
    )
    line = build_watchlist_monitor_line(scan)
    assert "**Turnover:** $1.2 M" in line


def test_watchlist_monitor_line_blue_text_link():
    scan = _scan(symbol="WYY", price=6.5, session_change_pct=12.0, score=70, grade="B")
    line = build_watchlist_monitor_line(
        scan,
        news_url="http://82.197.66.62:8787/n/12345",
    )
    assert " - [Link](http://82.197.66.62:8787/n/12345)" in line
