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
    """Moomoo OpenD via futu-api."""

    name = "moomoo"

    def __init__(self, host: str, port: int, fallback: MarketDataProvider):
        self.host = host
        self.port = port
        self.fallback = fallback
        self._ctx = None
        self._connected = False

    def _connect(self):
        if self._connected and self._ctx:
            return self._ctx
        try:
            from futu import OpenQuoteContext

            self._ctx = OpenQuoteContext(host=self.host, port=self.port)
            self._connected = True
            logger.info("Moomoo OpenD connected at %s:%s", self.host, self.port)
            return self._ctx
        except ImportError:
            logger.warning("futu-api not installed — pip install futu-api")
            return None
        except Exception as exc:
            logger.warning("Moomoo connect failed: %s — using Alpaca fallback", exc)
            return None

    def _moomoo_code(self, symbol: str) -> str:
        return f"US.{symbol.upper()}"

    def get_last_price(self, symbol: str) -> float:
        ctx = self._connect()
        if not ctx:
            return self.fallback.get_last_price(symbol)
        try:
            from futu import RET_OK

            ret, data = ctx.get_market_snapshot([self._moomoo_code(symbol)])
            if ret != RET_OK or data is None or data.empty:
                return self.fallback.get_last_price(symbol)
            row = data.iloc[0]
            for col in ("last_price", "cur_price", "ask_price"):
                if col in data.columns and float(row[col]) > 0:
                    return float(row[col])
        except Exception as exc:
            logger.warning("Moomoo price failed for %s: %s", symbol, exc)
        return self.fallback.get_last_price(symbol)

    def get_intraday_bars(self, symbol: str, *, limit: int = 120) -> list[Bar]:
        ctx = self._connect()
        if not ctx:
            return self.fallback.get_intraday_bars(symbol, limit=limit)
        try:
            from futu import KLType, RET_OK

            ret, data, _ = ctx.request_history_kline(
                self._moomoo_code(symbol),
                max_count=limit,
                ktype=KLType.K_1M,
            )
            if ret != RET_OK or data is None or data.empty:
                return self.fallback.get_intraday_bars(symbol, limit=limit)
            bars: list[Bar] = []
            for _, row in data.iterrows():
                bars.append(
                    Bar(
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                )
            return bars
        except Exception as exc:
            logger.warning("Moomoo bars failed for %s: %s", symbol, exc)
            return self.fallback.get_intraday_bars(symbol, limit=limit)


class IBKRDataProvider(MarketDataProvider):
    """Interactive Brokers via ib_insync."""

    name = "ibkr"

    def __init__(self, host: str, port: int, client_id: int, fallback: MarketDataProvider):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.fallback = fallback
        self._ib = None
        self._connected = False

    def _connect(self):
        if self._connected and self._ib and self._ib.isConnected():
            return self._ib
        try:
            from ib_insync import IB

            self._ib = IB()
            self._ib.connect(self.host, self.port, clientId=self.client_id, readonly=True)
            self._connected = True
            logger.info("IBKR connected at %s:%s", self.host, self.port)
            return self._ib
        except ImportError:
            logger.warning("ib_insync not installed — pip install ib_insync")
            return None
        except Exception as exc:
            logger.warning("IBKR connect failed: %s — using Alpaca fallback", exc)
            return None

    def get_last_price(self, symbol: str) -> float:
        ib = self._connect()
        if not ib:
            return self.fallback.get_last_price(symbol)
        try:
            from ib_insync import Stock

            contract = Stock(symbol.upper(), "SMART", "USD")
            ib.qualifyContracts(contract)
            tickers = ib.reqTickers(contract)
            if tickers and tickers[0].marketPrice():
                return float(tickers[0].marketPrice())
            if tickers and tickers[0].last:
                return float(tickers[0].last)
        except Exception as exc:
            logger.warning("IBKR price failed for %s: %s", symbol, exc)
        return self.fallback.get_last_price(symbol)

    def get_intraday_bars(self, symbol: str, *, limit: int = 120) -> list[Bar]:
        ib = self._connect()
        if not ib:
            return self.fallback.get_intraday_bars(symbol, limit=limit)
        try:
            from ib_insync import Stock, util

            contract = Stock(symbol.upper(), "SMART", "USD")
            ib.qualifyContracts(contract)
            bars_data = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr="1 D",
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
            )
            df = util.df(bars_data)
            if df is None or df.empty:
                return self.fallback.get_intraday_bars(symbol, limit=limit)
            df = df.tail(limit)
            return [
                Bar(
                    open=float(row.open),
                    high=float(row.high),
                    low=float(row.low),
                    close=float(row.close),
                    volume=float(row.volume),
                )
                for row in df.itertuples()
            ]
        except Exception as exc:
            logger.warning("IBKR bars failed for %s: %s", symbol, exc)
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
