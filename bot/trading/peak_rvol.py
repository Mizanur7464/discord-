"""Session peak RVOL recorder."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

PEAK_RVOL_FILE = Path(__file__).resolve().parents[2] / "data" / "peak_rvol.json"


@dataclass
class PeakRvolRecord:
    symbol: str
    peak_rvol: float = 0.0
    peak_at: float = 0.0
    session_date: str = ""
    last_rvol: float | None = None

    @property
    def peak_time_utc(self) -> str:
        if not self.peak_at:
            return "—"
        return datetime.fromtimestamp(self.peak_at, tz=timezone.utc).strftime("%H:%M UTC")

    @property
    def rvol_expansion_pct(self) -> float | None:
        if self.last_rvol is None or self.peak_rvol <= 0:
            return None
        return round((self.last_rvol / self.peak_rvol - 1) * 100, 1)


class PeakRvolStore:
    def __init__(self) -> None:
        PEAK_RVOL_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, PeakRvolRecord] = {}
        self._load()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def update(self, symbol: str, rvol: float | None) -> PeakRvolRecord | None:
        if rvol is None or rvol <= 0:
            return self._records.get(symbol.upper())
        symbol = symbol.upper()
        today = self._today()
        record = self._records.get(symbol)
        if not record or record.session_date != today:
            record = PeakRvolRecord(symbol=symbol, session_date=today)
        record.last_rvol = rvol
        now = time.time()
        if rvol >= record.peak_rvol:
            record.peak_rvol = rvol
            record.peak_at = now
        self._records[symbol] = record
        self._save()
        return record

    def get(self, symbol: str) -> PeakRvolRecord | None:
        record = self._records.get(symbol.upper())
        if record and record.session_date != self._today():
            return None
        return record

    def _load(self) -> None:
        if not PEAK_RVOL_FILE.exists():
            return
        try:
            raw = json.loads(PEAK_RVOL_FILE.read_text(encoding="utf-8"))
            self._records = {
                symbol.upper(): PeakRvolRecord(**data)
                for symbol, data in raw.items()
                if isinstance(data, dict)
            }
        except Exception:
            self._records = {}

    def _save(self) -> None:
        payload = {symbol: asdict(record) for symbol, record in self._records.items()}
        PEAK_RVOL_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
