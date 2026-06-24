"""Discord embed for #mosquito volume / RVOL scanner alerts."""

from __future__ import annotations

import discord

from bot.trading.scanner import ScanResult


def _compact_number(value: float | None, *, prefix: str = "", suffix: str = "") -> str:
    if value is None:
        return "—"
    if abs(value) >= 1_000_000:
        text = f"{value / 1_000_000:.2f}M"
    elif abs(value) >= 1_000:
        text = f"{value / 1_000:.1f}K"
    else:
        text = f"{value:.2f}"
    return f"{prefix}{text}{suffix}"


def build_mosquito_embed(scan: ScanResult) -> discord.Embed:
    rvol = scan.current_rvol or scan.rvol
    exp = scan.expansion
    color = discord.Color.from_rgb(87, 242, 135) if rvol and rvol >= 3 else discord.Color.from_rgb(254, 231, 92)

    lines = [
        f"**{scan.symbol}**",
        f"Price {_compact_number(scan.price, prefix='$')}",
        f"Float {_compact_number(scan.float_shares)}",
        f"RVOL {_compact_number(rvol, suffix='x')}",
        f"Peak RVOL {_compact_number(scan.peak_rvol, suffix='x')} @ {scan.peak_rvol_at or '—'}",
        f"Volume {scan.daily_volume:,}" if scan.daily_volume else "Volume —",
        f"Vol expansion {(exp.volume_expansion_pct if exp else None) or 0:+.1f}%",
        f"Session {(scan.session_change_pct if scan.session_change_pct is not None else 0):+.1f}%",
    ]

    embed = discord.Embed(
        title="🦟 Mosquito Scanner",
        description="\n".join(lines),
        color=color,
    )
    embed.set_footer(text="Own scanner · Alpaca market data")
    return embed
