"""OpenAI news sentiment for trading signals."""

from __future__ import annotations

import json
import logging
import re

import aiohttp

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = """You classify US stock news for a fast day-trading bot.

Return JSON only:
{"sentiment":"bullish"|"ignored"|"neutral","reason":"short phrase"}

bullish = clear positive catalyst to buy (patent granted, partnership, contract win, FDA approval, upgrade, compliance regained, strong growth beat, acquisition, license deal, major new product launch with near-term commercial impact)
ignored = clear negative (offering, dilution, bankruptcy, delisting, probe, resignation, missed earnings, revenue down, default)
neutral = routine filings, awards/nominations, unclear impact, PR with no near-term trading catalyst, or not enough information

Read the headline and article text. Use the article text to understand the real catalyst, but ignore company boilerplate and generic "AI company" descriptions.
If there is not enough real news text, return neutral with reason "insufficient news text".
Do not return ignored unless the headline clearly describes negative news.
Keep the reason buyer-friendly and specific; do not say "insufficient headline" when article text was provided."""


SUMMARY_SYSTEM_PROMPT = """You summarize general/world news (politics, economy, macro) for a trading Discord.
Write ONE short, plain sentence (max 25 words) capturing the key point.
No preamble, no "this article", no markdown. Just the sentence."""


class AISentimentError(Exception):
    pass


async def summarize_world_news(
    headline: str,
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    article_text: str = "",
    timeout: float = 10.0,
) -> str:
    """Return a short one-sentence summary for no-symbol general/world news."""
    headline = headline.strip()
    if not headline or not api_key:
        return headline

    article_text = article_text.strip()
    if len(article_text) > 3000:
        article_text = article_text[:3000]
    user_text = f"Headline: {headline}"
    if article_text and article_text != headline:
        user_text = f"{user_text}\n\nArticle text:\n{article_text}"

    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 60,
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
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
                    logger.warning("World-news summary HTTP %s: %s", resp.status, body[:200])
                    return headline
                data = json.loads(body)
                return data["choices"][0]["message"]["content"].strip() or headline
    except (aiohttp.ClientError, KeyError, json.JSONDecodeError) as exc:
        logger.warning("World-news summary failed: %s", exc)
        return headline


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
    article_text: str = "",
    timeout: float = 10.0,
) -> tuple[str, str]:
    """Classify a news headline and optional article text as bullish, ignored, or neutral."""
    headline = headline.strip()
    if not headline:
        return "neutral", "empty headline"
    if not api_key:
        raise AISentimentError("OpenAI API key not configured")

    article_text = article_text.strip()
    if len(article_text) > 3500:
        article_text = article_text[:3500]

    user_text = f"Headline: {headline}"
    if symbol:
        user_text = f"Symbol: {symbol}\n{user_text}"
    if article_text and article_text != headline:
        user_text = f"{user_text}\n\nArticle text:\n{article_text}"

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
