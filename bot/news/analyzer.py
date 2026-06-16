"""Analyze Discord messages for trading signals."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from bot.news.ai_sentiment import AISentimentError, classify_headline
from bot.news.symbols import NUNTIO_FIRST_LINE, extract_stock_symbol
from bot.utils.config import NewsConfig
from bot.utils.timing import mark_step

logger = logging.getLogger(__name__)

DEFAULT_NEGATION_WORDS = [
    "not",
    "no ",
    "n't",
    "never",
    "without",
    "despite",
    "fail",
    "failed",
    "denies",
    "denied",
    "reject",
    "rejected",
    "cancel",
    "cancelled",
    "canceled",
    "withdraw",
    "despite",
    "against",
    "unlikely",
    "misses",
    "missed",
]

# Skip boilerplate intro when scanning article body for ignore keywords.
INTRO_SKIP_PATTERNS = (
    re.compile(r"^about (?:the )?company\b", re.IGNORECASE),
    re.compile(r"^company overview\b", re.IGNORECASE),
    re.compile(r"^corporate profile\b", re.IGNORECASE),
    re.compile(r"^business description\b", re.IGNORECASE),
)


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: str
    sentiment: str  # "bullish", "ignored", or "neutral"
    matched_keyword: str
    message_id: str
    stock_symbol: str = ""


class MessageAnalyzer:
    def __init__(self, config: NewsConfig):
        self.config = config
        self._negation_words = config.negation_words or DEFAULT_NEGATION_WORDS

    @staticmethod
    def _keyword_pattern(keyword: str) -> re.Pattern[str]:
        """Match whole words/phrases only (avoids 'miss' in 'Commission')."""
        cleaned = keyword.strip().lower()
        if not cleaned:
            return re.compile(r"(?!x)x")
        return re.compile(r"\b" + re.escape(cleaned) + r"\b", re.IGNORECASE)

    def _contains_keyword(self, text: str, keyword: str) -> bool:
        return bool(self._keyword_pattern(keyword).search(text))

    def _keyword_match(self, text: str, keyword: str) -> re.Match[str] | None:
        return self._keyword_pattern(keyword).search(text)

    def _negation_in_window(self, window: str) -> bool:
        for neg in self._negation_words:
            neg = neg.strip().lower()
            if not neg:
                continue
            if neg == "n't":
                if "n't" in window:
                    return True
                continue
            if self._contains_keyword(window, neg):
                return True
        return False

    def _is_negated(self, text: str, keyword: str) -> bool:
        if not self.config.check_negation:
            return False

        match = self._keyword_match(text, keyword)
        if not match:
            return False

        start = max(0, match.start() - 50)
        end = min(len(text), match.end() + 30)
        window = text[start:end]
        return self._negation_in_window(window)

    @staticmethod
    def extract_headline(text: str) -> str:
        """Return the news headline line, skipping NuntioBot ticker header rows."""
        lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
        if not lines:
            return text.strip()

        idx = 0
        if NUNTIO_FIRST_LINE.match(lines[0]):
            idx = 1

        while idx < len(lines):
            line = lines[idx]
            if line.startswith("http://") or line.startswith("https://"):
                idx += 1
                continue
            return line

        return lines[0]

    @staticmethod
    def _strip_intro_sections(body: str) -> str:
        """Remove company boilerplate blocks from article body."""
        if not body.strip():
            return ""

        kept: list[str] = []
        skip_block = False

        for raw_line in body.split("\n"):
            line = raw_line.strip()
            if not line:
                if skip_block:
                    skip_block = False
                continue

            if any(pattern.search(line) for pattern in INTRO_SKIP_PATTERNS):
                skip_block = True
                continue

            if skip_block:
                continue

            kept.append(line)

        return "\n".join(kept)

    def _match_ignore(self, text: str) -> tuple[str, str]:
        for word in self.config.keywords.get("ignore", []):
            if self._contains_keyword(text, word):
                return "ignored", word
        return "", ""

    def _match_bullish(self, text: str) -> tuple[str, str]:
        for word in self.config.keywords.get("bullish", []):
            if self._contains_keyword(text, word):
                if self._is_negated(text, word):
                    return "ignored", f"{word} (opposite context)"
                return "bullish", word
        return "", ""

    def detect_sentiment(self, text: str, *, headline: str = "") -> tuple[str, str]:
        """Detect buy, ignore, or neutral. Bullish uses headline; ignore uses full text."""
        head = headline or self.extract_headline(text)
        body_without_intro = self._strip_intro_sections(text)
        ignore_text = body_without_intro if body_without_intro else text

        sentiment, keyword = self._match_ignore(ignore_text)
        if sentiment:
            return sentiment, keyword

        sentiment, keyword = self._match_bullish(head)
        if sentiment:
            return sentiment, keyword

        return "neutral", ""

    async def detect_sentiment_async(
        self,
        text: str,
        *,
        headline: str = "",
        symbol: str = "",
        timing_key: str = "",
    ) -> tuple[str, str]:
        """Keyword rules first, then OpenAI when still neutral."""
        sentiment, keyword = self.detect_sentiment(text, headline=headline)
        if sentiment != "neutral":
            return sentiment, keyword

        if not self.config.ai_sentiment_enabled or not self.config.openai_api_key:
            return "neutral", keyword

        if self.config.ai_on_neutral_only is False:
            pass  # future: always run AI

        head = headline or self.extract_headline(text)
        if not head.strip():
            return "neutral", keyword

        if timing_key:
            mark_step(timing_key, "ai")
        try:
            ai_sentiment, reason = await classify_headline(
                head,
                api_key=self.config.openai_api_key,
                model=self.config.openai_model,
                symbol=symbol,
            )
            if ai_sentiment == "neutral":
                return "neutral", keyword or "none"
            return ai_sentiment, f"ai: {reason}"
        except (AISentimentError, Exception) as exc:
            logger.warning("AI sentiment failed: %s", exc)
            return "neutral", keyword or "none"

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
        """Convert message text into a news item (with optional AI fallback)."""
        if not text.strip():
            return None

        head = headline or self.extract_headline(text)
        symbol = extract_stock_symbol(text)
        sentiment, keyword = await self.detect_sentiment_async(
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
                    keyword = "new message"
                else:
                    return None
            keyword = keyword or "none"

        preview = head if head else text.strip()
        if len(preview) > 300:
            preview = preview[:297] + "..."

        return NewsItem(
            title=preview,
            link=jump_url,
            source=source,
            published=published,
            sentiment=sentiment,
            matched_keyword=keyword,
            message_id=message_id,
            stock_symbol=symbol,
        )

    def analyze_text(
        self,
        text: str,
        *,
        source: str,
        published: str,
        message_id: str,
        jump_url: str = "",
        from_url: bool = False,
        headline: str = "",
    ) -> NewsItem | None:
        """Convert message text into a news item if it matches rules."""
        if not text.strip():
            return None

        head = headline or self.extract_headline(text)
        sentiment, keyword = self.detect_sentiment(text, headline=head)

        if sentiment == "neutral":
            if not self.config.alert_all_news:
                if from_url:
                    return None
                if self.config.process_all_messages:
                    sentiment = "bullish"
                    keyword = "new message"
                else:
                    return None
            keyword = keyword or "none"

        preview = head if head else text.strip()
        if len(preview) > 300:
            preview = preview[:297] + "..."

        return NewsItem(
            title=preview,
            link=jump_url,
            source=source,
            published=published,
            sentiment=sentiment,
            matched_keyword=keyword,
            message_id=message_id,
            stock_symbol=extract_stock_symbol(text),
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
        """Analyze fetched article with AI fallback on neutral."""
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

    def analyze_article(
        self,
        title: str,
        body: str,
        *,
        url: str,
        source: str,
        message_id: str,
    ) -> NewsItem | None:
        """Analyze fetched article: headline for bullish, body (no intro) for ignore."""
        headline = title.strip() or self.extract_headline(body)
        text = f"{headline}\n{body}" if body else headline
        item = self.analyze_text(
            text,
            source=source,
            published="from URL",
            message_id=message_id,
            jump_url=url,
            from_url=True,
            headline=headline,
        )
        if item:
            item.title = headline[:300]
            if not item.stock_symbol:
                item.stock_symbol = extract_stock_symbol(text)
        return item
