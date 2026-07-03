from datetime import datetime
from zoneinfo import ZoneInfo

from bot.discord_bot.gainer_table_image import render_gainer_table_png
from bot.discord_bot.summary_embed import (
    build_gainer_table_rows,
    build_live_summary_caption,
    build_live_summary_message,
)
from bot.trading.scanner import ScanResult

_ET = ZoneInfo("America/New_York")


def _scan(symbol: str, pct: float, **kwargs) -> ScanResult:
    defaults = dict(
        session_change_pct=pct,
        price=10.0,
        daily_volume=250_000,
        float_shares=12_500_000,
        catalyst_label="Partnership",
        score=80,
    )
    defaults.update(kwargs)
    return ScanResult(symbol=symbol, **defaults)


def test_render_gainer_table_png():
    rows = build_gainer_table_rows(
        [_scan("CWD", 74.3, price=1.15, daily_volume=289_000_000, float_shares=8_500_000)],
        watchlist_symbols={"CWD"},
    )
    buf = render_gainer_table_png(["Symbol", "Price", "% ↑", "Vol", "Float", "News"], rows)
    assert buf.read(8) == b"\x89PNG\r\n\x1a\n"


def test_caption_has_no_code_block_table():
    now = datetime(2026, 6, 25, 8, 30, tzinfo=_ET)
    caption = build_live_summary_caption(
        [_scan("WYY", 68.7, price=29.48, daily_volume=86_200, catalyst_label="Earnings")],
        updated_at=now,
        data_updated_at=now,
    )
    assert "**Top Gainers ☕ Pre-Market**" in caption
    assert "Updated: just now" in caption
    assert "**News Types Key:**" in caption
    assert "| Symbol |" not in caption


def test_build_live_summary_message_alias():
    now = datetime(2026, 6, 25, 8, 30, tzinfo=_ET)
    message = build_live_summary_message(
        [_scan("WYY", 68.7)],
        updated_at=now,
        data_updated_at=now,
    )
    assert "**Top Gainers ☕ Pre-Market**" in message
    assert "| Symbol |" not in message
