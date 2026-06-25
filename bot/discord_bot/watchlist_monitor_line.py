"""NB-style one-line watchlist monitor posts with Details button."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from bot.discord_bot.scan_embed import build_scan_embed
from bot.trading.scanner import ScanResult

_ET = ZoneInfo("America/New_York")


def _fmt_millions(value: float | None) -> str:
    if value is None:
        return "—"
    millions = value / 1_000_000 if value >= 100_000 else value
    if millions >= 100:
        return f"{millions:.0f} M"
    return f"{millions:.1f} M"


def _price_level_tag(price: float | None) -> str:
    if price is None:
        return ""
    if price < 0.5:
        return "< $.50c"
    if price < 2:
        return "< $2"
    if price < 5:
        return "< $5"
    return f"$ {price:.2f}"


def _arrow(pct: float | None) -> str:
    if pct is None or pct == 0:
        return "→"
    return "↑" if pct > 0 else "↓"


def _status_tags(scan: ScanResult) -> list[str]:
    tags: list[str] = []
    if scan.mosquito_nhod or (scan.structure and scan.structure.hod_break):
        tags.append("NHOD")
    if scan.mosquito_nlod:
        tags.append("NLOD")
    if scan.expansion and (scan.expansion.volume_expansion_pct or 0) >= 80:
        tags.append("Vol-spike")
    if scan.catalyst_detected:
        tags.append("PR")
    if scan.is_repeat_runner:
        tags.append("Runner")
    return tags[:3]


def build_watchlist_monitor_line(scan: ScanResult, *, country_flag: str = "🇺🇸") -> str:
    """Compact NB / nuntio-std monitoring list row."""
    clock = datetime.now(_ET).strftime("%H:%M")
    rank = scan.liquidity_rank or scan.peak_rvol_rank

    head_parts = [clock, _arrow(scan.session_change_pct), f"**{scan.symbol}**", _price_level_tag(scan.price)]
    if scan.session_change_pct is not None:
        head_parts.append(f"{abs(scan.session_change_pct):.0f}%")
    if rank:
        head_parts.append(f"· {rank}")
    for tag in _status_tags(scan):
        head_parts.append(f"`{tag}`")
    head_parts.append(f"~ {country_flag}")
    head = " ".join(part for part in head_parts if part)

    fields: list[str] = []
    if scan.float_shares:
        fields.append(f"**Float:** {_fmt_millions(scan.float_shares)}")
    rvol = scan.current_rvol or scan.rvol
    if rvol is not None:
        rvol_text = f"{rvol:,.0f}x" if rvol >= 100 else f"{rvol:g}x"
        fields.append(f"**RVol:** {rvol_text}")
    if scan.daily_volume:
        fields.append(f"**Vol:** {_fmt_millions(float(scan.daily_volume))}")
    if scan.microstructure and scan.microstructure.short_interest_pct is not None:
        fields.append(f"**SI:** {scan.microstructure.short_interest_pct:.1f}%")
    if scan.structure and scan.structure.distance_from_hod_pct is not None:
        fields.append(f"{scan.structure.distance_from_hod_pct:+.1f}% from **HOD**")
    if scan.catalyst_label and scan.catalyst_label != "No Clear Catalyst":
        fields.append(f"**Theme:** [{scan.catalyst_label}]")
    fields.append(f"**Score:** {scan.grade} {scan.score}/100")

    return f"{head} | " + " | ".join(fields)


class ScanDetailView(discord.ui.View):
    """Button to post full scanner embed on click."""

    def __init__(self, bot, symbol: str, *, title_prefix: str):
        super().__init__(timeout=3600)
        self._bot = bot
        self._symbol = symbol.upper()
        self._title_prefix = title_prefix

    @discord.ui.button(label="Details", style=discord.ButtonStyle.primary, emoji="🔎")
    async def show_details(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cached = self._bot._scan_detail_cache.get(self._symbol)
        if not cached:
            await interaction.response.send_message(
                f"No cached scan for `{self._symbol}` — try `/scan {self._symbol}`.",
                ephemeral=True,
            )
            return
        scan, min_score = cached
        embed = build_scan_embed(scan, min_score=min_score, title_prefix=self._title_prefix)
        await interaction.response.send_message(embed=embed, ephemeral=True)
