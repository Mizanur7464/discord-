"""Background scanner that refreshes watchlist symbols on an interval."""

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
    ):
        self.interval_seconds = max(10, interval_seconds)
        self.min_score = min_score
        self.alert_cooldown_seconds = alert_cooldown_seconds
        self._scan_fn = scan_fn
        self._collect_symbols_fn = collect_symbols_fn
        self._send_alert_fn = send_alert_fn
        self._recent_alerts: dict[str, float] = {}
        self._running = False

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

    async def _scan_once(self) -> int:
        symbols = self._collect_symbols_fn()
        if not symbols:
            return 0
        sent = 0
        now = time.time()
        for symbol in symbols[:25]:
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
        for symbol in self._collect_symbols_fn()[:25]:
            scan = await asyncio.to_thread(self._scan_fn, symbol)
            results.append(scan)
        return results
