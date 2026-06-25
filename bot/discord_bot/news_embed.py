"""NuntioBot-style one-line Benzinga news posts for #news-channel."""

from __future__ import annotations

import re

from bot.news.benzinga import BenzingaArticle

_INLINE_TAG_PHRASES: tuple[str, ...] = (
    "Provides Update",
    "Reports Financial Results",
    "Reports Earnings",
    "Public Offering",
    "Reverse Split",
    "FDA Approval",
    "Receives FDA",
    "Guidance Update",
    "Provides Guidance",
    "Merger Agreement",
    "Acquisition Agreement",
    "Delisting",
    "Compliance Notice",
    "Announces",
    "Reports",
    "Files",
    "Launches",
    "Partnership",
    "Contract",
    "Upgrade",
    "Downgrade",
    "Earnings",
    "Guidance",
    "Offering",
    "Approval",
    "Merger",
    "Acquisition",
)


def _format_float_badge(float_shares: float | None) -> str:
    if not float_shares:
        return ""
    millions = float_shares / 1_000_000
    if millions >= 100:
        text = f"{millions:.0f} M"
    else:
        text = f"{millions:.1f} M"
    return f"`{text}`"


def _company_from_title(title: str, symbol: str) -> str:
    if not symbol:
        return ""
    pattern = re.compile(rf"^{re.escape(symbol)}\s*[-–:]\s*(.+)$", re.IGNORECASE)
    match = pattern.match(title.strip())
    if not match:
        return ""
    rest = match.group(1).strip()
    for phrase in _INLINE_TAG_PHRASES:
        idx = rest.lower().find(phrase.lower())
        if idx > 0:
            return rest[:idx].strip(" -–:")
        if idx == 0:
            break
    words = rest.split()
    return " ".join(words[:4]).strip(" -–:")


def _highlight_title_tags(text: str) -> str:
    updated = text
    for phrase in sorted(_INLINE_TAG_PHRASES, key=len, reverse=True):
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)

        def repl(match: re.Match[str]) -> str:
            return f"`{match.group(0)}`"

        updated = pattern.sub(repl, updated, count=1)
    return updated


def _headline_text(article: BenzingaArticle, symbol: str, company_name: str) -> str:
    title = article.title.strip()
    if symbol:
        if title.upper().startswith(symbol.upper()):
            title = title[len(symbol) :].lstrip(" -–:")
        if company_name and title.lower().startswith(company_name.lower()):
            title = title[len(company_name) :].lstrip(" -–:")
    return _highlight_title_tags(title.strip())


def build_benzinga_news_line(
    article: BenzingaArticle,
    *,
    float_shares: float | None = None,
    company_name: str = "",
    country_flag: str = "🇺🇸",
) -> str:
    """Single-line Nuntio-style post: float badge, flag, ticker, tags, Link."""
    symbol = article.symbols[0] if article.symbols else ""
    company = company_name or _company_from_title(article.title, symbol)
    parts: list[str] = []

    float_badge = _format_float_badge(float_shares)
    if float_badge:
        parts.append(float_badge)
    if country_flag:
        parts.append(country_flag)

    if symbol and company:
        parts.append(f"**{symbol}**: {company}")
    elif symbol:
        parts.append(f"**{symbol}**")
    elif company:
        parts.append(company)

    headline = _headline_text(article, symbol, company)
    if headline:
        parts.append(headline)

    line = " ".join(part for part in parts if part).strip()
    if article.url:
        line = f"{line} - [Link]({article.url})" if line else f"[Link]({article.url})"
    return line[:2000]


def build_benzinga_news_post(article: BenzingaArticle, **kwargs) -> str:
    """Backward-compatible alias."""
    return build_benzinga_news_line(article, **kwargs)
