"""Tiered profit-taking and trailing stop exit management."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

EXIT_STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "exit_state.json"


@dataclass
class ExitTier:
    profit_percent: float
    sell_percent: float


@dataclass
class PositionExitState:
    symbol: str
    entry_price: float
    original_qty: float
    remaining_qty: float
    tiers_hit: list[int] = field(default_factory=list)
    highest_price: float = 0.0
    trailing_stop_price: float | None = None
    runner_qty: float = 0.0


@dataclass
class ExitAction:
    symbol: str
    qty: float
    reason: str
    profit_percent: float


class ExitManager:
    def __init__(
        self,
        *,
        tiers: list[ExitTier],
        trailing_stop_percent: float,
        runner_hold_percent: float,
        enabled: bool = True,
        round_price,
        get_clients,
        get_last_price,
    ):
        self.tiers = tiers
        self.trailing_stop_percent = trailing_stop_percent
        self.runner_hold_percent = runner_hold_percent
        self.enabled = enabled
        self._round_price = round_price
        self._get_clients = get_clients
        self._get_last_price = get_last_price
        self._states: dict[str, PositionExitState] = {}
        EXIT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def register_fill(self, symbol: str, qty: float, entry_price: float) -> None:
        if not self.enabled or qty <= 0 or entry_price <= 0:
            return
        symbol = symbol.upper()
        runner_qty = qty * self.runner_hold_percent / 100
        self._states[symbol] = PositionExitState(
            symbol=symbol,
            entry_price=entry_price,
            original_qty=qty,
            remaining_qty=qty,
            highest_price=entry_price,
            runner_qty=runner_qty,
        )
        self._save()
        logger.info("Exit plan registered for %s qty=%s entry=$%.4f", symbol, qty, entry_price)

    def evaluate(self, symbol: str) -> list[ExitAction]:
        if not self.enabled:
            return []
        state = self._states.get(symbol.upper())
        if not state or state.remaining_qty <= 0:
            return []

        try:
            price = self._get_last_price(symbol)
        except Exception as exc:
            logger.warning("Exit check price failed for %s: %s", symbol, exc)
            return []

        if price > state.highest_price:
            state.highest_price = price
            if state.highest_price > state.entry_price:
                trail = state.highest_price * (1 - self.trailing_stop_percent / 100)
                state.trailing_stop_price = self._round_price(trail)

        profit_pct = (price / state.entry_price - 1) * 100
        actions: list[ExitAction] = []

        for idx, tier in enumerate(self.tiers):
            if idx in state.tiers_hit:
                continue
            if profit_pct < tier.profit_percent:
                continue
            sell_qty = state.original_qty * tier.sell_percent / 100
            sell_qty = min(sell_qty, state.remaining_qty - state.runner_qty)
            if sell_qty <= 0:
                state.tiers_hit.append(idx)
                continue
            actions.append(
                ExitAction(
                    symbol=state.symbol,
                    qty=round(sell_qty, 4),
                    reason=f"tier +{tier.profit_percent:g}% → sell {tier.sell_percent:g}%",
                    profit_percent=profit_pct,
                )
            )
            state.tiers_hit.append(idx)

        if (
            state.trailing_stop_price
            and price <= state.trailing_stop_price
            and state.remaining_qty > 0
        ):
            actions.append(
                ExitAction(
                    symbol=state.symbol,
                    qty=state.remaining_qty,
                    reason=f"trailing stop @ ${state.trailing_stop_price:.2f}",
                    profit_percent=profit_pct,
                )
            )

        if actions:
            self._save()
        return actions

    def evaluate_all(self) -> list[ExitAction]:
        return [action for symbol in list(self._states) for action in self.evaluate(symbol)]

    def execute_actions(self, actions: list[ExitAction]) -> list[str]:
        if not actions:
            return []
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        trading_client, _ = self._get_clients()
        messages: list[str] = []
        for action in actions:
            try:
                order = trading_client.submit_order(
                    MarketOrderRequest(
                        symbol=action.symbol,
                        qty=action.qty,
                        side=OrderSide.SELL,
                        time_in_force=TimeInForce.DAY,
                    )
                )
                state = self._states.get(action.symbol)
                if state:
                    state.remaining_qty = max(0.0, state.remaining_qty - action.qty)
                    if state.remaining_qty <= 0:
                        state.remaining_qty = 0
                messages.append(
                    f"SELL {action.symbol} x{action.qty} ({action.reason}) order {order.id}"
                )
            except Exception as exc:
                messages.append(f"SELL {action.symbol} failed: {exc}")
        self._save()
        return messages

    def status_lines(self) -> list[str]:
        lines: list[str] = []
        for state in self._states.values():
            if state.remaining_qty <= 0:
                continue
            trail = (
                f"${state.trailing_stop_price:.2f}"
                if state.trailing_stop_price
                else "not active"
            )
            lines.append(
                f"`{state.symbol}` entry ${state.entry_price:.2f} | "
                f"remaining {state.remaining_qty:g}/{state.original_qty:g} | "
                f"high ${state.highest_price:.2f} | trail {trail} | "
                f"tiers hit {len(state.tiers_hit)}/{len(self.tiers)}"
            )
        return lines or ["No active exit plans."]

    def _load(self) -> None:
        if not EXIT_STATE_FILE.exists():
            return
        try:
            raw = json.loads(EXIT_STATE_FILE.read_text(encoding="utf-8"))
            self._states = {
                symbol.upper(): PositionExitState(**data)
                for symbol, data in raw.items()
                if isinstance(data, dict)
            }
        except Exception:
            self._states = {}

    def _save(self) -> None:
        payload = {symbol: asdict(state) for symbol, state in self._states.items()}
        EXIT_STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
