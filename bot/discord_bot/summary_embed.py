"""Summary channel embeds — live top gainers board."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from bot.trading.scanner import ScanResult

_ET = ZoneInfo("America/New_York")


def _compact_number(value: float | None, *, prefix: str = "", suffix: str = "") -> str:
    if value is None:
        return "—"
    if abs(value) >= 1_000_000:
        text = f"{value / 1_000_000:.2f}M"
    elif abs(value) >= 1_000:
        text = f"{value / 1_000:.1f}K"
    else:
        text = f"{value:.2f}" if isinstance(value, float) else str(value)
    return f"{prefix}{text}{suffix}"


def _top_gainers(scans: list[ScanResult], *, limit: int = 15) -> list[ScanResult]:
    ranked = sorted(
        scans,
        key=lambda scan: (
            scan.session_change_pct if scan.session_change_pct is not None else -999,
            scan.score,
            scan.turnover_usd or 0,
        ),
        reverse=True,
    )
    movers = [scan for scan in ranked if (scan.session_change_pct or 0) > 0]
    return movers[:limit]


def build_live_summary_embed(
    scans: list[ScanResult],
    *,
    top_limit: int = 15,
    updated_at: datetime | None = None,
) -> discord.Embed:
    now = updated_at or datetime.now(_ET)
    gainers = _top_gainers(scans, limit=top_limit)

    if gainers:
        lines = []
        for idx, scan in enumerate(gainers, start=1):
            pct = scan.session_change_pct
            pct_text = f"{pct:+.1f}%" if pct is not None else "—"
            lines.append(
                f"`{idx:02d}` **{scan.symbol}** · {pct_text} · "
                f"RVol {_compact_number(scan.current_rvol or scan.rvol, suffix='x')} · "
                f"Score {scan.grade} {scan.score}/100"
            )
        body = "\n".join(lines)
    else:
        body = "Waiting for scanner data…"

    embed = discord.Embed(
        title="📊 Top Gainers (Live)",
        description=body[:4096],
        color=discord.Color.from_rgb(88, 101, 242),
    )
    embed.set_footer(
        text=(
            f"Last update: {now.strftime('%I:%M:%S %p ET').lstrip('0')} · "
            f"Top {top_limit} · {len(scans)} symbols scanned"
        )
    )
    return embed


def build_summary_embed(scans: list[ScanResult]) -> discord.Embed:
    return build_live_summary_embed(scans)
