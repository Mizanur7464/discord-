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


@dataclass
class SymbolNewsContext:
    symbol: str
    float_shares: float | None = None
    market_cap_usd: float | None = None
    country_flag: str = "🇺🇸"
    sector: str = ""
    rvol: float | None = None
    is_runner: bool = False
    runner_stars: int = 0


def is_options_news(*, title: str = "", body: str = "") -> bool:
    text = f"{title}\n{body}".lower()
    return any(keyword in text for keyword in OPTIONS_KEYWORDS)


def classify_impact(
    text: str,
    *,
    category: str = "",
    sentiment: str = "neutral",
) -> NewsImpact:
    """Classify trading impact (color = urgency, not bullish/bearish)."""
    lower = text.lower()
    category = category or classify_news_text(text, sentiment=sentiment)

    if any(keyword in lower for keyword in GRAY_KEYWORDS):
        level = IMPACT_GRAY
        reason = "routine / low-value"
    elif any(keyword in lower for keyword in HIGH_KEYWORDS) or category in HIGH_CATEGORIES:
        level = IMPACT_HIGH
        reason = "high-impact catalyst"
    elif any(keyword in lower for keyword in MEDIUM_KEYWORDS):
        level = IMPACT_MEDIUM
        reason = "tradable catalyst"
    elif any(keyword in lower for keyword in LOW_KEYWORDS) or category == "Ordinary News":
        level = IMPACT_LOW
        reason = "watch only"
    elif category in {"Partnership", "Contract Announcement", "Earnings"}:
        level = IMPACT_MEDIUM
        reason = category.lower()
    elif sentiment == "bullish":
        level = IMPACT_MEDIUM
        reason = "bullish signal"
    elif category == "No Clear Catalyst":
        level = IMPACT_GRAY
        reason = "no clear catalyst"
    else:
        level = IMPACT_LOW
        reason = "low impact"

    emoji = IMPACT_EMOJI[level]
    skip_entirely = level == IMPACT_GRAY
    post_main = level in {IMPACT_HIGH, IMPACT_MEDIUM}
    post_cap = level in {IMPACT_HIGH, IMPACT_MEDIUM, IMPACT_LOW}
    return NewsImpact(
        level=level,
        emoji=emoji,
        category=category,
        post_main=post_main,
        post_cap=post_cap,
        skip_entirely=skip_entirely,
        reason=reason,
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
) -> tuple[bool, bool, bool]:
    """Return (post_main, post_cap, skip_all)."""
    if is_crypto and crypto_exclusive:
        return False, False, False
    if impact.skip_entirely:
        return False, False, True
    if is_options_news(title=title, body=body) and not symbols:
        return False, False, True
    if smallest_market_cap_usd is not None and smallest_market_cap_usd >= max_low_cap_usd:
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
