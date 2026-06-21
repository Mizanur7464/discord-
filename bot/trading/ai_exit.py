"""AI-assisted exit decisions using volume + flexible grid context."""

from __future__ import annotations

import json
import logging

import aiohttp

from bot.trading.grid_exit import VolumeContext

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = """You advise a low-cap momentum day-trading exit bot with a flexible profit grid.

Return JSON only:
{"action":"hold"|"sell_partial"|"sell_all"|"defer_tier","sell_percent":0-100,"reason":"short phrase"}

Actions:
- hold = volume/momentum still strong; skip selling now and wait for a better grid level
- defer_tier = current grid level reached but volume supports holding for the next tier
- sell_partial = lock gains but keep a runner (sell_percent 25-50)
- sell_all = cut loss, take profit now, or volume collapsing / bad momentum

Rules:
- Strong RVOL + rising 1m volume → prefer hold or defer_tier
- Falling volume + profit already up → prefer sell_partial or sell_all
- Small profit (<5%) with healthy volume → hold
- Loss beyond ~3% with falling volume → sell_all
- If next grid tier is close and volume is rising, defer_tier is OK"""


async def advise_exit(
    *,
    symbol: str,
    entry_price: float,
    current_price: float,
    profit_percent: float,
    volume: VolumeContext,
    tiers_hit: int,
    total_tiers: int,
    next_tier_profit: float | None,
    trailing_stop: float | None,
    api_key: str,
    model: str = "gpt-4o-mini",
    timeout: float = 8.0,
) -> tuple[str, float, str]:
    """Return (action, sell_percent, reason)."""
    if not api_key:
        return "hold", 0.0, "AI exit disabled — no API key"

    trail_line = f"${trailing_stop:.2f}" if trailing_stop else "none"
    next_line = f"+{next_tier_profit:g}%" if next_tier_profit is not None else "none"

    user_text = (
        f"Symbol: {symbol}\n"
        f"Entry: ${entry_price:.4f}\n"
        f"Current: ${current_price:.4f}\n"
        f"Profit: {profit_percent:.2f}%\n"
        f"Volume: {volume.trend_label}\n"
        f"Grid tiers hit: {tiers_hit}/{total_tiers}\n"
        f"Next grid tier: {next_line}\n"
        f"Trailing stop: {trail_line}"
    )
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 90,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    client_timeout = aiohttp.ClientTimeout(total=timeout)
    from aiohttp.resolver import ThreadedResolver

    connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
    try:
        async with aiohttp.ClientSession(timeout=client_timeout, connector=connector) as session:
            async with session.post(OPENAI_CHAT_URL, json=payload, headers=headers) as resp:
                body = await resp.text()
                if resp.status != 200:
                    logger.warning("AI exit HTTP %s: %s", resp.status, body[:120])
                    return "hold", 0.0, "AI exit error"
                data = json.loads(body)
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                action = str(parsed.get("action", "hold")).lower().strip()
                sell_percent = float(parsed.get("sell_percent", 0) or 0)
                reason = str(parsed.get("reason", "ai exit")).strip() or "ai exit"
                if action not in {"hold", "sell_partial", "sell_all", "defer_tier"}:
                    action = "hold"
                sell_percent = max(0.0, min(100.0, sell_percent))
                if action == "sell_partial" and sell_percent <= 0:
                    sell_percent = 30.0
                if action == "sell_all":
                    sell_percent = 100.0
                logger.info("AI exit %s: %s (%s%%) — %s", symbol, action, sell_percent, reason)
                return action, sell_percent, reason
    except Exception as exc:
        logger.warning("AI exit failed for %s: %s", symbol, exc)
        return "hold", 0.0, f"AI exit error ({exc})"
