"""Broad market universe scanner via Alpaca screener (most actives + movers)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class UniverseCandidate:
    symbol: str
    source: str
    rank: int = 0
    change_pct: float | None = None
    volume: int | None = None


@dataclass
class UniverseScanResult:
    candidates: list[UniverseCandidate] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.symbols)


def fetch_universe_symbols(
    api_key: str,
    secret_key: str,
    *,
    most_actives_top: int = 100,
    movers_top: int = 50,
    min_price: float = 0.5,
    max_price: float = 20.0,
) -> UniverseScanResult:
    """Return merged symbol list from Alpaca most-actives and market movers."""
    if not api_key or not secret_key:
        return UniverseScanResult()

    from alpaca.data.enums import MarketType, MostActivesBy
    from alpaca.data.historical.screener import ScreenerClient
    from alpaca.data.requests import MarketMoversRequest, MostActivesRequest

    client = ScreenerClient(api_key, secret_key)
    result = UniverseScanResult()
    seen: set[str] = set()

    def _add(symbol: str, source: str, rank: int, change_pct: float | None = None, volume: int | None = None) -> None:
        symbol = symbol.upper()
        if symbol in seen:
            return
        seen.add(symbol)
        result.candidates.append(
            UniverseCandidate(
                symbol=symbol,
                source=source,
                rank=rank,
                change_pct=change_pct,
                volume=volume,
            )
        )
        result.symbols.append(symbol)

    try:
        actives = client.get_most_actives(
            MostActivesRequest(top=most_actives_top, by=MostActivesBy.VOLUME)
        )
        for idx, item in enumerate(getattr(actives, "most_actives", []) or []):
            sym = getattr(item, "symbol", None) or (item.get("symbol") if isinstance(item, dict) else None)
            vol = getattr(item, "volume", None) or (item.get("volume") if isinstance(item, dict) else None)
            if sym:
                _add(sym, "most_active", idx + 1, volume=int(vol) if vol else None)
    except Exception as exc:
        logger.warning("Most actives fetch failed: %s", exc)

    try:
        movers = client.get_market_movers(MarketMoversRequest(top=movers_top, market_type=MarketType.STOCKS))
        for idx, item in enumerate(getattr(movers, "gainers", []) or []):
            sym = getattr(item, "symbol", None) or (item.get("symbol") if isinstance(item, dict) else None)
            pct = getattr(item, "percent_change", None) or (item.get("percent_change") if isinstance(item, dict) else None)
            if sym:
                _add(sym, "gainer", idx + 1, change_pct=float(pct) if pct is not None else None)
        for idx, item in enumerate(getattr(movers, "losers", []) or []):
            sym = getattr(item, "symbol", None) or (item.get("symbol") if isinstance(item, dict) else None)
            if sym:
                _add(sym, "loser", idx + 1)
    except Exception as exc:
        logger.warning("Market movers fetch failed: %s", exc)

    logger.info("Universe scan found %s symbols", result.count)
    return result
