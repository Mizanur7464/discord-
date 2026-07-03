"""Publish live top-gainer board to the summary Discord channel."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from bot.discord_bot.gainer_table_image import render_gainer_table_png
from bot.discord_bot.summary_embed import (
    _top_gainers,
    build_gainer_table_rows,
    build_live_summary_caption,
)
from bot.trading.scanner import ScanResult

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")


class SummaryPublisher:
    def __init__(self, *, min_symbols: int = 1, top_limit: int = 15):
        self.min_symbols = min_symbols
        self.top_limit = top_limit
        self._latest_scans: list[ScanResult] = []
        # Last scans that actually contained positive movers — kept so the
        # board shows the previous movers when the market is quiet.
        self._last_mover_scans: list[ScanResult] = []
        self._watchlist_symbols: set[str] = set()
        self._market_ordered = False
        self._data_updated_at: datetime | None = None
        self._message: discord.Message | None = None

    def has_data(self) -> bool:
        return bool(self._latest_scans or self._last_mover_scans)

    def reset_message(self) -> None:
        self._message = None

    def update_scans(
        self,
        scans: list[ScanResult],
        *,
        watchlist_symbols: set[str] | None = None,
        market_ordered: bool = False,
    ) -> None:
        self._latest_scans = list(scans)
        self._watchlist_symbols = {s.upper() for s in (watchlist_symbols or set())}
        self._market_ordered = market_ordered
        self._data_updated_at = datetime.now(_ET)
        if _top_gainers(scans, limit=self.top_limit, preserve_order=market_ordered):
            self._last_mover_scans = list(scans)

    def _effective_scans(self) -> list[ScanResult]:
        """Show current movers, or fall back to the last known movers."""
        if _top_gainers(self._latest_scans, limit=self.top_limit, preserve_order=self._market_ordered):
            return self._latest_scans
        if self._last_mover_scans:
            return self._last_mover_scans
        return self._latest_scans

    def _build_caption(self, *, now: datetime | None = None) -> str:
        return build_live_summary_caption(
            self._effective_scans(),
            top_limit=self.top_limit,
            updated_at=now or datetime.now(_ET),
            data_updated_at=self._data_updated_at,
            watchlist_symbols=self._watchlist_symbols,
            preserve_order=self._market_ordered,
        )

    def _build_table_file(self) -> discord.File | None:
        rows = build_gainer_table_rows(
            self._effective_scans(),
            top_limit=self.top_limit,
            watchlist_symbols=self._watchlist_symbols,
            preserve_order=self._market_ordered,
        )
        if not rows:
            return None
        png = render_gainer_table_png(
            ["Symbol", "Price", "% ↑", "Vol", "Float", "News"],
            rows,
        )
        return discord.File(png, filename="top-gainers.png")

    async def publish(self, channel: discord.TextChannel, *, refresh_data: bool = True) -> bool:
        if not self._latest_scans and not self._last_mover_scans:
            return False
        caption = self._build_caption()
        table_file = self._build_table_file()
        if self._message:
            try:
                if table_file:
                    await self._message.edit(content=caption, attachments=[table_file])
                else:
                    await self._message.edit(content=caption, attachments=[])
                return True
            except discord.NotFound:
                self._message = None
            except Exception as exc:
                logger.warning("Summary edit failed: %s", exc)
                self._message = None
        if table_file:
            self._message = await channel.send(content=caption, file=table_file)
        else:
            self._message = await channel.send(content=caption, suppress_embeds=True)
        logger.info("Summary published (%s symbols)", len(self._latest_scans))
        return True

    async def tick_footer(self, channel: discord.TextChannel) -> bool:
        if not self._message or (not self._latest_scans and not self._last_mover_scans):
            return False
        caption = self._build_caption()
        table_file = self._build_table_file()
        try:
            if table_file:
                await self._message.edit(content=caption, attachments=[table_file])
            else:
                await self._message.edit(content=caption, attachments=[])
            return True
        except Exception:
            self._message = None
            return False
