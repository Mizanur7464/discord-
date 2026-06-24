"""Publish batch rankings to the summary Discord channel."""

from __future__ import annotations

import logging

import discord

from bot.discord_bot.summary_embed import build_summary_embed
from bot.trading.scanner import ScanResult

logger = logging.getLogger(__name__)


class SummaryPublisher:
    def __init__(self, *, min_symbols: int = 3):
        self.min_symbols = min_symbols
        self._latest_scans: list[ScanResult] = []

    def update_scans(self, scans: list[ScanResult]) -> None:
        self._latest_scans = list(scans)

    async def publish(self, channel: discord.TextChannel) -> bool:
        if len(self._latest_scans) < self.min_symbols:
            return False
        embed = build_summary_embed(self._latest_scans)
        await channel.send(embed=embed)
        logger.info("Summary published (%s symbols)", len(self._latest_scans))
        return True
