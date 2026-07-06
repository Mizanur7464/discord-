"""NuntioBot-style one-line Benzinga news posts for #news-channel."""

from __future__ import annotations

import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.news.ai_output import NewsAIOutput
from bot.news.benzinga import BenzingaArticle
from bot.news.impact_routing import ACTIONABILITY_LABELS, IMPACT_LEVEL_LABELS
from bot.news.news_intelligence import NewsImpact, SymbolNewsContext
from bot.news.reader_urls import reader_article_url
from bot.news.source_traceability import SourceTraceability

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


def _format_published_seconds_et(published: str) -> str:
    if not published:
        return ""
    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        return dt.astimezone(_ET).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return ""


def _fmt_mcap_display(value: float | None) -> str:
    if value is None or value <= 0:
        return ""
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.0f}M"
    return f"${value:,.0f}"


def _fmt_float_display(shares: float | None) -> str:
    if not shares or shares <= 0:
        return ""
    millions = shares / 1_000_000
    if millions >= 100:
        return f"{millions:.0f}M"
    return f"{millions:.1f}M"


def _fmt_price_display(price: float | None) -> str:
    if price is None or price <= 0:
        return ""
    if price >= 1:
        return f"${price:.2f}"
    return f"${price:.3f}"


def _fmt_turnover_display(value: float | None) -> str:
    if value is None or value <= 0:
        return ""
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}k"
    return f"${value:.0f}"


def _fmt_pct_display(value: float | None) -> str:
    if value is None:
        return ""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:g}%"


def _fmt_sentiment_display(sentiment: str) -> str:
    labels = {
        "bullish": "Bullish",
        "bearish": "Bearish",
        "ignored": "Bearish",
        "neutral": "Neutral",
    }
    return labels.get((sentiment or "").lower(), sentiment.title() if sentiment else "")


def _fmt_peak_rvol_display(peak_rvol: float | None, peak_at: str) -> str:
    if peak_rvol is None or peak_rvol <= 0:
        return ""
    text = f"{peak_rvol:,.0f}x" if peak_rvol >= 100 else f"{peak_rvol:g}x"
    if peak_at and peak_at not in {"—", ""}:
        return f"{text} @{peak_at}"
    return text


