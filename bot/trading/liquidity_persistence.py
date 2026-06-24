"""Track sustained liquidity (turnover) through the session."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PERSISTENCE_FILE = Path(__file__).resolve().parents[2] / "data" / "liquidity_persistence.json"
MIN_TURNOVER_USD = 500_000.0


@dataclass
class PersistenceRecord:
    symbol: str
    session_date: str = ""
    readings: list[tuple[float, float]] = field(default_factory=list)

    def score(self) -> int:
        if not self.readings:
            return 0
        above = sum(1 for _, turnover in self.readings if turnover >= MIN_TURNOVER_USD)
        ratio = above / len(self.readings)
        latest = self.readings[-1][1] if self.readings else 0
        latest_bonus = 20 if latest >= MIN_TURNOVER_USD * 2 else 10 if latest >= MIN_TURNOVER_USD else 0
        return min(100, int(ratio * 80) + latest_bonus)


class LiquidityPersistenceStore:
    def __init__(self) -> None:
        PERSISTENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, PersistenceRecord] = {}
        self._load()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def update(self, symbol: str, turnover_usd: float | None) -> int:
        if turnover_usd is None or turnover_usd <= 0:
            record = self._records.get(symbol.upper())
            return record.score() if record and record.session_date == self._today() else 0
        symbol = symbol.upper()
        today = self._today()
        record = self._records.get(symbol)
        if not record or record.session_date != today:
            record = PersistenceRecord(symbol=symbol, session_date=today)
        record.readings.append((time.time(), turnover_usd))
        if len(record.readings) > 200:
            record.readings = record.readings[-200:]
        self._records[symbol] = record
        self._save()
        return record.score()

    def get_score(self, symbol: str) -> int:
        record = self._records.get(symbol.upper())
        if not record or record.session_date != self._today():
            return 0
        return record.score()

    def _load(self) -> None:
        if not PERSISTENCE_FILE.exists():
            return
        try:
            raw = json.loads(PERSISTENCE_FILE.read_text(encoding="utf-8"))
            for symbol, data in raw.items():
                if not isinstance(data, dict):
                    continue
                readings = data.get("readings") or []
                self._records[symbol.upper()] = PersistenceRecord(
                    symbol=symbol.upper(),
                    session_date=data.get("session_date", ""),
                    readings=[(float(r[0]), float(r[1])) for r in readings if isinstance(r, (list, tuple)) and len(r) == 2],
                )
        except Exception:
            self._records = {}

    def _save(self) -> None:
        payload = {
            symbol: {
                "symbol": record.symbol,
                "session_date": record.session_date,
                "readings": record.readings,
            }
            for symbol, record in self._records.items()
        }
        PERSISTENCE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
