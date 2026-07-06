"""News impact, routing, and trader-context helpers (buyer noise-reduction phases)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bot.trading.catalyst_labels import classify_news_text

IMPACT_HIGH = "high"
IMPACT_MEDIUM = "medium"
IMPACT_LOW = "low"
IMPACT_GRAY = "gray"

IMPACT_EMOJI = {
    IMPACT_HIGH: "🔴",
    IMPACT_MEDIUM: "🟠",
    IMPACT_LOW: "🟡",
    IMPACT_GRAY: "⚪",
}

HIGH_KEYWORDS = (
    "fda approval",
    "fda accepts",
    "fda clearance",
    "fast track",
    "breakthrough therapy",
    "orphan drug",
    "phase 1",
    "phase 2",
    "phase 3",
    "trial success",
    "trial met",
    "contract awarded",
    "government contract",
    "defense contract",
    "acquisition",
    "merger",
    "buyout",
    "takeover",
    "public offering",
    "registered direct",
    "private placement",
    "pipe",
    "atm offering",
    "shelf registration",
    "dilution",
    "reverse split",
    "delisting",
    "non-compliance",
    "bankruptcy",
    "going concern",
    "clinical hold",
    "fda rejection",
    "trading halt",
    "halted",
    "uplisting",
    "nasdaq compliance regained",
)

MEDIUM_KEYWORDS = (
    "partnership",
    "collaboration",
    "distribution agreement",
    "supply agreement",
    "commercial launch",
    "product launch",
    "pilot program",
    "strategic alliance",
    "licensing",
    "earnings",
    "guidance",
    "revenue growth",
    "investor presentation",
    "conference participation",
)

LOW_KEYWORDS = (
    "announces",
    "provides update",
    "corporate update",
    "business update",
    "shareholder letter",
    "appointment",
    "board change",
    "management change",
    "webinar",
    "conference reminder",
    "award",
    "esg",
    "sustainability",
)

GRAY_KEYWORDS = (
    "reminder",
    "reiterates",
    "comments on",
    "market commentary",
    "industry outlook",
    "routine filing",
    "schedule",
    "participation notice",
    "podcast",
    "blog post",
    "non-material",
    "minor operational",
)

OPTIONS_KEYWORDS = (
    "options flow",
    "call option",
    "put option",
    "open interest",
    "unusual options",
    "options activity",
    "strike price",
    "covered call",
    "put spread",
    "call spread",
)

HIGH_CATEGORIES = frozenset(
    {
        "FDA / Biotech Catalyst",
        "Public Offering",
        "Reverse Split",
        "Major Catalyst",
    }
)


@dataclass
class NewsImpact:
    level: str
    emoji: str
    category: str
    post_main: bool
    post_cap: bool
    skip_entirely: bool
    reason: str
    catalyst_type: str = ""
    catalyst_tags: list[str] | None = None
    dilution_risk: bool = False
    matched_keywords: list[str] | None = None
    confidence: float | None = None
    urgency: str = ""
    repeated_pr: bool = False
    negated: bool = False
    secondary_events: list[str] | None = None
    canonical_keyword: str = ""


DILUTION_KEYWORDS = (
    "private placement",
    "pipe",
    "public offering",
    "direct offering",
    "registered direct",
    "atm offering",
    "shelf registration",
    "s-1 filing",
    "s-3 filing",
    "securities purchase agreement",
    "warrant",
    "convertible note",
    "convertible debt",
    "equity purchase agreement",
    "sepa",
    "standby equity purchase",
    "lincoln park",
    "yorkville",
    "committed equity facility",
    "dilution",
)


@dataclass
class SymbolNewsContext:
    symbol: str
    float_shares: float | None = None
    market_cap_usd: float | None = None
    country_flag: str = "🇺🇸"
    sector: str = ""
    exchange: str = ""
    theme: str = ""
    rvol: float | None = None
    peak_rvol: float | None = None
    peak_rvol_at: str = ""
    price: float | None = None
    session_change_pct: float | None = None
    session_turnover_usd: float | None = None
    premarket_turnover_usd: float | None = None
    is_runner: bool = False
    runner_stars: int = 0
    sentiment: str = ""
    dilution_risk: bool | None = None


def is_options_news(*, title: str = "", body: str = "") -> bool:
    text = f"{title}\n{body}".lower()
    return any(keyword in text for keyword in OPTIONS_KEYWORDS)


def is_dilution_news(text: str) -> bool:
    """SDS §3.2 financing/dilution keywords."""
    from bot.news.keyword_scanner import scan_keywords

    return scan_keywords(text).dilution_risk or any(
        keyword in text.lower() for keyword in DILUTION_KEYWORDS
    )


def classify_impact(
    text: str,
    *,
    category: str = "",
    sentiment: str = "neutral",
    symbol: str = "",
    article_id: str = "",
    source: str = "benzinga",
) -> NewsImpact:
    """Classify via SDS §3 keyword scanner + §4 rule engine."""
    from bot.news.rule_engine import apply_rule_engine

    rules = apply_rule_engine(text, symbol=symbol, article_id=article_id, source=source)
    scan = rules.keyword
    category = category or rules.catalyst_type or classify_news_text(text, sentiment=sentiment)
    if rules.catalyst_type and rules.catalyst_type not in category:
        category = rules.catalyst_type

    level = rules.impact_level
    emoji = rules.impact_emoji
    reason = rules.reason

    if level not in {IMPACT_HIGH, IMPACT_MEDIUM, IMPACT_LOW, IMPACT_GRAY}:
        level = IMPACT_LOW
        emoji = IMPACT_EMOJI[level]

    if level == IMPACT_MEDIUM and category in {"Partnership", "Contract Announcement", "Earnings"}:
        reason = category.lower()
    elif level == IMPACT_LOW and category == "Ordinary News":
        reason = "watch only"
    elif level == IMPACT_GRAY and category == "No Clear Catalyst":
        reason = rules.reason or "no clear catalyst"
    elif sentiment == "bullish" and level == IMPACT_LOW and not rules.negated:
        level = IMPACT_MEDIUM
        emoji = IMPACT_EMOJI[IMPACT_MEDIUM]
        reason = "bullish signal"

    skip_entirely = level == IMPACT_GRAY
    post_main = level in {IMPACT_HIGH, IMPACT_MEDIUM}
    post_cap = level in {IMPACT_HIGH, IMPACT_MEDIUM, IMPACT_LOW}
    secondary = [f"{e.catalyst_type} ({e.role})" for e in rules.secondary_events[:3]]
    from bot.news.canonical_keyword import resolve_canonical_keyword

    canonical = resolve_canonical_keyword(
        text,
        matched=rules.matched_keywords or scan.matched_keywords,
        catalyst_type=rules.catalyst_type or scan.catalyst_type,
    )

    return NewsImpact(
        level=level,
        emoji=emoji,
        category=category,
        post_main=post_main,
        post_cap=post_cap,
        skip_entirely=skip_entirely,
        reason=reason,
        catalyst_type=rules.catalyst_type or scan.catalyst_type,
        catalyst_tags=rules.catalyst_tags or scan.catalyst_tags,
        dilution_risk=rules.dilution_risk,
        matched_keywords=rules.matched_keywords or scan.matched_keywords,
        confidence=rules.confidence,
        urgency=rules.urgency,
        repeated_pr=rules.repeated_pr,
        negated=rules.negated,
        secondary_events=secondary or None,
        canonical_keyword=canonical,
    )


def is_out_of_news_universe(
    smallest_market_cap_usd: float | None,
    max_universe_cap_usd: float,
) -> bool:
    """Coverage scope boundary — not a news classification rule (SDS §1.1)."""
    return (
        smallest_market_cap_usd is not None
        and max_universe_cap_usd > 0
        and smallest_market_cap_usd >= max_universe_cap_usd
    )


def resolve_news_routing(
    *,
    title: str,
    body: str,
    symbols: list[str],
    smallest_market_cap_usd: float | None,
    max_low_cap_usd: float,
    is_crypto: bool,
    impact: NewsImpact,
    crypto_exclusive: bool = True,
    intelligence_mode: bool = False,
) -> tuple[bool, bool, bool]:
    """Return (post_main, post_cap, skip_all). Legacy MC-cap routing when intelligence_mode=False."""
    if is_crypto and crypto_exclusive:
        return False, False, False
    if is_options_news(title=title, body=body) and not symbols:
        return False, False, True
    if is_out_of_news_universe(smallest_market_cap_usd, max_low_cap_usd):
        return False, False, True
    if intelligence_mode:
        if impact.level == IMPACT_GRAY:
            return False, False, False
        post_main = impact.level in {IMPACT_HIGH, IMPACT_MEDIUM, IMPACT_LOW}
        return post_main, False, not post_main
    if impact.skip_entirely:
        return False, False, True
    post_main = impact.post_main
    post_cap = impact.post_cap and (
        smallest_market_cap_usd is None or smallest_market_cap_usd < max_low_cap_usd
    )
    if not post_main and not post_cap:
        return False, False, True
    return post_main, post_cap, False


def _fmt_mcap(value: float | None) -> str:
    if value is None or value <= 0:
        return ""
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.0f}M"
    return f"${value:,.0f}"


def _fmt_float_shares(shares: float | None) -> str:
    if not shares or shares <= 0:
        return ""
    millions = shares / 1_000_000
    if millions >= 100:
        return f"{millions:.0f}M"
    return f"{millions:.1f}M"


def build_trader_context_line(ctx: SymbolNewsContext, *, catalyst: str = "") -> str:
    """Compact scanner-style context below the headline."""
    parts: list[str] = []
    mcap = _fmt_mcap(ctx.market_cap_usd)
    if mcap:
        parts.append(f"MC {mcap}")
    flt = _fmt_float_shares(ctx.float_shares)
    if flt:
        parts.append(f"Float {flt}")
    if ctx.rvol is not None and ctx.rvol > 0:
        text = f"{ctx.rvol:,.0f}x" if ctx.rvol >= 100 else f"{ctx.rvol:g}x"
        parts.append(f"RVOL {text}")
    if ctx.is_runner:
        stars = "★" * max(1, min(ctx.runner_stars, 3))
        parts.append(f"{stars} Runner")
    if ctx.sector:
        parts.append(ctx.sector[:24])
    if catalyst and catalyst not in {"", "No Clear Catalyst", "Ordinary News"}:
        parts.append(catalyst)
    if not parts:
        return ""
    return " · ".join(parts)


def build_priority_line(*, impact: NewsImpact, ai_reason: str = "") -> str:
    reason = re.sub(r"^\s*ai\s*[:\-–]\s*", "", (ai_reason or "").strip(), flags=re.IGNORECASE)
    if reason and reason.lower() not in {"no clear catalyst", "ai", "none"}:
        summary = f"{impact.category} — {reason}"
    else:
        summary = f"{impact.category} — {impact.reason}"
    return f"{impact.emoji} {summary}"[:300]