def build_timeline_news_block(
    article: BenzingaArticle,
    *,
    symbol: str = "",
    impact: NewsImpact,
    context: SymbolNewsContext | None = None,
    reader_base_url: str = "",
    sentiment: str = "",
    dilution_risk: bool | None = None,
    ai_output=None,
    source_trace: SourceTraceability | None = None,
    related_symbols: list[str] | None = None,
    news_scope: str = "company",
) -> str:
    """SDS §2.1 timeline feed — HH:MM:SS — TICKER Headline, one metadata field per line."""
    from bot.news.news_scope import is_multi_ticker_post

    multi = is_multi_ticker_post(news_scope) and related_symbols and len(related_symbols) > 1
    symbol = (symbol or "").upper()
    if not symbol and not multi:
        symbol = (article.symbols[0] if article.symbols else "").upper()
    headline = _headline_for_symbol(article, symbol if not multi else "")
    time_et = _format_published_seconds_et(article.published)
    if multi:
        title_line = f"{time_et} — {headline}".strip(" —") if time_et else headline
    else:
        title_line = f"{time_et} — {symbol} {headline}".strip(" —") if time_et else f"{symbol} {headline}".strip()

    lines: list[str] = [title_line[:500]]
    if multi:
        lines.append(f"Related: {', '.join(related_symbols[:16])}")
    ctx = context or SymbolNewsContext(symbol=symbol)
    if not multi:
        flag = ctx.country_flag or "🇺🇸"
        exchange = (ctx.exchange or "").strip()
        if exchange:
            lines.append(f"{flag} {exchange}")
        elif flag:
            lines.append(flag)

        industry = (ctx.sector or "").strip()
        if industry:
            lines.append(f"Ind: {industry[:48]}")
        theme = (ctx.theme or "").strip()
        if theme and theme != industry:
            lines.append(f"Theme: {theme[:48]}")

    mcap = _fmt_mcap_display(ctx.market_cap_usd)
    if mcap and not multi:
        lines.append(f"MC: {mcap.lstrip('$')}")
    flt = _fmt_float_display(ctx.float_shares)
    if flt and not multi:
        lines.append(f"F: {flt}")

    impact_label = IMPACT_LEVEL_LABELS.get(impact.level, impact.level.title())
    lines.append(f"Impact: {impact.emoji} {impact_label}")

    sent = _fmt_sentiment_display(sentiment or ctx.sentiment)
    if sent:
        lines.append(f"Sent: {sent}")

    if impact.category and impact.category not in {"", "No Clear Catalyst", "Ordinary News"}:
        lines.append(f"Cat: {impact.category[:64]}")
    elif impact.catalyst_type:
        lines.append(f"Cat: {impact.catalyst_type[:64]}")

    if impact.catalyst_tags:
        lines.append(f"Tags: {', '.join(impact.catalyst_tags[:6])}")

    conf_val = None
    if source_trace:
        conf_val = source_trace.confidence
    elif getattr(impact, "confidence", None):
        conf_val = impact.confidence
    if conf_val is not None:
        lines.append(f"Conf: {conf_val:.0f}%")

    if getattr(impact, "urgency", ""):
        lines.append(f"Urgency: {impact.urgency}")

    if getattr(impact, "repeated_pr", False):
        lines.append("Repeated PR: Yes")

    px = _fmt_price_display(ctx.price)
    if px and not multi:
        lines.append(f"Px: {px.lstrip('$')}")

    session_to = _fmt_turnover_display(
        getattr(ctx, "session_turnover_usd", None) or ctx.premarket_turnover_usd
    )
    if session_to and not multi:
        lines.append(f"Session TO: {session_to.lstrip('$')}")

    if not multi and ctx.rvol is not None and ctx.rvol > 0:
        rvol_text = f"{ctx.rvol:,.0f}x" if ctx.rvol >= 100 else f"{ctx.rvol:g}x"
        lines.append(f"RVOL@News: {rvol_text}")

    peak = _fmt_peak_rvol_display(ctx.peak_rvol, ctx.peak_rvol_at)
    if peak and not multi:
        lines.append(f"Peak RVOL: {peak}")

    day_chg = _fmt_pct_display(ctx.session_change_pct)
    if day_chg and not multi:
        lines.append(f"1D: {day_chg}")

    if not multi:
        if ctx.is_runner:
            lines.append("Prev Run: Yes")
        elif ctx.symbol:
            lines.append("Prev Run: No")

    dilution = dilution_risk if dilution_risk is not None else ctx.dilution_risk
    if dilution is not None:
        lines.append(f"Dilution: {'Yes' if dilution else 'No'}")

    if ai_output is not None:
        if ai_output.summary:
            lines.append(f"Summary: {ai_output.summary[:220]}")
        if ai_output.liquidity_risk:
            lines.append(f"Liq Risk: {ai_output.liquidity_risk}")
    keyword = ""
    if ai_output is not None and ai_output.keyword and ai_output.keyword != "—":
        keyword = ai_output.keyword
    elif getattr(impact, "canonical_keyword", "") and impact.canonical_keyword != "—":
        keyword = impact.canonical_keyword
    if keyword:
        lines.append(f"Keyword: {keyword[:64]}")
    if ai_output is not None:
        if ai_output.crowd_attention_score:
            lines.append(f"Crowd: {ai_output.crowd_attention_score}/100")
        if ai_output.smart_alert:
            lines.append("Smart Alert: Yes")
        if ai_output.timeline_note:
            lines.append(f"Timeline: {ai_output.timeline_note[:300]}")
        action = ai_output.suggested_action or ACTIONABILITY_LABELS.get(impact.level, "")
    else:
        action = ACTIONABILITY_LABELS.get(impact.level, "")
    if action:
        lines.append(f"Action: {action}")

    if source_trace is not None:
        lines.append(f"Source: {source_trace.source_name} ({source_trace.quality_display})")
        if source_trace.original_url:
            lines.append(f"Original URL: {source_trace.original_url[:200]}")
        if source_trace.published_et:
            lines.append(f"Published: {source_trace.published_et}")
        if source_trace.first_detected_et:
            lines.append(f"First Detected: {source_trace.first_detected_et}")

    reader_link = (source_trace.mirror_url if source_trace else "") or reader_article_url(
        reader_base_url, article.article_id
    )
    link = reader_link or article.url
    if link:
        label = "Mirror" if source_trace and source_trace.mirror_url else "Link"
        lines.append(f"[{label}]({link})")

    return "\n".join(lines)[:2000]


