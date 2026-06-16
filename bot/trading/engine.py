"""Stock trading engine using Alpaca API."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from bot.news.symbols import extract_stock_symbol
from bot.trading.schedule import is_regular_market_hours, trading_block_reason
from bot.trading.volume import get_daily_volume
from bot.utils.config import Settings

logger = logging.getLogger(__name__)

TRADES_FILE = Path(__file__).resolve().parents[2] / "data" / "trades_log.json"


@dataclass
class TradeResult:
    success: bool
    message: str
    side: str
    symbol: str
    amount: float
    price: float | None = None
    paper: bool = True


class TradingEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None
        self._data_client = None
        self._trades_today = 0
        self._last_trade_date = date.today()
        self._symbols_today: set[str] = set()
        TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _reset_daily_count(self) -> None:
        today = date.today()
        if today != self._last_trade_date:
            self._trades_today = 0
            self._symbols_today.clear()
            self._last_trade_date = today

    def _is_trading_allowed(self) -> str:
        cfg = self.settings.trading
        return trading_block_reason(
            block_saturday=cfg.block_saturday,
            block_sunday=cfg.block_sunday,
            block_monday_premarket=cfg.block_monday_premarket,
            regular_market_hours_only=cfg.regular_market_hours_only,
            extended_hours_trading=cfg.extended_hours_trading,
        )

    @staticmethod
    def _round_price(price: float) -> float:
        if price >= 1:
            return round(price, 2)
        return round(price, 4)

    @staticmethod
    def _round_price_down(price: float, ref: float) -> float:
        if ref >= 1:
            return math.floor(price * 100) / 100
        return math.floor(price * 10000) / 10000

    def _calc_bracket_prices(self, price: float) -> tuple[float, float]:
        tp_pct = self.settings.trading.take_profit_percent / 100
        sl_pct = self.settings.trading.stop_loss_percent / 100
        take_profit = self._round_price(price * (1 + tp_pct))
        stop_loss = self._round_price_down(price * (1 - sl_pct), price)
        max_stop = self._round_price_down(price - 0.01, price)
        if stop_loss > max_stop:
            stop_loss = max_stop
        min_tick = 0.0001 if price < 1 else 0.01
        if stop_loss >= price - min_tick:
            stop_loss = self._round_price_down(price - min_tick, price)
        return take_profit, stop_loss

    @staticmethod
    def _calc_qty(amount_usd: float, price: float) -> float:
        raw = amount_usd / price
        if raw >= 1:
            return float(max(1, int(raw)))
        qty = round(raw, 4)
        if qty <= 0:
            raise ValueError(f"Trade amount ${amount_usd:.2f} too small for price ${price:.4f}")
        return qty

    def _get_clients(self):
        if self._client is not None:
            return self._client, self._data_client

        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.trading.client import TradingClient

        api_key = self.settings.alpaca_api_key
        secret_key = self.settings.alpaca_secret_key
        paper = self.settings.alpaca_paper

        self._client = TradingClient(api_key, secret_key, paper=paper)
        self._data_client = StockHistoricalDataClient(api_key, secret_key)
        return self._client, self._data_client

    def _resolve_symbol(self, symbol: str, text: str) -> str:
        resolved = (symbol or extract_stock_symbol(text)).upper()
        if resolved:
            return resolved
        return self.settings.trading.default_symbol.upper()

    def _get_last_price(self, symbol: str) -> float:
        from alpaca.data.requests import StockLatestQuoteRequest

        _, data_client = self._get_clients()
        quote = data_client.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbol)
        )
        data = quote[symbol]
        if data.ask_price and data.ask_price > 0:
            return float(data.ask_price)
        if data.bid_price and data.bid_price > 0:
            return float(data.bid_price)
        raise ValueError(f"No quote available for {symbol}")

    def _resolve_trade_amount(self, symbol: str) -> tuple[float, str]:
        """Apply low-volume rules. Returns (amount_usd, note for logs/alerts)."""
        cfg = self.settings.trading
        if not cfg.volume_filter_enabled:
            return cfg.trade_amount_usd, ""

        try:
            _, data_client = self._get_clients()
            volume = get_daily_volume(data_client, symbol)
        except Exception as exc:
            logger.warning("Volume check failed for %s: %s — using reduced size", symbol, exc)
            return cfg.low_volume_trade_amount_usd, " (volume unknown — reduced size)"

        if volume < cfg.min_volume_skip:
            raise ValueError(
                f"Low volume skip — {symbol} daily volume {volume:,} "
                f"< min {cfg.min_volume_skip:,}"
            )

        if volume < cfg.low_volume_threshold:
            return (
                cfg.low_volume_trade_amount_usd,
                f" (high-risk low volume {volume:,} — ${cfg.low_volume_trade_amount_usd:.0f} size)",
            )

        return cfg.trade_amount_usd, f" (volume {volume:,})"

    def _log_trade(self, result: TradeResult) -> None:
        logs: list[dict] = []
        if TRADES_FILE.exists():
            with open(TRADES_FILE, encoding="utf-8") as f:
                logs = json.load(f)

        logs.append(
            {
                "side": result.side,
                "symbol": result.symbol,
                "amount": result.amount,
                "price": result.price,
                "paper": result.paper,
                "message": result.message,
            }
        )

        with open(TRADES_FILE, "w", encoding="utf-8") as f:
            json.dump(logs[-100:], f, indent=2)

    async def process_signal(
        self,
        sentiment: str,
        *,
        symbol: str = "",
        text: str = "",
    ) -> TradeResult | None:
        """Handle bullish buy or bad-news cancel."""
        if sentiment == "ignored":
            return await self.handle_bad_news(symbol=symbol, text=text)
        if sentiment == "bullish":
            return await self.execute(sentiment, symbol=symbol, text=text)
        return None

    async def handle_bad_news(self, *, symbol: str = "", text: str = "") -> TradeResult | None:
        if not self.settings.trading.enabled:
            return None
        if not self.settings.trading.cancel_orders_on_bad_news:
            return TradeResult(
                success=False,
                message="Bad news ignored — cancel on bad news is disabled.",
                side="none",
                symbol=symbol or "N/A",
                amount=0,
            )

        stock = self._resolve_symbol(symbol, text)
        if not stock:
            return TradeResult(
                success=False,
                message="Bad news signal — no stock symbol to cancel.",
                side="none",
                symbol="N/A",
                amount=0,
            )

        if not self.settings.alpaca_api_key or not self.settings.alpaca_secret_key:
            return TradeResult(
                success=False,
                message=f"Bad news for {stock} — Alpaca keys not set.",
                side="none",
                symbol=stock,
                amount=0,
            )

        try:
            count = self._cancel_open_orders(stock)
            msg = f"Bad news on {stock} — cancelled {count} open order(s)."
            if count == 0:
                msg = f"Bad news on {stock} — no open orders to cancel."
        except Exception as exc:
            return TradeResult(
                success=False,
                message=f"Cancel failed for {stock}: {exc}",
                side="cancel",
                symbol=stock,
                amount=0,
            )

        result = TradeResult(
            success=True,
            message=msg,
            side="cancel",
            symbol=stock,
            amount=0,
            paper=self.settings.alpaca_paper,
        )
        self._log_trade(result)
        return result

    def _cancel_open_orders(self, symbol: str) -> int:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        trading_client, _ = self._get_clients()
        orders = trading_client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        )
        for order in orders:
            trading_client.cancel_order_by_id(order.id)
        return len(orders)

    async def execute(
        self,
        sentiment: str,
        *,
        symbol: str = "",
        text: str = "",
    ) -> TradeResult | None:
        """Execute a stock buy on Alpaca when sentiment is bullish."""
        if not self.settings.trading.enabled:
            return None

        if sentiment != "bullish":
            return None

        self._reset_daily_count()

        block = self._is_trading_allowed()
        if block:
            return TradeResult(
                success=False,
                message=block,
                side="blocked",
                symbol=symbol or "N/A",
                amount=0,
            )

        max_trades = self.settings.trading.max_trades_per_day

        if self._trades_today >= max_trades:
            return TradeResult(
                success=False,
                message=f"Daily trade limit ({max_trades}) reached.",
                side="none",
                symbol=symbol or "N/A",
                amount=0,
            )

        stock = self._resolve_symbol(symbol, text)
        if not stock:
            return TradeResult(
                success=False,
                message="No stock symbol found in news. Set default_symbol in settings.yaml.",
                side="none",
                symbol="N/A",
                amount=0,
            )

        cfg = self.settings.trading
        if cfg.one_trade_per_symbol_per_day and stock in self._symbols_today:
            return TradeResult(
                success=False,
                message=f"Already traded {stock} today — skipping duplicate buy.",
                side="none",
                symbol=stock,
                amount=0,
            )

        amount_usd = cfg.trade_amount_usd
        paper = self.settings.alpaca_paper

        if not self.settings.alpaca_api_key or not self.settings.alpaca_secret_key:
            return TradeResult(
                success=False,
                message="Alpaca API keys not set. Add ALPACA_API_KEY and ALPACA_SECRET_KEY to .env.",
                side="buy",
                symbol=stock,
                amount=amount_usd,
                paper=paper,
            )

        try:
            amount_usd, volume_note = self._resolve_trade_amount(stock)
        except ValueError as exc:
            return TradeResult(
                success=False,
                message=str(exc),
                side="blocked",
                symbol=stock,
                amount=0,
            )

        try:
            if is_regular_market_hours():
                result = self._place_bracket_buy(stock, amount_usd, paper, volume_note=volume_note)
            else:
                result = self._place_market_buy(
                    stock,
                    amount_usd,
                    paper,
                    volume_note=volume_note,
                    extended_hours=True,
                )
        except Exception as exc:
            logger.error("Buy failed for %s: %s — trying fallback order", stock, exc)
            try:
                result = self._place_market_buy(
                    stock,
                    amount_usd,
                    paper,
                    volume_note=volume_note,
                    extended_hours=not is_regular_market_hours(),
                )
            except Exception as fallback_exc:
                result = TradeResult(
                    success=False,
                    message=f"Trade failed: {fallback_exc}",
                    side="buy",
                    symbol=stock,
                    amount=amount_usd,
                    paper=paper,
                )

        if result.success:
            self._trades_today += 1
            self._symbols_today.add(stock)

        self._log_trade(result)
        return result

    def _place_bracket_buy(
        self,
        symbol: str,
        amount_usd: float,
        paper: bool,
        *,
        volume_note: str = "",
    ) -> TradeResult:
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (
            MarketOrderRequest,
            StopLossRequest,
            TakeProfitRequest,
        )

        trading_client, _ = self._get_clients()
        price = self._get_last_price(symbol)

        take_profit, stop_loss = self._calc_bracket_prices(price)
        qty = self._calc_qty(amount_usd, price)

        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=take_profit),
            stop_loss=StopLossRequest(stop_price=stop_loss),
        )
        order = trading_client.submit_order(order_data)

        mode = "PAPER" if paper else "LIVE"
        return TradeResult(
            success=True,
            message=(
                f"[{mode}] BUY {symbol} x{qty} ~${amount_usd:.2f}{volume_note} | "
                f"TP ${take_profit} | SL ${stop_loss} | Order {order.id}"
            ),
            side="buy",
            symbol=symbol,
            amount=amount_usd,
            price=price,
            paper=paper,
        )

    def _place_market_buy(
        self,
        symbol: str,
        amount_usd: float,
        paper: bool,
        *,
        volume_note: str = "",
        extended_hours: bool = False,
    ) -> TradeResult:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        trading_client, _ = self._get_clients()
        price = self._get_last_price(symbol)
        qty = self._calc_qty(amount_usd, price)

        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            extended_hours=extended_hours,
        )
        order = trading_client.submit_order(order_data)

        mode = "PAPER" if paper else "LIVE"
        session = " extended" if extended_hours else ""
        return TradeResult(
            success=True,
            message=(
                f"[{mode}] BUY {symbol} x{qty} ~${amount_usd:.2f}{volume_note} | "
                f"{session} market order {order.id}"
            ),
            side="buy",
            symbol=symbol,
            amount=amount_usd,
            price=price,
            paper=paper,
        )

    def get_status(self) -> str:
        mode = "PAPER (test)" if self.settings.alpaca_paper else "LIVE (real money!)"
        trading = "enabled" if self.settings.trading.enabled else "disabled"
        cfg = self.settings.trading
        return (
            f"**Trading Status**\n"
            f"Broker: Alpaca\n"
            f"Mode: {mode}\n"
            f"Auto trade: {trading}\n"
            f"Per trade: ${cfg.trade_amount_usd:.2f}\n"
            f"Take profit: {cfg.take_profit_percent}%\n"
            f"Stop loss: {cfg.stop_loss_percent}%\n"
            f"Trades today: {self._trades_today}/{cfg.max_trades_per_day}\n"
            f"One buy per symbol/day: {'yes' if cfg.one_trade_per_symbol_per_day else 'no'}\n"
            f"Cancel on bad news: {'yes' if cfg.cancel_orders_on_bad_news else 'no'}\n"
            f"Trading hours: "
            f"{'regular only (9:30 AM–4 PM ET)' if cfg.regular_market_hours_only else 'extended (Mon–Fri 4 AM–8 PM ET)'}\n"
            f"Volume filter: {'on' if cfg.volume_filter_enabled else 'off'} "
            f"(skip <{cfg.min_volume_skip:,}, reduced <{cfg.low_volume_threshold:,} @ ${cfg.low_volume_trade_amount_usd:.0f})\n"
            f"Weekend block: Sat={cfg.block_saturday}, Sun={cfg.block_sunday}"
        )
