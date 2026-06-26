"""Summary channel — NuntioBot-style top gainers table."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from bot.trading.scanner import ScanResult
from bot.trading.schedule import EXTENDED_CLOSE, EXTENDED_OPEN, REGULAR_CLOSE, REGULAR_OPEN

_ET = ZoneInfo("America/New_York")


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
    if volume is None:
        return "—"
    if volume >= 1_000_000:
        return f"{volume / 1_000_000:.1f} m"
    if volume >= 1_000:
        return f"{volume / 1_000:.1f} k"
    return str(volume)


def _fmt_float(shares: float | None) -> str:
    if not shares or shares <= 0:
        return "—"
    millions = shares / 1_000_000
    if millions >= 100:
        return f"{millions:.0f} m"
    return f"{millions:.1f} m"


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


def _top_gainers(scans: list[ScanResult], *, limit: int = 15) -> list[ScanResult]:
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


def _pipe_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def _row(cells: list[str]) -> str:
        return "| " + " | ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(cells)) + " |"

    lines = [_row(headers), *(_row(row) for row in rows)]
    return "\n".join(lines)


def build_live_summary_message(
    scans: list[ScanResult],
    *,
    top_limit: int = 15,
    updated_at: datetime | None = None,
    data_updated_at: datetime | None = None,
) -> str:
    now = updated_at or datetime.now(_ET)
    gainers = _top_gainers(scans, limit=top_limit)
    title = _session_title(now)

    if gainers:
        rows = [
            [
                scan.symbol,
                _fmt_price(scan.price),
                _fmt_pct(scan.session_change_pct),
                _fmt_volume(scan.daily_volume),
                _fmt_float(scan.float_shares),
                _short_news_label(scan),
            ]
            for scan in gainers
        ]
        table = _pipe_table(["Symbol", "Price", "% ↑", "Volume", "Float", "News"], rows)
        body = f"**{title}**\n```\n{table}\n```"
    elif scans:
        body = (
            f"**{title}**\n"
            "```\n"
            "| Symbol | Price | % ↑ | Volume | Float | News |\n"
            "| No positive movers yet — scanner is running… |\n"
            "```"
        )
    else:
        body = f"**{title}**\n```\nWaiting for scanner data…\n```"

    when = _relative_updated(data_updated_at or now, now)
    footer = f"*Updated: {when}*"
    return f"{body}\n{footer}\n\n{_NEWS_TYPES_KEY}"[:2000]


def build_live_summary_embed(*args, **kwargs):
    """Backward-compatible alias — summary now posts as plain text like NuntioBot."""
    import discord

    content = build_live_summary_message(*args, **kwargs)
    embed = discord.Embed(description=content[:4096], color=discord.Color.from_rgb(47, 49, 54))
    return embed


def build_summary_embed(scans: list[ScanResult]) -> discord.Embed:
    return build_live_summary_embed(scans)