def build_timeline_news_blocks(
    article: BenzingaArticle,
    *,
    symbol_rows: list[tuple[str, float | None, str]] | None = None,
    reader_base_url: str = "",
    contexts: dict[str, SymbolNewsContext] | None = None,
    impact: NewsImpact,
    sentiment: str = "",
    dilution_risk: bool | None = None,
    ai_outputs: dict[str, object] | None = None,
    source_trace=None,
    news_scope: str = "company",
    **kwargs,
) -> list[str]:
    """One Discord message per ticker — or single post for macro/sector scope."""
    from bot.news.news_scope import is_multi_ticker_post

    contexts = contexts or {}
    if symbol_rows:
        tickers = [sym.upper() for sym, _, _ in symbol_rows if sym]
        if is_multi_ticker_post(news_scope) and len(tickers) > 1:
            primary = tickers[0]
            ctx = contexts.get(primary) or SymbolNewsContext(symbol=primary)
            first_ai = (ai_outputs or {}).get(primary) or next(iter((ai_outputs or {}).values()), None)
            block = build_timeline_news_block(
                article,
                symbol="",
                impact=impact,
                context=ctx,
                reader_base_url=reader_base_url,
                sentiment=sentiment,
                dilution_risk=dilution_risk,
                ai_output=first_ai,
                source_trace=source_trace,
                related_symbols=tickers,
                news_scope=news_scope,
            )
            return [block] if block else []
        blocks: list[str] = []
        for symbol, _float_shares, _country_flag in symbol_rows:
            sym = symbol.upper()
            ctx = contexts.get(sym) or SymbolNewsContext(symbol=sym, country_flag=_country_flag)
            block = build_timeline_news_block(
                article,
                symbol=sym,
                impact=impact,
                context=ctx,
                reader_base_url=reader_base_url,
                sentiment=sentiment,
                dilution_risk=dilution_risk,
                ai_output=(ai_outputs or {}).get(sym),
                source_trace=source_trace,
            )
            if block:
                blocks.append(block)
        return blocks
    first_ai = next(iter(ai_outputs.values()), None) if ai_outputs else None
    block = build_timeline_news_block(
        article,
        impact=impact,
        reader_base_url=reader_base_url,
        sentiment=sentiment,
        dilution_risk=dilution_risk,
        ai_output=first_ai,
        source_trace=source_trace,
    )
    return [block] if block else []


def build_benzinga_news_line(
    article: BenzingaArticle,
    *,
    symbol: str = "",
    float_shares: float | None = None,
    country_flag: str = "",
    company_name: str = "",
    link_mode: str = "article",
    reader_base_url: str = "",
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

    reader_link = reader_article_url(reader_base_url, article.article_id)
    if reader_link:
        link = reader_link
    elif link_mode == "quote" and symbol:
        link = f"https://www.benzinga.com/quote/{symbol}"
    else:
        link = article.url
    if link:
        row = f"{row} - [Link]({link})" if row else f"[Link]({link})"

    if published_et and row:
        return f"**{published_et}**\n{row}"[:2000]
    return row[:2000]


_SENTIMENT_EMOJI = {
    "bullish": "🟢",
    "neutral": "🟡",
    "ignored": "🔴",
    "bearish": "🔴",
}


def build_ai_news_line(
    *,
    sentiment: str = "",
    reason: str = "",
    category: str = "",
) -> str:
    """Traffic-light AI summary line, e.g. `🟢 AI: Earnings — strong beat`."""
    emoji = _SENTIMENT_EMOJI.get((sentiment or "").lower(), "🟡")
    reason = _decode_text(reason)
    category = _decode_text(category)
    # Drop a redundant leading "AI:" / "AI -" that the model sometimes adds.
    reason = re.sub(r"^\s*ai\s*[:\-–]\s*", "", reason, flags=re.IGNORECASE).strip()
    generic = {"", "no clear catalyst", "ai", "none"}
    if category.lower() not in generic and reason:
        summary = f"{category} — {reason}"
    elif category.lower() not in generic:
        summary = category
    else:
        summary = reason or "no clear catalyst"
    return f"{emoji} AI: {summary}"[:300]


def build_benzinga_news_post(
    article: BenzingaArticle,
    *,
    symbol_rows: list[tuple[str, float | None, str]] | None = None,
    reader_base_url: str = "",
    **kwargs,
) -> str:
    return "\n\n".join(build_benzinga_news_blocks(article, symbol_rows=symbol_rows, reader_base_url=reader_base_url, **kwargs))


def build_benzinga_news_blocks(
    article: BenzingaArticle,
    *,
    symbol_rows: list[tuple[str, float | None, str]] | None = None,
    reader_base_url: str = "",
    context_lines: dict[str, str] | None = None,
    priority_line: str = "",
    **kwargs,
) -> list[str]:
    """One Discord message per block — NB spacing between multi-ticker rows."""
    if symbol_rows:
        link_mode = "quote" if len(symbol_rows) > 1 and not reader_base_url else "article"
        blocks: list[str] = []
        for symbol, float_shares, country_flag in symbol_rows:
            line = build_benzinga_news_line(
                article,
                symbol=symbol,
                float_shares=float_shares,
                country_flag=country_flag,
                link_mode=link_mode,
                reader_base_url=reader_base_url,
                **kwargs,
            )
            if not line:
                continue
            parts = [line]
            ctx = (context_lines or {}).get(symbol.upper(), "")
            if ctx:
                parts.append(ctx)
            if priority_line:
                parts.append(priority_line)
            blocks.append("\n".join(parts))
        return blocks
    line = build_benzinga_news_line(article, reader_base_url=reader_base_url, **kwargs)
    if not line:
        return []
    parts = [line]
    if priority_line:
        parts.append(priority_line)
    return ["\n".join(parts)]
