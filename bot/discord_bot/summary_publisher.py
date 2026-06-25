"""Publish live top-gainer board to the summary Discord channel."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from bot.discord_bot.summary_embed import build_live_summary_embed
from bot.trading.scanner import ScanResult

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")


class SummaryPublisher:
    def __init__(self, *, min_symbols: int = 3, top_limit: int = 15):
        self.min_symbols = min_symbols
        self.top_limit = top_limit
        self._latest_scans: list[ScanResult] = []
        self._message: discord.Message | None = None

    def update_scans(self, scans: list[ScanResult]) -> None:
        self._latest_scans = list(scans)

    async def publish(self, channel: discord.TextChannel, *, refresh_data: bool = True) -> bool:
        if len(self._latest_scans) < self.min_symbols:
            return False
        now = datetime.now(_ET)
        embed = build_live_summary_embed(
            self._latest_scans,
            top_limit=self.top_limit,
            updated_at=now,
        )
        if self._message:
            try:
                await self._message.edit(embed=embed)
                return True
            except discord.NotFound:
                self._message = None
            except Exception as exc:
                logger.warning("Summary edit failed: %s", exc)
                self._message = None
        self._message = await channel.send(embed=embed)
        logger.info("Summary published (%s symbols)", len(self._latest_scans))
        return True

    async def tick_footer(self, channel: discord.TextChannel) -> bool:
        if not self._message or len(self._latest_scans) < self.min_symbols:
            return False
        now = datetime.now(_ET)
        embed = build_live_summary_embed(
            self._latest_scans,
            top_limit=self.top_limit,
            updated_at=now,
        )
        try:
            await self._message.edit(embed=embed)
            return True
        except Exception:
            self._message = None
            return False
