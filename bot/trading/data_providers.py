"""Market data provider abstraction (Alpaca default, Moomoo/IBKR optional)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from bot.trading.indicators import Bar
from bot.trading.market_data import fetch_intraday_bars

logger = logging.getLogger(__name__)


class MarketDataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_last_price(self, symbol: str) -> float:
        raise NotImplementedError

    @abstractmethod
    def get_intraday_bars(self, symbol: str, *, limit: int = 120) -> list[Bar]:
        raise NotImplementedError


class AlpacaDataProvider(MarketDataProvider):
    name = "alpaca"

    def __init__(self, *, get_clients, get_last_price, get_latest_trade_price):
        self._get_clients = get_clients
        self._get_last_price = get_last_price
        self._get_latest_trade_price = get_latest_trade_price

    def get_last_price(self, symbol: str) -> float:
        try:
            return self._get_last_price(symbol)
        except Exception:
            trade = self._get_latest_trade_price(symbol)
            if trade:
                return trade
            raise

    def get_intraday_bars(self, symbol: str, *, limit: int = 120) -> list[Bar]:
        _, data_client = self._get_clients()
        return fetch_intraday_bars(data_client, symbol, limit=limit)


class MoomooDataProvider(MarketDataProvider):
    """Optional provider — requires buyer Moomoo OpenD credentials."""

    name = "moomoo"

    def __init__(self, host: str, port: int, fallback: MarketDataProvider):
        self.host = host
        self.port = port
        self.fallback = fallback
        self._warned = False

    def _warn_once(self) -> None:
        if self._warned:
            return
        self._warned = True
        logger.warning(
            "Moomoo provider selected but OpenD bridge not configured — falling back to Alpaca"
        )

    def get_last_price(self, symbol: str) -> float:
        self._warn_once()
        return self.fallback.get_last_price(symbol)

    def get_intraday_bars(self, symbol: str, *, limit: int = 120) -> list[Bar]:
        self._warn_once()
        return self.fallback.get_intraday_bars(symbol, limit=limit)


class IBKRDataProvider(MarketDataProvider):
    """Optional provider — requires buyer IB Gateway/TWS setup."""

    name = "ibkr"

    def __init__(self, host: str, port: int, client_id: int, fallback: MarketDataProvider):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.fallback = fallback
        self._warned = False

    def _warn_once(self) -> None:
        if self._warned:
            return
        self._warned = True
        logger.warning(
            "IBKR provider selected but gateway bridge not configured — falling back to Alpaca"
        )

    def get_last_price(self, symbol: str) -> float:
        self._warn_once()
        return self.fallback.get_last_price(symbol)

    def get_intraday_bars(self, symbol: str, *, limit: int = 120) -> list[Bar]:
        self._warn_once()
        return self.fallback.get_intraday_bars(symbol, limit=limit)


def build_data_provider(
    provider_name: str,
    *,
    get_clients,
    get_last_price,
    get_latest_trade_price,
    moomoo_host: str = "127.0.0.1",
    moomoo_port: int = 11111,
    ibkr_host: str = "127.0.0.1",
    ibkr_port: int = 7497,
    ibkr_client_id: int = 1,
) -> MarketDataProvider:
    alpaca = AlpacaDataProvider(
        get_clients=get_clients,
        get_last_price=get_last_price,
        get_latest_trade_price=get_latest_trade_price,
    )
    name = (provider_name or "alpaca").lower()
    if name == "moomoo":
        return MoomooDataProvider(moomoo_host, moomoo_port, alpaca)
    if name == "ibkr":
        return IBKRDataProvider(ibkr_host, ibkr_port, ibkr_client_id, alpaca)
    return alpaca
