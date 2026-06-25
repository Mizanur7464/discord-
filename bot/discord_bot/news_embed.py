"""SPM / Nuntio #mc-style one-line Benzinga news posts for #news-channel."""

from __future__ import annotations

import re

from bot.news.benzinga import BenzingaArticle

_INLINE_TAG_PHRASES: tuple[str, ...] = (
    "1-for-25 Share Consolidation",
    "Share Consolidation",
    "Reverse Stock Split",
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
    "Ratifies Partnership",
    "Strategic Partnership",
    "Delisting",
    "Compliance Notice",
    "Announces",
    "Reports",
    "Files",
    "Launches",
    "Partnership",
    "Expanding",
    "Deploying",
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
    return " ".join(words[:6]).strip(" -–:")


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
    if symbol and title.upper().startswith(symbol.upper()):
        title = title[len(symbol) :].lstrip(" -–:")
    if company_name and title.lower().startswith(company_name.lower()):
        title = title[len(company_name) :].lstrip(" -–:")
    return _highlight_title_tags(title.strip())


def build_benzinga_news_line(
    article: BenzingaArticle,
    *,
    float_shares: float | None = None,
    company_name: str = "",
    country_flag: str = "",
) -> str:
    """SPM #mc row: **TICKER** (Company): headline `tags` - Link."""
    _ = float_shares, country_flag
    symbol = article.symbols[0] if article.symbols else ""
    company = company_name or _company_from_title(article.title, symbol)
    headline = _headline_text(article, symbol, company)

    if symbol and company:
        line = f"**{symbol}** ({company}): {headline}".strip()
    elif symbol:
        line = f"**{symbol}**: {headline}".strip() if headline else f"**{symbol}**"
    elif company:
        line = f"({company}): {headline}".strip()
    else:
        line = headline

    line = line.rstrip(": ").strip()
    if article.url:
        line = f"{line} - [Link]({article.url})" if line else f"[Link]({article.url})"
    return line[:2000]


def build_benzinga_news_post(article: BenzingaArticle, **kwargs) -> str:
    return build_benzinga_news_line(article, **kwargs)
