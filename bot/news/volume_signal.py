"""Track short-term volume / money-flow signals from the mosquito channel."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

SYMBOL_PATTERN = re.compile(r"\b([A-Z]{2,5})\b")
LABELED_VOLUME_PATTERN = re.compile(
    r"\b(?:1m|2m|5m|10m|vol|volume)\s*:?\s*([0-9][0-9,.]*\.?[0-9]*)\s*([KMB]?)\b",
    re.IGNORECASE,
)
RVOL_PATTERN = re.compile(r"\bRVol\s*:?\s*([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)
FLOAT_PATTERN = re.compile(
    r"\bFloat\s*:?\s*([0-9][0-9,.]*\.?[0-9]*)\s*([KMB]?)\b",
    re.IGNORECASE,
)
PRICE_PATTERN = re.compile(r"\$([0-9]+(?:\.[0-9]+)?)\b")
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
    "RVOL",
    "FLOAT",
    "PRICE",
}


@dataclass
class VolumeSignal:
    symbol: str
    value: float
    raw: str
    seen_at: float
    relative_volume: float | None = None
    float_shares: float | None = None
    price: float | None = None

    @property
    def age_seconds(self) -> float:
        return time.time() - self.seen_at

    @property
    def label(self) -> str:
        parts = [f"{self.symbol} volume {self.value:,.0f}"]
        if self.relative_volume is not None:
            parts.append(f"RVol {self.relative_volume:g}")
        if self.float_shares is not None:
            parts.append(f"Float {self.float_shares:,.0f}")
        return " / ".join(parts)


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


def _parse_optional(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text)
    if not match:
        return None
    if len(match.groups()) == 1:
        return float(match.group(1).replace(",", ""))
    return _parse_number(match.group(1), match.group(2))


def parse_volume_signals(
    text: str,
    *,
    min_value: float,
    min_relative_volume: float,
) -> list[VolumeSignal]:
    """Parse mosquito-style volume cards.

    The mosquito channel usually includes labels like 1m/2m/5m/10m/F. Nuntio
    news messages do not, so this avoids treating market-cap labels as volume.
    """
    if not text.strip():
        return []

    volume_matches = list(LABELED_VOLUME_PATTERN.finditer(text))
    relative_volume = _parse_optional(RVOL_PATTERN, text)
    float_shares = _parse_optional(FLOAT_PATTERN, text)
    price = _parse_optional(PRICE_PATTERN, text)

    if not volume_matches and relative_volume is None:
        return []

    max_value = (
        max(_parse_number(match.group(1), match.group(2)) for match in volume_matches)
        if volume_matches
        else 0
    )
    volume_confirmed = max_value >= min_value
    rvol_confirmed = relative_volume is not None and relative_volume >= min_relative_volume
    if not volume_confirmed and not rvol_confirmed:
        return []

    symbols = _candidate_symbols(text)
    now = time.time()
    return [
        VolumeSignal(
            symbol=symbol,
            value=max_value,
            raw=text[:500],
            seen_at=now,
            relative_volume=relative_volume,
            float_shares=float_shares,
            price=price,
        )
        for symbol in symbols
    ]


class VolumeSignalTracker:
    def __init__(self, *, min_value: float, min_relative_volume: float, confirm_seconds: int):
        self.min_value = min_value
        self.min_relative_volume = min_relative_volume
        self.confirm_seconds = confirm_seconds
        self._signals: dict[str, VolumeSignal] = {}

    def update_from_text(self, text: str) -> list[VolumeSignal]:
        signals = parse_volume_signals(
            text,
            min_value=self.min_value,
            min_relative_volume=self.min_relative_volume,
        )
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
