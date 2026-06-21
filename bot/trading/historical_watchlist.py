"""Persistent historical watchlist for repeat low-cap runners (up to 2k symbols)."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

HISTORICAL_FILE = Path(__file__).resolve().parents[2] / "data" / "historical_watchlist.json"


@dataclass
class HistoricalEntry:
    symbol: str
    source: str
    added_at: float
    last_seen_at: float
    times_seen: int = 1
    note: str = ""


class HistoricalWatchlistStore:
    def __init__(self, *, max_entries: int = 2000, retention_days: int = 90):
        self.max_entries = max(100, max_entries)
        self.retention_seconds = retention_days * 24 * 60 * 60
        HISTORICAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, HistoricalEntry] = {}
        self._load()

    def add(self, symbol: str, *, source: str = "manual", note: str = "") -> HistoricalEntry:
        self._trim()
        symbol = symbol.upper()
        now = time.time()
        entry = self._entries.get(symbol)
        if entry:
            entry.times_seen += 1
            entry.last_seen_at = now
            if source:
                entry.source = source
            if note:
                entry.note = note[:500]
        else:
            entry = HistoricalEntry(
                symbol=symbol,
                source=source,
                added_at=now,
                last_seen_at=now,
                note=note[:500],
            )
        self._entries[symbol] = entry
        self._enforce_cap()
        self._save()
        return entry

    def remove(self, symbol: str) -> bool:
        symbol = symbol.upper()
        if symbol not in self._entries:
            return False
        self._entries.pop(symbol, None)
        self._save()
        return True

    def contains(self, symbol: str) -> bool:
        self._trim()
        return symbol.upper() in self._entries

    def symbols(self) -> list[str]:
        self._trim()
        ranked = sorted(
            self._entries.values(),
            key=lambda item: (item.times_seen, item.last_seen_at),
            reverse=True,
        )
        return [entry.symbol for entry in ranked[: self.max_entries]]

    def count(self) -> int:
        self._trim()
        return len(self._entries)

    def status_summary(self) -> str:
        return f"{self.count()}/{self.max_entries} historical symbols tracked"

    def _enforce_cap(self) -> None:
        if len(self._entries) <= self.max_entries:
            return
        ranked = sorted(
            self._entries.values(),
            key=lambda item: (item.times_seen, item.last_seen_at),
        )
        for entry in ranked[: len(self._entries) - self.max_entries]:
            self._entries.pop(entry.symbol, None)

    def _trim(self) -> None:
        cutoff = time.time() - self.retention_seconds
        expired = [
            symbol
            for symbol, entry in self._entries.items()
            if entry.last_seen_at < cutoff and entry.times_seen <= 1
        ]
        for symbol in expired:
            self._entries.pop(symbol, None)
        if expired:
            self._save()

    def _load(self) -> None:
        if not HISTORICAL_FILE.exists():
            return
        try:
            raw = json.loads(HISTORICAL_FILE.read_text(encoding="utf-8"))
            self._entries = {
                symbol.upper(): HistoricalEntry(**data)
                for symbol, data in raw.items()
                if isinstance(data, dict)
            }
            self._trim()
            self._enforce_cap()
        except Exception:
            self._entries = {}

    def _save(self) -> None:
        payload = {symbol: asdict(entry) for symbol, entry in self._entries.items()}
        HISTORICAL_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
