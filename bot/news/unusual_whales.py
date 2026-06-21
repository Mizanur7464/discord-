"""Unusual Whales API — options flow and unusual activity."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

UW_BASE = "https://api.unusualwhales.com"


@dataclass
class WhaleFlowAlert:
    symbol: str
    premium: float | None = None
    volume: float | None = None
    alert_rule: str = ""
    raw: str = ""


@dataclass
class WhaleSnapshot:
    symbol: str
    alerts: list[WhaleFlowAlert] = field(default_factory=list)
    total_premium: float = 0.0
    bullish_flow: bool = False

    @property
    def summary(self) -> str:
        if not self.alerts:
            return "no unusual flow"
        return f"{len(self.alerts)} flow alert(s), premium ~${self.total_premium:,.0f}"


def _uw_get(path: str, api_key: str, params: dict | None = None) -> dict | list | None:
    if not api_key:
        return None
    query = ""
    if params:
        parts = []
        for key, value in params.items():
            if isinstance(value, list):
                for item in value:
                    parts.append(f"{quote(key)}={quote(str(item))}")
            else:
                parts.append(f"{quote(key)}={quote(str(value))}")
        query = "?" + "&".join(parts)
    url = f"{UW_BASE}{path}{query}"
    req = Request(url, headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("Unusual Whales request failed %s: %s", path, exc)
        return None


def fetch_flow_alerts(api_key: str, *, limit: int = 50) -> list[WhaleFlowAlert]:
    payload = _uw_get(
        "/api/option-trades/flow-alerts",
        api_key,
        params={
            "issue_types[]": ["Common Stock", "ADR"],
            "min_dte": 1,
            "limit": limit,
        },
    )
    if not payload:
        return []
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    alerts: list[WhaleFlowAlert] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        sym = (row.get("ticker") or row.get("symbol") or "").upper()
        if not sym:
            continue
        alerts.append(
            WhaleFlowAlert(
                symbol=sym,
                premium=_float(row.get("total_premium") or row.get("premium")),
                volume=_float(row.get("volume")),
                alert_rule=str(row.get("alert_rule") or row.get("rule_name") or ""),
                raw=str(row)[:300],
            )
        )
    return alerts


def fetch_symbol_flow(api_key: str, symbol: str) -> WhaleSnapshot:
    symbol = symbol.upper()
    snap = WhaleSnapshot(symbol=symbol)
    payload = _uw_get(f"/api/stock/{quote(symbol)}/flow-recent", api_key)
    if not payload:
        payload = _uw_get(
            "/api/option-trades/flow-alerts",
            api_key,
            params={"ticker": symbol, "limit": 20},
        )
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return snap
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_sym = (row.get("ticker") or row.get("symbol") or symbol).upper()
        if row_sym != symbol:
            continue
        premium = _float(row.get("total_premium") or row.get("premium")) or 0.0
        alert = WhaleFlowAlert(
            symbol=row_sym,
            premium=premium,
            volume=_float(row.get("volume")),
            alert_rule=str(row.get("alert_rule") or row.get("rule_name") or ""),
        )
        snap.alerts.append(alert)
        snap.total_premium += premium
    snap.bullish_flow = snap.total_premium >= 200_000 or len(snap.alerts) >= 2
    return snap


def score_whale_flow(snap: WhaleSnapshot | None) -> tuple[int, list[str], list[str]]:
    if not snap or not snap.alerts:
        return 0, [], []
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []
    if snap.bullish_flow:
        score += 10
        reasons.append(f"Unusual Whales flow: {snap.summary}")
    elif snap.alerts:
        score += 5
        reasons.append(f"Unusual Whales activity: {len(snap.alerts)} alert(s)")
    if snap.total_premium >= 500_000:
        score += 5
        reasons.append(f"high premium flow ~${snap.total_premium:,.0f}")
    return score, reasons, warnings


def _float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
