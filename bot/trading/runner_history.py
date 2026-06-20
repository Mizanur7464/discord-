"""Track repeat low-cap momentum runners for scanner scoring."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

RUNNER_FILE = Path(__file__).resolve().parents[2] / "data" / "runner_history.json"


@dataclass
class RunnerRecord:
    symbol: str
    stars: int = 0
    best_single_day_pct: float = 0.0
    times_seen: int = 0
    last_seen_at: float = 0.0
    last_price: float | None = None
    notes: str = ""

    @property
    def is_starred(self) -> bool:
        return self.stars > 0


class RunnerHistoryStore:
    def __init__(self, *, big_move_percent: float = 50.0, retention_days: int = 30):
        self.big_move_percent = big_move_percent
        self.retention_seconds = retention_days * 24 * 60 * 60
        RUNNER_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, RunnerRecord] = {}
        self._load()

    def get(self, symbol: str) -> RunnerRecord | None:
        self._trim()
        return self._records.get(symbol.upper())

    def is_repeat_runner(self, symbol: str) -> bool:
        record = self.get(symbol)
        return record is not None and (record.stars > 0 or record.times_seen >= 2)

    def record_sighting(
        self,
        symbol: str,
        *,
        price: float | None = None,
        move_pct: float | None = None,
        note: str = "",
    ) -> RunnerRecord:
        self._trim()
        symbol = symbol.upper()
        now = time.time()
        record = self._records.get(symbol)
        if not record:
            record = RunnerRecord(symbol=symbol, last_seen_at=now)
        record.times_seen += 1
        record.last_seen_at = now
        if price is not None:
            record.last_price = price
        if note:
            record.notes = note[:500]
        if move_pct is not None and move_pct > record.best_single_day_pct:
            record.best_single_day_pct = move_pct
        if move_pct is not None and move_pct >= self.big_move_percent:
            record.stars = min(3, record.stars + 1)
        self._records[symbol] = record
        self._save()
        return record

    def star_symbol(self, symbol: str, *, stars: int = 1, note: str = "") -> RunnerRecord:
        record = self.record_sighting(symbol, note=note)
        record.stars = min(3, max(record.stars, stars))
        self._records[symbol.upper()] = record
        self._save()
        return record

    def active_runners(self) -> list[RunnerRecord]:
        self._trim()
        return sorted(
            self._records.values(),
            key=lambda item: (item.stars, item.times_seen, item.last_seen_at),
            reverse=True,
        )

    def _trim(self) -> None:
        cutoff = time.time() - self.retention_seconds
        expired = [
            symbol
            for symbol, record in self._records.items()
            if record.last_seen_at < cutoff and record.stars == 0
        ]
        for symbol in expired:
            self._records.pop(symbol, None)
        if expired:
            self._save()

    def _load(self) -> None:
        if not RUNNER_FILE.exists():
            return
        try:
            raw = json.loads(RUNNER_FILE.read_text(encoding="utf-8"))
            self._records = {
                symbol.upper(): RunnerRecord(**data)
                for symbol, data in raw.items()
                if isinstance(data, dict)
            }
            self._trim()
        except Exception:
            self._records = {}

    def _save(self) -> None:
        payload = {symbol: asdict(record) for symbol, record in self._records.items()}
        RUNNER_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
