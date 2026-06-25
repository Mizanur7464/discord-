"""Benzinga news API — catalyst lookup and licensed news feed."""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

CATALYST_KEYWORDS = (
    "fda",
    "approval",
    "contract",
    "partnership",
    "acquisition",
    "merger",
    "earnings",
    "guidance",
    "upgrade",
    "downgrade",
    "offering",
    "buyback",
    "short squeeze",
    "breakthrough",
    "patent",
    "trial",
    "phase",
    "launch",
)


@dataclass
class BenzingaArticle:
    article_id: str
    title: str
    url: str = ""
    body: str = ""
    symbols: list[str] = field(default_factory=list)
    published: str = ""


def _news_items_from_payload(payload) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("results", "news", "data", "articles"):
            items = payload.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def _parse_symbols(item: dict) -> list[str]:
    symbols: list[str] = []
    for key in ("stocks", "securities", "tickers"):
        raw = item.get(key)
        if not isinstance(raw, list):
            continue
        for entry in raw:
            if isinstance(entry, dict):
                sym = entry.get("name") or entry.get("symbol") or entry.get("ticker")
                if sym:
                    symbols.append(str(sym).upper())
            elif entry:
                symbols.append(str(entry).upper())
    return symbols[:8]


def _clean_text(text: str) -> str:
    return html.unescape(str(text or "")).strip()


def parse_benzinga_article(item: dict) -> BenzingaArticle | None:
    article_id = str(item.get("id") or item.get("benzinga_id") or item.get("article_id") or "").strip()
    title = _clean_text(item.get("title") or item.get("headline") or "")
    if not title:
        return None
    if not article_id:
        article_id = str(hash(title))
    body = _clean_text(item.get("body") or item.get("teaser") or item.get("summary") or "")
    url = str(item.get("url") or item.get("link") or "").strip()
    published = str(item.get("created") or item.get("published") or item.get("updated") or "").strip()
    return BenzingaArticle(
        article_id=article_id,
        title=title,
        url=url,
        body=body,
        symbols=_parse_symbols(item),
        published=published,
    )


def _fetch_news_payload(
    api_key: str,
    *,
    symbols: str = "",
    page_size: int = 25,
    provider: str = "massive",
) -> list[dict]:
    page_size = max(1, min(page_size, 100))
    if provider == "direct":
        query = (
            f"https://api.benzinga.com/api/v2/news"
            f"?token={quote(api_key)}&pageSize={page_size}&displayOutput=full"
        )
        if symbols:
            query += f"&tickers={quote(symbols.upper())}"
    else:
        params: dict[str, str | int] = {
            "apiKey": api_key,
            "limit": page_size,
            "sort": "published.desc",
        }
        if symbols:
            params["tickers"] = symbols.upper()
        query = f"https://api.massive.com/benzinga/v2/news?{urlencode(params)}"
    with urlopen(Request(query, headers={"Accept": "application/json", "User-Agent": "discord-news-bot/1.0"}), timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    if raw.lstrip().startswith("<"):
        logger.warning("Benzinga news API returned non-JSON payload")
        return []
    payload = json.loads(raw)
    return _news_items_from_payload(payload)


def fetch_recent_news(api_key: str, *, page_size: int = 25, provider: str = "massive") -> list[BenzingaArticle]:
    if not api_key:
        return []
    try:
        items = _fetch_news_payload(api_key, page_size=page_size, provider=provider)
        articles = [parse_benzinga_article(item) for item in items]
        return [article for article in articles if article]
    except Exception as exc:
        logger.warning("Benzinga news fetch failed: %s", exc)
        return []


def _article_id_matches(item: dict, article_id: str) -> bool:
    target = str(article_id or "").strip()
    if not target:
        return False
    for key in ("id", "benzinga_id", "article_id"):
        value = item.get(key)
        if value is not None and str(value).strip() == target:
            return True
    return False


def fetch_article_by_id(
    api_key: str,
    article_id: str,
    *,
    provider: str = "massive",
) -> BenzingaArticle | None:
    if not api_key or not str(article_id or "").strip():
        return None
    article_id = str(article_id).strip()
    try:
        if provider == "massive":
            params: dict[str, str | int] = {
                "apiKey": api_key,
                "limit": 1,
                "ids": article_id,
            }
            query = f"https://api.massive.com/benzinga/v2/news?{urlencode(params)}"
            with urlopen(
                Request(query, headers={"Accept": "application/json", "User-Agent": "discord-news-bot/1.0"}),
                timeout=15,
            ) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            if not raw.lstrip().startswith("<"):
                payload = json.loads(raw)
                for item in _news_items_from_payload(payload):
                    if _article_id_matches(item, article_id):
                        return parse_benzinga_article(item)
        items = _fetch_news_payload(api_key, page_size=100, provider=provider)
        for item in items:
            if _article_id_matches(item, article_id):
                return parse_benzinga_article(item)
    except Exception as exc:
        logger.warning("Benzinga article lookup failed for %s: %s", article_id, exc)
    return None


@dataclass
class CatalystResult:
    symbol: str
    headline: str
    url: str = ""
    keywords: list[str] = field(default_factory=list)
    is_bullish_catalyst: bool = False

    @property
    def summary(self) -> str:
        if not self.keywords:
            return self.headline[:200]
        return f"{self.headline[:160]} [{', '.join(self.keywords[:4])}]"


def _extract_keywords(text: str) -> list[str]:
    lower = text.lower()
    found = [word for word in CATALYST_KEYWORDS if word in lower]
    return found[:6]


def parse_benzinga_payload(symbol: str, payload) -> CatalystResult | None:
    items = payload if isinstance(payload, list) else payload.get("news") or payload.get("data") or []
    if not items:
        return None
    item = items[0]
    title = str(item.get("title") or item.get("headline") or "").strip()
    if not title:
        return None
    url = str(item.get("url") or item.get("link") or "")
    keywords = _extract_keywords(title)
    bearish = any(token in title.lower() for token in ("downgrade", "offering", "bankruptcy", "delisting"))
    return CatalystResult(
        symbol=symbol.upper(),
        headline=title,
        url=url,
        keywords=keywords,
        is_bullish_catalyst=bool(keywords) and not bearish,
    )


def fetch_catalyst_sync(symbol: str, api_key: str, *, provider: str = "massive") -> CatalystResult | None:
    if not api_key:
        return None
    try:
        items = _fetch_news_payload(api_key, symbols=symbol.upper(), page_size=3, provider=provider)
        return parse_benzinga_payload(symbol, items)
    except Exception as exc:
        logger.warning("Benzinga catalyst lookup failed for %s: %s", symbol, exc)
        return None


def score_catalyst(catalyst: CatalystResult | None) -> tuple[int, list[str], list[str]]:
    if not catalyst:
        return 0, [], []
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []
    if catalyst.is_bullish_catalyst:
        score += 8
        reasons.append(f"Benzinga catalyst: {catalyst.summary[:120]}")
    elif catalyst.keywords:
        score += 3
        warnings.append(f"Benzinga headline with mixed keywords: {', '.join(catalyst.keywords)}")
    else:
        warnings.append("Benzinga headline without strong catalyst keywords")
    return score, reasons, warnings
