"""Background scanner that refreshes watchlist + broad market universe."""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class RealtimeScanner:
    def __init__(
        self,
        *,
        interval_seconds: int,
        min_score: int,
        alert_cooldown_seconds: int,
        scan_fn,
        collect_symbols_fn,
        send_alert_fn,
        universe_symbols_fn=None,
        max_symbols_per_cycle: int = 100,
        batch_rotation: bool = True,
    ):
        self.interval_seconds = max(10, interval_seconds)
        self.min_score = min_score
        self.alert_cooldown_seconds = alert_cooldown_seconds
        self.max_symbols_per_cycle = max_symbols_per_cycle
        self.batch_rotation = batch_rotation
        self._scan_fn = scan_fn
        self._collect_symbols_fn = collect_symbols_fn
        self._universe_symbols_fn = universe_symbols_fn
        self._send_alert_fn = send_alert_fn
        self._recent_alerts: dict[str, float] = {}
        self._running = False
        self._universe_cache: list[str] = []
        self._universe_cache_at: float = 0.0
        self._batch_offset: int = 0

    async def run_loop(self) -> None:
        self._running = True
        logger.info("Realtime scanner started (every %ss)", self.interval_seconds)
        while self._running:
            try:
                await self._scan_once()
            except Exception as exc:
                logger.warning("Realtime scanner cycle failed: %s", exc)
            await asyncio.sleep(self.interval_seconds)

    def stop(self) -> None:
        self._running = False

    def _get_universe_symbols(self) -> list[str]:
        if not self._universe_symbols_fn:
            return []
        now = time.time()
        if now - self._universe_cache_at > 300:
            try:
                self._universe_cache = self._universe_symbols_fn()
                self._universe_cache_at = now
            except Exception as exc:
                logger.warning("Universe refresh failed: %s", exc)
        return self._universe_cache

    def _merged_symbols(self) -> list[str]:
        symbols: list[str] = []
        for source in (self._collect_symbols_fn(), self._get_universe_symbols()):
            for symbol in source:
                sym = symbol.upper()
                if sym not in symbols:
                    symbols.append(sym)

        if not symbols:
            return []

        if not self.batch_rotation or len(symbols) <= self.max_symbols_per_cycle:
            return symbols[: self.max_symbols_per_cycle]

        end = self._batch_offset + self.max_symbols_per_cycle
        if end <= len(symbols):
            batch = symbols[self._batch_offset:end]
        else:
            batch = symbols[self._batch_offset:] + symbols[: end - len(symbols)]
        self._batch_offset = (self._batch_offset + self.max_symbols_per_cycle) % len(symbols)
        return batch

    async def _scan_once(self) -> int:
        symbols = self._merged_symbols()
        if not symbols:
            return 0
        sent = 0
        now = time.time()
        for symbol in symbols:
            if now - self._recent_alerts.get(symbol, 0) < self.alert_cooldown_seconds:
                continue
            scan = await asyncio.to_thread(self._scan_fn, symbol)
            if scan.score < self.min_score:
                continue
            await self._send_alert_fn(scan)
            self._recent_alerts[symbol] = now
            sent += 1
        if sent:
            logger.info("Realtime scanner sent %s alert(s)", sent)
        return sent

    async def scan_now(self) -> list:
        results = []
        for symbol in self._merged_symbols():
            scan = await asyncio.to_thread(self._scan_fn, symbol)
            results.append(scan)
        return results
