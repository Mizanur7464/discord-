"""Track high-potential symbols before they become top gainers."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

STORE_FILE = Path(__file__).resolve().parents[2] / "data" / "potential_symbols.json"


@dataclass
class PotentialEntry:
    symbol: str
    score: int
    grade: str
    session_change_pct: float | None
    added_at: float
    reasons: list[str]
    related_news_title: str = ""
    related_news_url: str = ""
    hit_at: float | None = None


class PotentialStore:
    def __init__(self, *, retention_days: int = 5, max_entries: int = 500):
        self.retention_days = retention_days
        self.max_entries = max(50, max_entries)
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, PotentialEntry] = {}
        self._load()

    def _load(self) -> None:
        if not STORE_FILE.exists():
            return
        try:
            raw = json.loads(STORE_FILE.read_text(encoding="utf-8"))
            items = raw.get("entries", raw) if isinstance(raw, dict) else raw
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                entry = PotentialEntry(
                    symbol=str(item.get("symbol", "")).upper(),
                    score=int(item.get("score", 0)),
                    grade=str(item.get("grade", "")),
                    session_change_pct=item.get("session_change_pct"),
                    added_at=float(item.get("added_at", 0)),
                    reasons=[str(r) for r in item.get("reasons", [])][:6],
                    related_news_title=str(item.get("related_news_title", "")),
                    related_news_url=str(item.get("related_news_url", "")),
                    hit_at=item.get("hit_at"),
                )
                if entry.symbol:
                    self._entries[entry.symbol] = entry
        except Exception:
            self._entries = {}

    def _save(self) -> None:
        items = [asdict(entry) for entry in self._entries.values()]
        items.sort(key=lambda row: row.get("added_at", 0), reverse=True)
        STORE_FILE.write_text(json.dumps({"entries": items[: self.max_entries]}, indent=2), encoding="utf-8")

    def _prune(self) -> None:
        cutoff = time.time() - self.retention_days * 86400
        self._entries = {
            symbol: entry for symbol, entry in self._entries.items() if entry.added_at >= cutoff
        }

    def add_or_update(
        self,
        *,
        symbol: str,
        score: int,
        grade: str,
        session_change_pct: float | None,
        reasons: list[str],
    ) -> PotentialEntry:
        symbol = symbol.upper()
        existing = self._entries.get(symbol)
        entry = PotentialEntry(
            symbol=symbol,
            score=score,
            grade=grade,
            session_change_pct=session_change_pct,
            added_at=existing.added_at if existing else time.time(),
            reasons=reasons[:6],
            related_news_title=existing.related_news_title if existing else "",
            related_news_url=existing.related_news_url if existing else "",
            hit_at=existing.hit_at if existing else None,
        )
        self._entries[symbol] = entry
        self._prune()
        if len(self._entries) > self.max_entries:
            oldest = sorted(self._entries.values(), key=lambda item: item.added_at)
            for item in oldest[: len(self._entries) - self.max_entries]:
                self._entries.pop(item.symbol, None)
        self._save()
        return entry

    def get(self, symbol: str) -> PotentialEntry | None:
        return self._entries.get(symbol.upper())

    def has_active(self, symbol: str) -> bool:
        entry = self.get(symbol)
        return entry is not None and entry.hit_at is None

    def attach_news(self, symbol: str, *, title: str, url: str = "") -> PotentialEntry | None:
        entry = self.get(symbol)
        if not entry:
            return None
        entry.related_news_title = title[:500]
        entry.related_news_url = url
        self._save()
        return entry

    def mark_hit(self, symbol: str) -> PotentialEntry | None:
        entry = self.get(symbol)
        if not entry:
            return None
        entry.hit_at = time.time()
        self._save()
        return entry

    def active_symbols(self) -> list[str]:
        self._prune()
        return [symbol for symbol, entry in self._entries.items() if entry.hit_at is None]
