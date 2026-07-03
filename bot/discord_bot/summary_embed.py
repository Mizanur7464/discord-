"""Summary channel — NuntioBot-style top gainers table."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from bot.trading.scanner import ScanResult
from bot.trading.schedule import EXTENDED_CLOSE, EXTENDED_OPEN, REGULAR_CLOSE, REGULAR_OPEN

_ET = ZoneInfo("America/New_York")

_TABLE_HEADERS = ["Symbol", "Price", "% ↑", "Vol", "Float", "News"]
GAINER_TABLE_HEADERS = _TABLE_HEADERS
_COL_ALIGNS = ("left", "right", "right", "right", "right", "left")
_COL_MIN_WIDTH = (6, 5, 5, 5, 6, 4)


def _compact_number(value: float | None, *, prefix: str = "", suffix: str = "") -> str:
    if value is None:
        return "—"
    if abs(value) >= 1_000_000:
        text = f"{value / 1_000_000:.2f}M"
    elif abs(value) >= 1_000:
        text = f"{value / 1_000:.2f}K"
    else:
        text = f"{value:.2f}" if isinstance(value, float) else str(value)
    return f"{prefix}{text}{suffix}"


def _fmt_price(price: float | None) -> str:
    if price is None:
        return "—"
    return f"{price:.2f}"


def _fmt_pct(pct: float | None) -> str:
    if pct is None:
        return "—"
    return f"{pct:.1f}"


def _fmt_volume(volume: int | None) -> str:
    """NuntioBot-style volume: 271 M, 620 k."""
    if volume is None or volume <= 0:
        return "—"
    if volume >= 1_000_000:
        millions = volume / 1_000_000
        if millions >= 100:
            return f"{millions:.0f} M"
        return f"{millions:.1f} M"
    if volume >= 1_000:
        return f"{volume / 1_000:.0f} k"
    return str(volume)


def _fmt_float(shares: float | None) -> str:
    if not shares or shares <= 0:
        return "—"
    millions = shares / 1_000_000
    if millions >= 100:
        return f"{millions:.0f}m"
    return f"{millions:.1f}m"


def _news_text(scan: ScanResult) -> str:
    parts = [scan.catalyst_label or ""]
    if scan.catalyst:
        parts.append(scan.catalyst.headline)
        parts.extend(scan.catalyst.keywords)
    return " ".join(part for part in parts if part).lower()


def _short_news_label(scan: ScanResult) -> str:
    """NuntioBot-style news codes: PR, PR*, AR, SF."""
    text = _news_text(scan)
    if not text and not scan.news_bullish:
        return "—"
    if any(
        token in text
        for token in (
            "analyst",
            "upgrade",
            "downgrade",
            "price target",
            "initiates",
            "maintains",
            "reinstates",
            "raises target",
            "cuts target",
        )
    ):
        return "AR"
    if any(
        token in text
        for token in (
            "sec filing",
            "8-k",
            "10-k",
            "form 4",
            "form 8",
            "s-1",
            "filed with the sec",
            "sec form",
        )
    ):
        return "SF"
    if "earnings" in text or (scan.catalyst_label or "") == "Earnings":
        return "PR*"
    if scan.catalyst and len(scan.catalyst.keywords) >= 2:
        return "PR*"
    if text or scan.news_bullish or scan.catalyst_detected:
        return "PR"
    return "—"


_NEWS_TYPES_KEY = (
    "**News Types Key:**\n"
    "```\n"
    "PR - Press Release\n"
    "AR - Analyst Rating\n"
    "SF - SEC Filing\n"
    "*  - Additional types of news\n"
    "```"
)


def _session_title(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=_ET)
    else:
        now = now.astimezone(_ET)
    if now.weekday() >= 5:
        return "Top Gainers"
    clock = now.time()
    if EXTENDED_OPEN <= clock < REGULAR_OPEN:
        return "Top Gainers ☕ Pre-Market"
    if REGULAR_OPEN <= clock < REGULAR_CLOSE:
        return "Top Gainers ☕ Market Hours"
    if REGULAR_CLOSE <= clock < EXTENDED_CLOSE:
        return "Top Gainers ☕ After-Hours"
    return "Top Gainers"


def _relative_updated(data_updated_at: datetime | None, now: datetime) -> str:
    if data_updated_at is None:
        return "just now"
    if data_updated_at.tzinfo is None:
        data_updated_at = data_updated_at.replace(tzinfo=_ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_ET)
    seconds = max(0, int((now - data_updated_at.astimezone(_ET)).total_seconds()))
    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{seconds} seconds ago"
    minutes = seconds // 60
    if minutes == 1:
        return "1 minute ago"
    if minutes < 60:
        return f"{minutes} minutes ago"
    hours = minutes // 60
    if hours == 1:
        return "1 hour ago"
    return f"{hours} hours ago"


def _top_gainers(
    scans: list[ScanResult],
    *,
    limit: int = 15,
    preserve_order: bool = False,
) -> list[ScanResult]:
    if preserve_order:
        movers = [scan for scan in scans if (scan.session_change_pct or 0) > 0]
        return movers[:limit]
    ranked = sorted(
        scans,
        key=lambda scan: (
            scan.session_change_pct if scan.session_change_pct is not None else -999,
            scan.turnover_usd or 0,
            scan.daily_volume or 0,
        ),
        reverse=True,
    )
    movers = [scan for scan in ranked if (scan.session_change_pct or 0) > 0]
    return movers[:limit]


def _fmt_symbol(symbol: str, watchlist_symbols: set[str]) -> str:
    sym = symbol.upper()
    if sym in watchlist_symbols:
        return f"★ {sym}"
    return sym


def _nuntio_pipe_table(headers: list[str], rows: list[list[str]]) -> str:
    """NuntioBot-style simple pipe table inside a monospace code block."""
    col_count = len(headers)
    widths = list(_COL_MIN_WIDTH[:col_count])
    for idx, header in enumerate(headers):
        widths[idx] = max(widths[idx], len(header))
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def _fmt_row(cells: list[str], *, header: bool = False) -> str:
        padded: list[str] = []
        for idx, cell in enumerate(cells):
            width = widths[idx]
            if header:
                padded.append(cell.center(width))
            elif _COL_ALIGNS[idx] == "right":
                padded.append(cell.rjust(width))
            else:
                padded.append(cell.ljust(width))
        return "| " + " | ".join(padded) + " |"

    divider = "|" + "|".join("-" * (width + 2) for width in widths) + "|"
    return "\n".join([_fmt_row(headers, header=True), divider, *[_fmt_row(row) for row in rows]])


def _gainer_row(scan: ScanResult, watchlist_symbols: set[str]) -> list[str]:
    return [
        _fmt_symbol(scan.symbol, watchlist_symbols),
        _fmt_price(scan.price),
        _fmt_pct(scan.session_change_pct),
        _fmt_volume(scan.daily_volume),
        _fmt_float(scan.float_shares),
        _short_news_label(scan),
    ]


def build_gainer_table_rows(
    scans: list[ScanResult],
    *,
    top_limit: int = 15,
    watchlist_symbols: set[str] | None = None,
    preserve_order: bool = False,
) -> list[list[str]]:
    wl = {s.upper() for s in (watchlist_symbols or set())}
    gainers = _top_gainers(scans, limit=top_limit, preserve_order=preserve_order)
    return [_gainer_row(scan, wl) for scan in gainers]


def build_gainer_legend_embed(
    *,
    updated_at: datetime | None = None,
    data_updated_at: datetime | None = None,
) -> discord.Embed:
    """Updated + news legend — shown below the table image embed."""
    now = updated_at or datetime.now(_ET)
    when = _relative_updated(data_updated_at or now, now)
    body = f"Updated: {when}\n\n{_NEWS_TYPES_KEY}"
    return discord.Embed(description=body[:4096], color=discord.Color.from_rgb(47, 49, 54))


def build_gainer_table_embed(
    scans: list[ScanResult],
    *,
    top_limit: int = 15,
    updated_at: datetime | None = None,
    watchlist_symbols: set[str] | None = None,
    preserve_order: bool = False,
) -> discord.Embed:
    """Title + watchlist note + table PNG attachment."""
    now = updated_at or datetime.now(_ET)
    wl = {s.upper() for s in (watchlist_symbols or set())}
    gainers = _top_gainers(scans, limit=top_limit, preserve_order=preserve_order)
    title = _session_title(now)

    embed = discord.Embed(title=title, color=discord.Color.from_rgb(47, 49, 54))
    if gainers:
        if wl and any(scan.symbol.upper() in wl for scan in gainers):
            embed.description = "★ = on our watchlist"
    elif scans:
        embed.description = "No positive movers yet — scanner is running…"
    else:
        embed.description = "Waiting for scanner data…"

    embed.set_image(url="attachment://top-gainers.png")
    return embed


def build_gainer_summary_embeds(
    scans: list[ScanResult],
    *,
    top_limit: int = 15,
    updated_at: datetime | None = None,
    data_updated_at: datetime | None = None,
    watchlist_symbols: set[str] | None = None,
    preserve_order: bool = False,
) -> list[discord.Embed]:
    """Table embed first, legend embed second (Discord stacks below the image)."""
    now = updated_at or datetime.now(_ET)
    return [
        build_gainer_table_embed(
            scans,
            top_limit=top_limit,
            updated_at=now,
            watchlist_symbols=watchlist_symbols,
            preserve_order=preserve_order,
        ),
        build_gainer_legend_embed(updated_at=now, data_updated_at=data_updated_at),
    ]


def build_gainer_table_footer_lines(
    *,
    updated_at: datetime | None = None,
    data_updated_at: datetime | None = None,
) -> list[str]:
    """Plain-text footer lines (legacy — legend is sent as a Discord embed now)."""
    now = updated_at or datetime.now(_ET)
    when = _relative_updated(data_updated_at or now, now)
    return [
        f"Updated: {when}",
        "",
        "News Types Key:",
        "PR - Press Release",
        "AR - Analyst Rating",
        "SF - SEC Filing",
        "*  - Additional types of news",
    ]


def build_live_summary_header(
    scans: list[ScanResult],
    *,
    top_limit: int = 15,
    updated_at: datetime | None = None,
    watchlist_symbols: set[str] | None = None,
    preserve_order: bool = False,
) -> str:
    """Plain text above the table PNG (title + watchlist note)."""
    now = updated_at or datetime.now(_ET)
    wl = {s.upper() for s in (watchlist_symbols or set())}
    gainers = _top_gainers(scans, limit=top_limit, preserve_order=preserve_order)
    title = _session_title(now)

    if gainers:
        watchlist_note = ""
        if wl and any(scan.symbol.upper() in wl for scan in gainers):
            watchlist_note = "\n★ = on our watchlist"
        body = f"**{title}**{watchlist_note}"
    elif scans:
        body = f"**{title}**\nNo positive movers yet — scanner is running…"
    else:
        body = f"**{title}**\nWaiting for scanner data…"

    return body[:2000]


def build_live_summary_footer(
    *,
    updated_at: datetime | None = None,
    data_updated_at: datetime | None = None,
) -> str:
    """Plain text below the table PNG (Updated + news legend)."""
    now = updated_at or datetime.now(_ET)
    when = _relative_updated(data_updated_at or now, now)
    return f"Updated: {when}\n\n{_NEWS_TYPES_KEY}"[:2000]


def build_live_summary_caption(
    scans: list[ScanResult],
    *,
    top_limit: int = 15,
    updated_at: datetime | None = None,
    data_updated_at: datetime | None = None,
    watchlist_symbols: set[str] | None = None,
    preserve_order: bool = False,
) -> str:
    """Backward-compatible alias — header text only."""
    return build_live_summary_header(
        scans,
        top_limit=top_limit,
        updated_at=updated_at,
        watchlist_symbols=watchlist_symbols,
        preserve_order=preserve_order,
    )


def build_live_summary_message(
    scans: list[ScanResult],
    *,
    top_limit: int = 15,
    updated_at: datetime | None = None,
    data_updated_at: datetime | None = None,
    watchlist_symbols: set[str] | None = None,
    preserve_order: bool = False,
) -> str:
    """Backward-compatible alias — caption text (table is PNG in live publisher)."""
    return build_live_summary_caption(
        scans,
        top_limit=top_limit,
        updated_at=updated_at,
        data_updated_at=data_updated_at,
        watchlist_symbols=watchlist_symbols,
        preserve_order=preserve_order,
    )


def build_live_summary_embed(*args, **kwargs):
    """Backward-compatible alias — summary posts as plain text like NuntioBot."""
    content = build_live_summary_message(*args, **kwargs)
    embed = discord.Embed(description=content[:4096], color=discord.Color.from_rgb(47, 49, 54))
    return embed


def build_summary_embed(scans: list[ScanResult]) -> discord.Embed:
    return build_live_summary_embed(scans)
