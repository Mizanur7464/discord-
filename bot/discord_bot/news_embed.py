"""NuntioBot-style one-line Benzinga news posts for #news-channel."""

from __future__ import annotations

import re

from bot.news.benzinga import BenzingaArticle


def _fmt_float_millions(shares: float | None) -> str:
    if shares is None:
        return ""
    millions = shares / 1_000_000 if shares >= 100_000 else shares
    if millions >= 100:
        return f"{millions:.0f} M"
    return f"{millions:.1f} M"


def _headline_for_symbol(article: BenzingaArticle, symbol: str) -> str:
    title = article.title.strip()
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
) -> str:
    """Nuntio row: `42.5 M` 🇺🇸 `TICKER`: headline - Link."""
    _ = company_name
    symbol = (symbol or (article.symbols[0] if article.symbols else "")).upper()
    headline = _headline_for_symbol(article, symbol)

    prefix_parts: list[str] = []
    float_text = _fmt_float_millions(float_shares)
    if float_text:
        prefix_parts.append(f"`{float_text}`")
    if country_flag:
        prefix_parts.append(country_flag)
    if symbol:
        prefix_parts.append(f"`{symbol}`")

    if prefix_parts and headline:
        line = f"{' '.join(prefix_parts)}: {headline}".strip()
    elif prefix_parts:
        line = " ".join(prefix_parts).strip()
    else:
        line = headline

    if article.url:
        line = f"{line} - [Link]({article.url})" if line else f"[Link]({article.url})"
    return line[:2000]


def build_benzinga_news_post(
    article: BenzingaArticle,
    *,
    symbol_rows: list[tuple[str, float | None, str]] | None = None,
    **kwargs,
) -> str:
    if symbol_rows:
        lines = [
            build_benzinga_news_line(
                article,
                symbol=symbol,
                float_shares=float_shares,
                country_flag=country_flag,
                **kwargs,
            )
            for symbol, float_shares, country_flag in symbol_rows
        ]
        return "\n".join(line for line in lines if line)
    return build_benzinga_news_line(article, **kwargs)
