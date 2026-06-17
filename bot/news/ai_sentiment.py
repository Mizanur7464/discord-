"""OpenAI headline sentiment for news trading signals."""

from __future__ import annotations

import json
import logging
import re

import aiohttp

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = """You classify US stock news headlines for a fast day-trading bot.

Return JSON only:
{"sentiment":"bullish"|"ignored"|"neutral","reason":"short phrase"}

bullish = clear positive catalyst to buy (patent granted, partnership, contract win, FDA approval, upgrade, compliance regained, strong growth beat, acquisition, license deal)
ignored = clear negative (offering, dilution, bankruptcy, delisting, probe, resignation, missed earnings, revenue down, default)
neutral = routine filings, unclear impact, or not a trade catalyst

Judge the headline only. Ignore company boilerplate about being an AI company unless the headline itself is the catalyst."""


class AISentimentError(Exception):
    pass


def _parse_ai_response(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    try:
        data = json.loads(raw)
        sentiment = str(data.get("sentiment", "")).lower().strip()
        reason = str(data.get("reason", "ai")).strip() or "ai"
    except json.JSONDecodeError:
        upper = raw.upper()
        if "BULLISH" in upper or "IGNORE" in upper:
            if "IGNORE" in upper and "BULLISH" not in upper:
                return "ignored", raw[:60]
            if "BULLISH" in upper:
                return "bullish", raw[:60]
        match = re.search(r"\b(bullish|ignored|ignore|neutral)\b", raw, re.IGNORECASE)
        if not match:
            raise AISentimentError(f"Unparseable AI response: {raw[:120]}")
        sentiment = match.group(1).lower()
        reason = raw[:60]
        if sentiment == "ignore":
            sentiment = "ignored"

    if sentiment not in {"bullish", "ignored", "neutral"}:
        raise AISentimentError(f"Invalid sentiment: {sentiment}")
    return sentiment, reason


async def classify_headline(
    headline: str,
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    symbol: str = "",
    timeout: float = 10.0,
) -> tuple[str, str]:
    """Classify a headline as bullish, ignored, or neutral."""
    headline = headline.strip()
    if not headline:
        return "neutral", "empty headline"
    if not api_key:
        raise AISentimentError("OpenAI API key not configured")

    user_text = headline if not symbol else f"Symbol: {symbol}\nHeadline: {headline}"

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 80,
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
                    raise AISentimentError(f"OpenAI HTTP {resp.status}: {body[:200]}")

                data = json.loads(body)
                content = data["choices"][0]["message"]["content"]
                sentiment, reason = _parse_ai_response(content)
                logger.info("AI sentiment: %s — %s (%s)", symbol or "?", sentiment, reason)
                return sentiment, reason
    except aiohttp.ClientError as exc:
        raise AISentimentError(f"OpenAI network error: {exc}") from exc
