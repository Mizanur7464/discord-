"""Track news-to-trade speed across forwarder and bot."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_starts: dict[str, float] = {}
_steps: dict[str, list[tuple[str, float]]] = {}


def mark_news(key: str) -> None:
    if key:
        now = time.perf_counter()
        _starts[key] = now
        _steps[key] = [("forward", now)]


def mark_news_if_absent(key: str) -> None:
    if key and key not in _starts:
        mark_news(key)


def mark_step(key: str, step: str) -> None:
    if key:
        _steps.setdefault(key, []).append((step, time.perf_counter()))


def log_trade_speed(key: str, *, symbol: str = "", action: str = "order") -> float | None:
    start = _starts.pop(key, None)
    steps = _steps.pop(key, [])
    if start is None:
        return None

    end = time.perf_counter()
    total = end - start
    sym = f" {symbol}" if symbol else ""

    if len(steps) > 1:
        parts: list[str] = []
        prev = start
        for name, ts in steps[1:]:
            parts.append(f"{name} {ts - prev:.2f}s")
            prev = ts
        if prev < end:
            parts.append(f"order {end - prev:.2f}s")
        breakdown = " | ".join(parts)
        logger.info("Speed: %.2fs total (%s) — %s%s", total, breakdown, action, sym)
    else:
        logger.info("Speed: %.2fs — %s%s", total, action, sym)

    return total
