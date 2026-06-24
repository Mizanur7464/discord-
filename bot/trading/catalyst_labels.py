"""Buyer news category labels (Phase 4)."""

from __future__ import annotations

from bot.news.benzinga import CatalystResult

BUYER_NEWS_CATEGORIES: tuple[str, ...] = (
    "Ordinary News",
    "Major Catalyst",
    "Earnings",
    "Public Offering",
    "Reverse Split",
    "FDA / Biotech Catalyst",
    "Contract Announcement",
    "Partnership",
    "No Clear Catalyst",
)

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Earnings": ("earnings", "guidance", "eps", "revenue beat", "quarterly results"),
    "Public Offering": ("public offering", "offering", "atm", "shelf", "registered direct"),
    "Reverse Split": ("reverse split", "reverse-split", "share consolidation", "1-for-"),
    "FDA / Biotech Catalyst": ("fda", "approval", "trial", "phase 1", "phase 2", "phase 3", "biotech", "breakthrough", "patent"),
    "Contract Announcement": ("contract", "award", "agreement signed", "wins deal", "government contract"),
    "Partnership": ("partnership", "collaboration", "joint venture", "licensing deal", "strategic alliance"),
    "Major Catalyst": ("acquisition", "merger", "buyout", "upgrade", "short squeeze", "launch", "buyback"),
}


def _match_category(text: str) -> str | None:
    lower = text.lower()
    for label, keys in CATEGORY_KEYWORDS.items():
        if any(key in lower for key in keys):
            return label
    return None


def classify_news_text(text: str, *, sentiment: str = "neutral") -> str:
    """Classify headline/body into buyer news category."""
    if not text.strip():
        return "No Clear Catalyst"
    matched = _match_category(text)
    if matched:
        return matched
    if sentiment == "bullish":
        return "Major Catalyst"
    if any(word in text.lower() for word in ("reports", "announces", "update", "sec filing", "form 8-k")):
        return "Ordinary News"
    return "No Clear Catalyst"


def classify_catalyst(
    *,
    catalyst: CatalystResult | None = None,
    news_bullish: bool = False,
    mosquito_confirmed: bool = False,
    text: str = "",
) -> tuple[str, bool]:
    combined = text
    if catalyst:
        combined = f"{combined} {catalyst.headline} {' '.join(catalyst.keywords)}"
    label = classify_news_text(combined, sentiment="bullish" if news_bullish else "neutral")
    if label == "No Clear Catalyst" and mosquito_confirmed:
        return "Ordinary News", True
    return label, label != "No Clear Catalyst"
