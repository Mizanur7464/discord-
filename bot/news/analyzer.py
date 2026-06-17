"""Analyze Discord messages for trading signals via OpenAI."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from bot.news.ai_sentiment import AISentimentError, classify_headline
from bot.news.symbols import extract_stock_symbol, is_nuntio_header_line
from bot.utils.config import NewsConfig
from bot.utils.timing import mark_step

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: str
    sentiment: str  # "bullish", "ignored", or "neutral"
    ai_reason: str
    message_id: str
    stock_symbol: str = ""
    daily_volume: int | None = None


class MessageAnalyzer:
    def __init__(self, config: NewsConfig):
        self.config = config

    @staticmethod
    def extract_headline(text: str) -> str:
        """Return the news headline line, skipping NuntioBot ticker header rows."""
        lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
        if not lines:
            return text.strip()

        idx = 0
        if is_nuntio_header_line(lines[0]):
            idx = 1

        while idx < len(lines):
            line = lines[idx]
            if line.startswith("http://") or line.startswith("https://"):
                idx += 1
                continue
            return line

        return lines[0]

    async def _classify_with_ai(
        self,
        headline: str,
        *,
        symbol: str = "",
        timing_key: str = "",
    ) -> tuple[str, str]:
        if not headline.strip():
            return "neutral", "AI: empty headline"
        if not self.config.openai_api_key:
            return "neutral", "AI: no API key"
        if not self.config.ai_sentiment_enabled:
            return "neutral", "AI: disabled"

        if timing_key:
            mark_step(timing_key, "ai")
        try:
            sentiment, reason = await classify_headline(
                headline,
                api_key=self.config.openai_api_key,
                model=self.config.openai_model,
                symbol=symbol,
            )
            label = f"AI: {reason}"
            if sentiment == "neutral":
                return "neutral", label
            return sentiment, label
        except (AISentimentError, Exception) as exc:
            logger.warning("AI sentiment failed: %s", exc)
            return "neutral", f"AI: error ({exc})"

    async def detect_sentiment_async(
        self,
        text: str,
        *,
        headline: str = "",
        symbol: str = "",
        timing_key: str = "",
    ) -> tuple[str, str]:
        head = headline or self.extract_headline(text)
        return await self._classify_with_ai(head, symbol=symbol, timing_key=timing_key)

    async def analyze_text_async(
        self,
        text: str,
        *,
        source: str,
        published: str,
        message_id: str,
        jump_url: str = "",
        from_url: bool = False,
        headline: str = "",
        timing_key: str = "",
    ) -> NewsItem | None:
        """Convert message text into a news item using OpenAI sentiment."""
        if not text.strip():
            return None

        head = headline or self.extract_headline(text)
        symbol = extract_stock_symbol(text)
        sentiment, ai_reason = await self.detect_sentiment_async(
            text,
            headline=head,
            symbol=symbol,
            timing_key=timing_key,
        )

        if sentiment == "neutral":
            if not self.config.alert_all_news:
                if from_url:
                    return None
                if self.config.process_all_messages:
                    sentiment = "bullish"
                    ai_reason = "AI: process all messages"
                else:
                    return None
            ai_reason = ai_reason or "AI: no catalyst"

        preview = head if head else text.strip()
        if len(preview) > 300:
            preview = preview[:297] + "..."

        return NewsItem(
            title=preview,
            link=jump_url,
            source=source,
            published=published,
            sentiment=sentiment,
            ai_reason=ai_reason,
            message_id=message_id,
            stock_symbol=symbol,
        )

    async def analyze_article_async(
        self,
        title: str,
        body: str,
        *,
        url: str,
        source: str,
        message_id: str,
        timing_key: str = "",
    ) -> NewsItem | None:
        """Analyze fetched article with OpenAI."""
        headline = title.strip() or self.extract_headline(body)
        text = f"{headline}\n{body}" if body else headline
        item = await self.analyze_text_async(
            text,
            source=source,
            published="from URL",
            message_id=message_id,
            jump_url=url,
            from_url=True,
            headline=headline,
            timing_key=timing_key or url,
        )
        if item:
            item.title = headline[:300]
            if not item.stock_symbol:
                item.stock_symbol = extract_stock_symbol(text)
        return item
