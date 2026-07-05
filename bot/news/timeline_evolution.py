"""SDS §5.1 Timeline Evolution — per-ticker daily catalyst sequence."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


@dataclass
class TimelineEvent:
    time_et: str
    label: str


@dataclass
class _DayLog:
    date: str
    events: list[TimelineEvent] = field(default_factory=list)


class TimelineEvolutionStore:
    def __init__(self, *, max_events: int = 12) -> None:
        self._max = max_events
        self._logs: dict[str, _DayLog] = {}

    @staticmethod
    def _today() -> str:
        return datetime.now(_ET).strftime("%Y-%m-%d")

    @staticmethod
    def _now_et() -> str:
        return datetime.now(_ET).strftime("%H:%M")

    def record(self, symbol: str, label: str) -> str:
        symbol = (symbol or "").upper()
        if not symbol or not label:
            return ""
        today = self._today()
        log = self._logs.get(symbol)
        if not log or log.date != today:
            log = _DayLog(date=today)
            self._logs[symbol] = log
        log.events.append(TimelineEvent(time_et=self._now_et(), label=label[:80]))
        if len(log.events) > self._max:
            log.events = log.events[-self._max :]
        return self.format_day(symbol)

    def format_day(self, symbol: str) -> str:
        symbol = (symbol or "").upper()
        log = self._logs.get(symbol)
        if not log or log.date != self._today() or not log.events:
            return ""
        parts = [f"{ev.time_et} {ev.label}" for ev in log.events[-4:]]
        return " → ".join(parts)


_timeline_store = TimelineEvolutionStore()


def record_timeline_event(symbol: str, label: str) -> str:
    return _timeline_store.record(symbol, label)


def get_timeline_snippet(symbol: str) -> str:
    return _timeline_store.format_day(symbol)
