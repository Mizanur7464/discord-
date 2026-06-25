"""NuntioBot-style one-line Benzinga news posts for #news-channel."""

from __future__ import annotations

import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.news.benzinga import BenzingaArticle
from bot.news.reader_urls import reader_article_url

_ET = ZoneInfo("America/New_York")


def _decode_text(text: str) -> str:
    return html.unescape(str(text or "")).strip()


def _fmt_float_millions(shares: float | None) -> str:
    if shares is None:
        return ""
    millions = shares / 1_000_000 if shares >= 100_000 else shares
    if millions >= 100:
        return f"{millions:.0f} M"
    return f"{millions:.1f} M"


def _format_published_et(published: str) -> str:
    if not published:
        return ""
    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        return dt.astimezone(_ET).strftime("%I:%M %p ET").lstrip("0")
    except (TypeError, ValueError):
        return ""


def _headline_for_symbol(article: BenzingaArticle, symbol: str) -> str:
    title = _decode_text(article.title)
    if not symbol:
        return title
    upper = symbol.upper()
    for prefix in (
        rf"^{re.escape(upper)}\s*[-–:]\s*",
        rf"^\({re.escape(upper)}\)\s*[-–:]\s*",
        rf"^{re.escape(upper)}\s+\({re.escape(upper)}\)\s*[-–:]\s*",
        rf"^{re.escape(upper)}\s*\([^)]+\)\s*[-–:]\s*",
    ):
        stripped = re.sub(prefix, "", title, flags=re.IGNORECASE).strip()
        if stripped != title:
            return stripped
    return title


def build_benzinga_news_line(
    article: BenzingaArticle,
    *,
    symbol: str = "",
    float_shares: float | None = None,
    country_flag: str = "",
    company_name: str = "",
    link_mode: str = "article",
    reader_base_url: str = "",
    link_label: str = "Link",
) -> str:
    """Nuntio row: **01:52 PM ET** | `42.5 M` 🇺🇸 **TICKER**: headline - Link."""
    _ = company_name
    symbol = (symbol or (article.symbols[0] if article.symbols else "")).upper()
    headline = _headline_for_symbol(article, symbol)

    prefix_parts: list[str] = []
    published_et = _format_published_et(article.published)
    float_text = _fmt_float_millions(float_shares)
    if float_text:
        prefix_parts.append(f"`{float_text}`")
    if country_flag:
        prefix_parts.append(country_flag)
    if symbol:
        prefix_parts.append(f"**{symbol}**")

    if prefix_parts and headline:
        row = f"{' '.join(prefix_parts)}: {headline}".strip()
    elif prefix_parts:
        row = " ".join(prefix_parts).strip()
    else:
        row = headline

    if published_et and row:
        line = f"**{published_et}** | {row}"
    else:
        line = row

    reader_link = reader_article_url(reader_base_url, article.article_id)
    if reader_link:
        link = reader_link
    elif link_mode == "quote" and symbol:
        link = f"https://www.benzinga.com/quote/{symbol}"
    else:
        link = article.url
    if link:
        label = link_label if reader_link else "Link"
        line = f"{line} - [{label}]({link})" if line else f"[{label}]({link})"
    return line[:2000]


def build_benzinga_news_post(
    article: BenzingaArticle,
    *,
    symbol_rows: list[tuple[str, float | None, str]] | None = None,
    reader_base_url: str = "",
    link_label: str = "Link",
    **kwargs,
) -> str:
    if symbol_rows:
        link_mode = "quote" if len(symbol_rows) > 1 and not reader_base_url else "article"
        lines = [
            build_benzinga_news_line(
                article,
                symbol=symbol,
                float_shares=float_shares,
                country_flag=country_flag,
                link_mode=link_mode,
                reader_base_url=reader_base_url,
                link_label=link_label,
                **kwargs,
            )
            for symbol, float_shares, country_flag in symbol_rows
        ]
        return "\n".join(line for line in lines if line)
    return build_benzinga_news_line(
        article,
        reader_base_url=reader_base_url,
        link_label=link_label,
        **kwargs,
    )
