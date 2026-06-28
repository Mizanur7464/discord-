"""NB-style one-line watchlist monitor posts with Details button."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from bot.discord_bot.scan_embed import build_scan_embed
from bot.trading.scanner import ScanResult

_ET = ZoneInfo("America/New_York")


def _fmt_turnover(usd: float | None) -> str:
    if usd is None or usd <= 0:
        return "—"
    if usd >= 1_000_000:
        return f"${usd / 1_000_000:.1f} M"
    if usd >= 1_000:
        return f"${usd / 1_000:.0f} K"
    return f"${usd:.0f}"


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


_SEC_TOKENS = (
    "sec filing",
    "8-k",
    "10-k",
    "10-q",
    "form 4",
    "form 8",
    "s-1",
    "filed with the sec",
    "sec form",
    "13d",
    "13g",
)


def _is_sec_filing(scan: ScanResult) -> bool:
    text = (scan.catalyst_label or "").lower()
    if scan.catalyst:
        text += " " + scan.catalyst.headline.lower()
        text += " " + " ".join(scan.catalyst.keywords).lower()
    return any(token in text for token in _SEC_TOKENS)


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


def format_monitor_clock(now: datetime | None = None) -> str:
    clock = (now or datetime.now(_ET)).strftime("%I:%M:%S %p ET").lstrip("0")
    return clock


def build_watchlist_monitor_line(
    scan: ScanResult,
    *,
    country_flag: str = "🇺🇸",
    news_url: str = "",
    pct_from_52w_low: float | None = None,
    details_url: str = "",
) -> str:
    """NB / nuntio-std row: NB arrangement, with our Score appended at the back."""
    clock = format_monitor_clock()
    rank = scan.liquidity_rank or scan.peak_rvol_rank

    # Header — NB order: time ↑ TICKER price % · rank [tags] ~ flag.
    # Important values sit in small `code` boxes like NB.
    head_parts = [f"`{clock}`", _arrow(scan.session_change_pct), f"**{scan.symbol}**"]
    price_tag = _price_level_tag(scan.price)
    if price_tag:
        head_parts.append(f"`{price_tag}`")
    if scan.session_change_pct is not None:
        head_parts.append(f"`{abs(scan.session_change_pct):.0f}%`")
    if rank:
        head_parts.append(f"· {rank}")
    for tag in _status_tags(scan):
        head_parts.append(f"`{tag}`")
    head_parts.append(f"~ {country_flag}")
    head = " ".join(part for part in head_parts if part)

    # Details — NB order: Float | RVol | Vol | SEC, then our Score at the back.
    fields: list[str] = []
    if scan.float_shares:
        fields.append(f"**Float:** {_fmt_millions(scan.float_shares)}")
    rvol = scan.current_rvol or scan.rvol
    if rvol is not None:
        rvol_text = f"{rvol:,.0f}x" if rvol >= 100 else f"{rvol:g}x"
        fields.append(f"**RVol:** {rvol_text}")
    if scan.daily_volume:
        fields.append(f"**Vol:** {_fmt_millions(float(scan.daily_volume))}")
    if scan.turnover_usd:
        fields.append(f"**Turnover:** {_fmt_turnover(scan.turnover_usd)}")
    if pct_from_52w_low is not None:
        fields.append(f"`+{pct_from_52w_low:.1f}% from 52W-Low`")
    if _is_sec_filing(scan):
        fields.append("`SEC`")
    fields.append(f"**Score:** {scan.grade} {scan.score}/100")

    line = f"{head} |\n" + " | ".join(fields)
    if news_url:
        line = f"{line} - [Link]({news_url})"
    if details_url:
        line = f"{line} · [Details]({details_url})"
    return line


class ScanDetailView(discord.ui.View):
    """Compact Details button — ephemeral full scanner embed."""

    def __init__(
        self,
        bot,
        symbol: str,
        *,
        title_prefix: str,
        related_news_title: str = "",
        related_news_url: str = "",
    ):
        super().__init__(timeout=3600)
        self._bot = bot
        self._symbol = symbol.upper()
        self._title_prefix = title_prefix
        self._related_news_title = related_news_title
        self._related_news_url = related_news_url

    @discord.ui.button(label="Details", style=discord.ButtonStyle.secondary)
    async def show_details(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            scan = await asyncio.to_thread(self._bot.scanner.scan, self._symbol)
        except Exception:
            cached = self._bot._scan_detail_cache.get(self._symbol)
            if not cached:
                await interaction.followup.send(
                    f"No scan for `{self._symbol}` — try `/scan {self._symbol}`.",
                    ephemeral=True,
                )
                return
            scan, _ = cached

        min_score = self._bot._scanner_min_score(scan)
        self._bot._scan_detail_cache[self._symbol] = (scan, min_score)
        title, url = self._bot._related_news_for_symbol(self._symbol)
        embed = build_scan_embed(
            scan,
            min_score=min_score,
            title_prefix=self._title_prefix,
            related_news_title=title or self._related_news_title,
            related_news_url=url or self._related_news_url,
            bot_name=self._bot.settings.bot.name,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
