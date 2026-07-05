"""SDS-Core-03 §6 structured AI output for News Intelligence."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import aiohttp

from bot.news.ai_sentiment import OPENAI_CHAT_URL
from bot.news.news_intelligence import IMPACT_EMOJI, NewsImpact

logger = logging.getLogger(__name__)

INTELLIGENCE_SYSTEM_PROMPT = """You analyze US low-cap stock news for a trading intelligence feed.

Return JSON only with these fields:
{
  "sentiment": "Bullish|Bearish|Neutral",
  "summary": "1-2 sentence trader-focused summary",
  "suggested_action": "guidance phrase — never say buy or sell directly",
  "liquidity_risk": "Low|Medium|High",
  "keyword": "primary catalyst keyword phrase"
}

Rules:
- suggested_action informs judgment; use Monitor, Research, Immediate Watch style guidance
- if dilution/offering, sentiment is usually Bearish and liquidity_risk Medium or High
- summary must mention the main catalyst clearly
- keep summary under 220 characters"""


@dataclass
class NewsAIOutput:
    impact_level: str
    impact_emoji: str
    sentiment: str
    confidence: float
    dilution_risk: bool
    liquidity_risk: str
    category: str
    keyword: str
    summary: str
    suggested_action: str
    catalyst_type: str = ""
    catalyst_tags: list[str] = field(default_factory=list)
    crowd_attention_score: int = 0
    smart_alert: bool = False
    timeline_note: str = ""


def _actionability_label(impact: NewsImpact) -> str:
    from bot.news.impact_routing import ACTIONABILITY_LABELS

    return ACTIONABILITY_LABELS.get(impact.level, "Monitor")


def build_ai_output_from_rules(
    impact: NewsImpact,
    *,
    sentiment: str = "neutral",
    ai_reason: str = "",
) -> NewsAIOutput:
    """Fallback §6 envelope from keyword/rule engine when OpenAI unavailable."""
    sent_map = {"bullish": "Bullish", "ignored": "Bearish", "bearish": "Bearish", "neutral": "Neutral"}
    sent = sent_map.get((sentiment or "neutral").lower(), "Neutral")
    keyword = (impact.matched_keywords or [""])[0] if impact.matched_keywords else impact.catalyst_type
    summary = ai_reason or impact.reason or impact.category or "No clear catalyst"
    return NewsAIOutput(
        impact_level=impact.level,
        impact_emoji=impact.emoji,
        sentiment=sent,
        confidence=float(impact.confidence or 75.0),
        dilution_risk=bool(impact.dilution_risk),
        liquidity_risk="Medium" if impact.level in {"high", "medium"} else "Low",
        category=impact.category or impact.catalyst_type or "News",
        keyword=keyword or "—",
        summary=summary[:220],
        suggested_action=_actionability_label(impact),
        catalyst_type=impact.catalyst_type or "",
        catalyst_tags=list(impact.catalyst_tags or []),
    )


async def classify_news_ai_output(
    *,
    headline: str,
    article_text: str,
    symbol: str,
    impact: NewsImpact,
    api_key: str,
    model: str = "gpt-4o-mini",
    timeout: float = 12.0,
) -> NewsAIOutput | None:
    """OpenAI structured output enriched with rule-engine context."""
    if not api_key or not headline.strip():
        return None

    body = article_text.strip()
    if len(body) > 3500:
        body = body[:3500]

    user = (
        f"Symbol: {symbol}\n"
        f"Headline: {headline}\n"
        f"Rule impact: {impact.level} ({impact.category})\n"
        f"Dilution risk: {'Yes' if impact.dilution_risk else 'No'}\n"
    )
    if body and body != headline:
        user += f"\nArticle text:\n{body}"

    payload = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 220,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": INTELLIGENCE_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    from aiohttp.resolver import ThreadedResolver

    connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
    try:
        async with aiohttp.ClientSession(timeout=client_timeout, connector=connector) as session:
            async with session.post(OPENAI_CHAT_URL, json=payload, headers=headers) as resp:
                raw = await resp.text()
                if resp.status != 200:
                    logger.warning("News AI output HTTP %s: %s", resp.status, raw[:200])
                    return None
                data = json.loads(raw)
                content = data["choices"][0]["message"]["content"].strip()
                parsed = json.loads(content)
    except (aiohttp.ClientError, KeyError, json.JSONDecodeError) as exc:
        logger.warning("News AI output failed: %s", exc)
        return None

    sentiment = str(parsed.get("sentiment", "Neutral")).strip().title()
    if sentiment not in {"Bullish", "Bearish", "Neutral"}:
        sentiment = "Neutral"
    liquidity = str(parsed.get("liquidity_risk", "Medium")).strip().title()
    if liquidity not in {"Low", "Medium", "High"}:
        liquidity = "Medium"

    return NewsAIOutput(
        impact_level=impact.level,
        impact_emoji=impact.emoji,
        sentiment=sentiment,
        confidence=float(impact.confidence or 80.0),
        dilution_risk=bool(impact.dilution_risk),
        liquidity_risk=liquidity,
        category=impact.category or impact.catalyst_type or "News",
        keyword=str(parsed.get("keyword", "")).strip() or (impact.matched_keywords or ["—"])[0],
        summary=str(parsed.get("summary", "")).strip()[:220],
        suggested_action=str(parsed.get("suggested_action", "")).strip()[:180]
        or _actionability_label(impact),
        catalyst_type=impact.catalyst_type or "",
        catalyst_tags=list(impact.catalyst_tags or []),
    )
