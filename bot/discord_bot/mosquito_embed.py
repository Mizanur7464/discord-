"""SPM-style compact mosquito alerts for #mosquito."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from bot.trading.scanner import ScanResult

_ET = ZoneInfo("America/New_York")


def _format_bar_volume(value: int | None, *, compact: bool = False) -> str:
    if value is None:
        return "—"
    if compact:
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f} M"
        if value >= 1_000:
            return f"{value / 1_000:.0f} k"
    return f"{value:,}"


def _format_float(shares: float | None) -> str:
    if not shares:
        return "—"
    millions = shares / 1_000_000
    if millions >= 100:
        return f"{millions:.0f}"
    return f"{millions:.1f}"


def _format_price(price: float | None) -> str:
    if price is None:
        return "—"
    if price >= 100:
        return f"{price:.2f}"
    if price >= 1:
        return f"{price:.2f}"
    return f"{price:.3f}".rstrip("0").rstrip(".")


def _pct_ansi(pct: float | None) -> str:
    if pct is None:
        return "\x1b[2;37m  — %\x1b[0m"
    if pct >= 0:
        return f"\x1b[2;32m+ {abs(pct):.1f} %\x1b[0m"
    return f"\x1b[2;31m- {abs(pct):.1f} %\x1b[0m"


def _rank_label(scan: ScanResult) -> str:
    rank = scan.peak_rvol_rank or scan.liquidity_rank
    if rank is None:
        return "M"
    return f"M  #{rank}"


def _tags(scan: ScanResult) -> str:
    tags: list[str] = []
    if scan.mosquito_nhod:
        tags.append("\x1b[2;32mNHOD\x1b[0m")
    if scan.mosquito_nlod:
        tags.append("\x1b[2;31mNLOD\x1b[0m")
    return f"  {' '.join(tags)}" if tags else ""


# NB-style dim pipe separator between fields.
_SEP = "  \x1b[2;37m|\x1b[0m  "


def _format_spm_row(scan: ScanResult) -> str:
    v1 = _format_bar_volume(scan.volume_1m)
    v2 = _format_bar_volume(scan.volume_2m)
    v5 = _format_bar_volume(scan.volume_5m, compact=True)
    v1d = _format_bar_volume(scan.daily_volume, compact=True)
    return (
        f"{_rank_label(scan)}  {_pct_ansi(scan.session_change_pct)}{_SEP}"
        f"\x1b[1;37m{scan.symbol}\x1b[0m{_tags(scan)}{_SEP}"
        f"\x1b[2;36m$ {_format_price(scan.price)}\x1b[0m{_SEP}"
        f"\x1b[2;33m1m:\x1b[0m {v1}{_SEP}"
        f"\x1b[2;33m2m:\x1b[0m {v2}{_SEP}"
        f"\x1b[2;33m5m:\x1b[0m {v5}{_SEP}"
        f"\x1b[2;34m1D:\x1b[0m {v1d}{_SEP}"
        f"\x1b[2;36mF:\x1b[0m {_format_float(scan.float_shares)}"
    )


def et_now() -> datetime:
    return datetime.now(_ET)


def build_mosquito_alert(scan: ScanResult, *, bot_name: str = "") -> tuple[str, discord.Embed]:
    from bot.utils.config import DEFAULT_BOT_NAME

    brand = bot_name or DEFAULT_BOT_NAME
    """Return SPM-style ANSI row + small embed for Discord timestamp."""
    now_et = et_now()
    content = f"```ansi\n{_format_spm_row(scan)}\n```"
    pct = scan.session_change_pct or 0
    color = discord.Color.from_rgb(87, 242, 135) if pct >= 0 else discord.Color.from_rgb(237, 66, 69)
    embed = discord.Embed(color=color)
    embed.timestamp = datetime.now(_ET)
    embed.set_footer(text=f"🦟 {now_et.strftime('%I:%M:%S %p')} ET · {brand}")
    return content, embed


def build_mosquito_embed(scan: ScanResult) -> discord.Embed:
    """Backward-compatible wrapper (content-only callers should use build_mosquito_alert)."""
    _, embed = build_mosquito_alert(scan)
    return embed
