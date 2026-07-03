from datetime import datetime
from zoneinfo import ZoneInfo

from bot.discord_bot.summary_embed import (
    _relative_updated,
    _short_news_label,
    _top_gainers,
    build_gainer_table_rows,
    build_live_summary_message,
)
from bot.news.benzinga import CatalystResult
from bot.trading.scanner import ScanResult

_ET = ZoneInfo("America/New_York")


def _scan(
    symbol: str,
    pct: float,
    *,
    price: float = 10.0,
    volume: int = 250_000,
    float_shares: float = 12_500_000,
    catalyst_label: str = "Earnings",
    catalyst: CatalystResult | None = None,
    news_bullish: bool = False,
) -> ScanResult:
    return ScanResult(
        symbol=symbol,
        session_change_pct=pct,
        price=price,
        daily_volume=volume,
        float_shares=float_shares,
        catalyst_label=catalyst_label,
        catalyst=catalyst,
        news_bullish=news_bullish,
        score=80,
        grade="A",
    )


def test_top_gainers_limit_and_sort():
    scans = [_scan("AAA", 5), _scan("BBB", 20), _scan("CCC", -1), _scan("DDD", 12)]
    gainers = _top_gainers(scans, limit=2)
    assert [scan.symbol for scan in gainers] == ["BBB", "DDD"]


def test_gainer_table_rows_include_all_columns():
    rows = build_gainer_table_rows(
        [_scan("WYY", 68.7, price=29.48, volume=86_200, catalyst_label="Earnings")],
    )
    assert rows == [["WYY", "29.48", "68.7", "86 k", "12.5m", "PR*"]]


def test_live_summary_message_is_caption_only():
    now = datetime(2026, 6, 25, 8, 30, tzinfo=_ET)
    message = build_live_summary_message(
        [_scan("WYY", 68.7, price=29.48, volume=86_200, catalyst_label="Earnings")],
        top_limit=15,
        updated_at=now,
        data_updated_at=now,
    )
    assert "**Top Gainers ☕ Pre-Market**" in message
    assert "Updated: just now" in message
    assert "**News Types Key:**" in message
    assert "PR - Press Release" in message
    assert "| Symbol |" not in message


def test_short_news_label_maps_nb_codes():
    assert _short_news_label(_scan("X", 1, catalyst_label="Earnings")) == "PR*"
    assert _short_news_label(
        _scan(
            "X",
            1,
            catalyst=CatalystResult(symbol="X", headline="Analyst upgrades shares to buy"),
        )
    ) == "AR"
    assert _short_news_label(
        _scan(
            "X",
            1,
            catalyst=CatalystResult(symbol="X", headline="Company files Form 8-K with the SEC"),
        )
    ) == "SF"
    assert _short_news_label(_scan("X", 1, catalyst_label="Partnership")) == "PR"


def test_relative_updated_minutes():
    now = datetime(2026, 6, 25, 9, 0, tzinfo=_ET)
    earlier = datetime(2026, 6, 25, 8, 58, tzinfo=_ET)
    assert _relative_updated(earlier, now) == "2 minutes ago"


def test_watchlist_symbol_marked_on_market_gainers():
    now = datetime(2026, 6, 25, 10, 0, tzinfo=_ET)
    rows = build_gainer_table_rows(
        [_scan("MRNA", 12.5), _scan("ZZZ", 8.0)],
        watchlist_symbols={"MRNA"},
        preserve_order=True,
    )
    message = build_live_summary_message(
        [_scan("MRNA", 12.5), _scan("ZZZ", 8.0)],
        top_limit=15,
        updated_at=now,
        data_updated_at=now,
        watchlist_symbols={"MRNA"},
        preserve_order=True,
    )
    assert rows[0][0] == "★ MRNA"
    assert "★ = on our watchlist" in message
