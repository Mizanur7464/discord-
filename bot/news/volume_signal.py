"""Track short-term volume / money-flow signals from the mosquito channel."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

SYMBOL_PATTERN = re.compile(r"\b([A-Z]{2,5})\b")
LABELED_VOLUME_PATTERN = re.compile(
    r"\b(?:1m|2m|5m|10m|vol|volume|f)\s*:?\s*([0-9][0-9,.]*\.?[0-9]*)\s*([KMB]?)\b",
    re.IGNORECASE,
)
NOISE_SYMBOLS = {
    "THE",
    "AND",
    "FOR",
    "WITH",
    "FROM",
    "NEWS",
    "LINK",
    "HOD",
    "CTB",
    "VOL",
}


@dataclass
class VolumeSignal:
    symbol: str
    value: float
    raw: str
    seen_at: float

    @property
    def age_seconds(self) -> float:
        return time.time() - self.seen_at

    @property
    def label(self) -> str:
        return f"{self.symbol} volume {self.value:,.0f}"


def _parse_number(value: str, suffix: str) -> float:
    number = float(value.replace(",", ""))
    scale = suffix.upper()
    if scale == "K":
        return number * 1_000
    if scale == "M":
        return number * 1_000_000
    if scale == "B":
        return number * 1_000_000_000
    return number


def _candidate_symbols(text: str) -> list[str]:
    symbols: list[str] = []
    for match in SYMBOL_PATTERN.finditer(text):
        symbol = match.group(1).upper()
        if symbol in NOISE_SYMBOLS:
            continue
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


def parse_volume_signals(text: str, *, min_value: float) -> list[VolumeSignal]:
    """Parse mosquito-style volume cards.

    The mosquito channel usually includes labels like 1m/2m/5m/10m/F. Nuntio
    news messages do not, so this avoids treating market-cap labels as volume.
    """
    if not text.strip():
        return []

    matches = list(LABELED_VOLUME_PATTERN.finditer(text))
    if not matches:
        return []

    max_value = max(_parse_number(match.group(1), match.group(2)) for match in matches)
    if max_value < min_value:
        return []

    symbols = _candidate_symbols(text)
    now = time.time()
    return [
        VolumeSignal(symbol=symbol, value=max_value, raw=text[:500], seen_at=now)
        for symbol in symbols
    ]


class VolumeSignalTracker:
    def __init__(self, *, min_value: float, confirm_seconds: int):
        self.min_value = min_value
        self.confirm_seconds = confirm_seconds
        self._signals: dict[str, VolumeSignal] = {}

    def update_from_text(self, text: str) -> list[VolumeSignal]:
        signals = parse_volume_signals(text, min_value=self.min_value)
        for signal in signals:
            self._signals[signal.symbol] = signal
        self._trim()
        return signals

    def get_recent(self, symbol: str) -> VolumeSignal | None:
        self._trim()
        signal = self._signals.get(symbol.upper())
        if not signal:
            return None
        if signal.age_seconds > self.confirm_seconds:
            self._signals.pop(symbol.upper(), None)
            return None
        return signal

    def _trim(self) -> None:
        expired = [
            symbol
            for symbol, signal in self._signals.items()
            if signal.age_seconds > self.confirm_seconds
        ]
        for symbol in expired:
            self._signals.pop(symbol, None)
