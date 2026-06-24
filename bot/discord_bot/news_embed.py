"""Compact Benzinga news posts for #news-channel (SPM/NB style)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from bot.news.benzinga import BenzingaArticle

_ET = ZoneInfo("America/New_York")


def _parse_published(published: str) -> datetime | None:
    if not published:
        return None
    text = published.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=_ET)
        except ValueError:
            continue
    return None


def _article_time(article: BenzingaArticle) -> tuple[str, datetime]:
    parsed = _parse_published(article.published)
    if parsed is None:
        parsed = datetime.now(_ET)
    elif parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_ET)
    else:
        parsed = parsed.astimezone(_ET)
    return parsed.strftime("%I:%M:%S %p ET"), parsed


def _headline(article: BenzingaArticle, symbol: str) -> str:
    title = article.title.strip()
    if symbol and not title.upper().startswith(symbol.upper()):
        return f"**{symbol}** — {title[:220]}"
    return title[:240]


def build_news_link_view(url: str) -> discord.ui.View | None:
    if not url:
        return None
    view = discord.ui.View()
    view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label="Read", url=url))
    return view


def build_benzinga_news_post(article: BenzingaArticle) -> tuple[discord.Embed, discord.ui.View | None]:
    symbol = article.symbols[0] if article.symbols else ""
    time_label, when = _article_time(article)
    embed = discord.Embed(
        description=f"**{time_label}**\n{_headline(article, symbol)}",
        color=discord.Color.from_rgb(88, 101, 242),
    )
    embed.timestamp = when
    embed.set_footer(text="Benzinga")
    return embed, build_news_link_view(article.url)
