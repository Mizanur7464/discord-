"""Persistent AI-news watchlist with mosquito volume/price breakout triggers."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from bot.news.volume_signal import VolumeSignal

WATCHLIST_FILE = Path(__file__).resolve().parents[2] / "data" / "watchlist.json"


@dataclass
class WatchEntry:
    symbol: str
    title: str
    ai_reason: str
    source: str
    link: str
    added_at: float
    expires_at: float
    baseline_volume: float | None = None
    baseline_price: float | None = None
    last_volume: float | None = None
    last_price: float | None = None
    triggered: bool = False


@dataclass
class WatchTrigger:
    entry: WatchEntry
    signal: VolumeSignal
    reason: str


class WatchlistStore:
    def __init__(
        self,
        *,
        days: int,
        volume_increase_percent: float,
        price_increase_percent: float,
        max_entries: int = 2000,
    ):
        self.days = days
        self.max_entries = max(50, max_entries)
        self.volume_multiplier = 1 + max(0, volume_increase_percent) / 100
        self.price_multiplier = 1 + max(0, price_increase_percent) / 100
        WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, WatchEntry] = {}
        self._load()

    def add_or_update(
        self,
        *,
        symbol: str,
        title: str,
        ai_reason: str,
        source: str,
        link: str,
        baseline_signal: VolumeSignal | None = None,
    ) -> WatchEntry:
        self._trim()
        now = time.time()
        symbol = symbol.upper()
        entry = self._entries.get(symbol)
        if not entry:
            entry = WatchEntry(
                symbol=symbol,
                title=title,
                ai_reason=ai_reason,
                source=source,
                link=link,
                added_at=now,
                expires_at=now + self.days * 24 * 60 * 60,
            )
        else:
            entry.title = title or entry.title
            entry.ai_reason = ai_reason or entry.ai_reason
            entry.source = source or entry.source
            entry.link = link or entry.link
            entry.expires_at = now + self.days * 24 * 60 * 60
            entry.triggered = False

        if baseline_signal:
            self._apply_baseline(entry, baseline_signal)

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

    def check_signal(self, signal: VolumeSignal) -> WatchTrigger | None:
        self._trim()
        entry = self._entries.get(signal.symbol.upper())
        if not entry or entry.triggered:
            return None

        if entry.baseline_volume is None and entry.baseline_price is None:
            self._apply_baseline(entry, signal)
            self._save()
            return None

        entry.last_volume = signal.value or entry.last_volume
        entry.last_price = signal.price or entry.last_price

        reasons: list[str] = []
        if entry.baseline_volume and signal.value >= entry.baseline_volume * self.volume_multiplier:
            pct = ((signal.value / entry.baseline_volume) - 1) * 100
            reasons.append(f"volume +{pct:.1f}%")
        if entry.baseline_price and signal.price and signal.price >= entry.baseline_price * self.price_multiplier:
            pct = ((signal.price / entry.baseline_price) - 1) * 100
            reasons.append(f"price +{pct:.1f}%")

        if not reasons:
            self._save()
            return None

        entry.triggered = True
        self._save()
        return WatchTrigger(entry=entry, signal=signal, reason=", ".join(reasons))

    def active_entries(self) -> list[WatchEntry]:
        self._trim()
        return list(self._entries.values())

    def _apply_baseline(self, entry: WatchEntry, signal: VolumeSignal) -> None:
        if signal.value and entry.baseline_volume is None:
            entry.baseline_volume = signal.value
        if signal.price and entry.baseline_price is None:
            entry.baseline_price = signal.price
        entry.last_volume = signal.value or entry.last_volume
        entry.last_price = signal.price or entry.last_price

    def _enforce_cap(self) -> None:
        if len(self._entries) <= self.max_entries:
            return
        ranked = sorted(self._entries.values(), key=lambda item: item.added_at)
        for entry in ranked[: len(self._entries) - self.max_entries]:
            self._entries.pop(entry.symbol, None)

    def _trim(self) -> None:
        now = time.time()
        expired = [symbol for symbol, entry in self._entries.items() if entry.expires_at < now]
        for symbol in expired:
            self._entries.pop(symbol, None)
        if expired:
            self._save()
        self._enforce_cap()

    def _load(self) -> None:
        if not WATCHLIST_FILE.exists():
            return
        try:
            raw = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
            self._entries = {
                symbol.upper(): WatchEntry(**data)
                for symbol, data in raw.items()
                if isinstance(data, dict)
            }
            self._trim()
        except Exception:
            self._entries = {}

    def _save(self) -> None:
        payload = {symbol: asdict(entry) for symbol, entry in self._entries.items()}
        WATCHLIST_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
