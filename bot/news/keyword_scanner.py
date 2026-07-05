"""SDS-Core-03 §3 keyword scanner — normalize, match, classify."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bot.news.keyword_dictionary import (
    ALIAS_TO_CANONICAL,
    CATALYST_TAG_KEYWORDS,
    CATALYST_TYPE_KEYWORDS,
    DISAMBIGUATION_PAIRS,
    FINANCING_DILUTION_KEYWORDS,
    GRAY_KEYWORDS,
    HIGH_BEARISH_KEYWORDS,
    HIGH_BULLISH_KEYWORDS,
    LOW_KEYWORDS,
    MEDIUM_KEYWORDS,
    METADATA_KEYWORD_SETS,
)
from bot.news.news_intelligence import (
    IMPACT_EMOJI,
    IMPACT_GRAY,
    IMPACT_HIGH,
    IMPACT_LOW,
    IMPACT_MEDIUM,
)


@dataclass
class KeywordScanResult:
    impact_level: str
    impact_emoji: str
    catalyst_type: str
    catalyst_tags: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    dilution_risk: bool = False
    financing_high_impact: bool = False
    ambiguous_root: bool = False
    metadata: dict[str, list[str]] = field(default_factory=dict)
    reason: str = ""


def _contains(text: str, phrase: str) -> bool:
    if phrase in text:
        return True
    try:
        return bool(re.search(r"\b" + re.escape(phrase) + r"\b", text, re.IGNORECASE))
    except re.error:
        return phrase in text


def normalize_news_text(text: str) -> str:
    """§3.8 — map alias variants to canonical keywords before matching."""
    lower = text.lower()
    for canonical, aliases in ALIAS_TO_CANONICAL.items():
        for alias in aliases:
            if alias in lower:
                lower = lower.replace(alias, canonical)
    return lower


def _first_match(text: str, phrases: tuple[str, ...]) -> str | None:
    for phrase in phrases:
        if _contains(text, phrase):
            return phrase
    return None


def _match_all(text: str, phrases: tuple[str, ...]) -> list[str]:
    return [p for p in phrases if _contains(text, p)]


def _check_disambiguation(text: str) -> tuple[bool, str]:
    """§3.7 — root term without clear modifier → ambiguous."""
    for root, positive, negative in DISAMBIGUATION_PAIRS:
        if root not in text:
            continue
        if _first_match(text, positive):
            return False, ""
        if _first_match(text, negative):
            return False, ""
        return True, root
    return False, ""


def _detect_catalyst_type(text: str) -> str:
    for ctype, phrases in CATALYST_TYPE_KEYWORDS.items():
        if _first_match(text, phrases):
            return ctype
    return ""


def _detect_catalyst_tags(text: str) -> list[str]:
    tags: list[str] = []
    for tag, phrases in CATALYST_TAG_KEYWORDS.items():
        if _first_match(text, phrases):
            tags.append(tag)
    return tags


def _detect_metadata(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for group, phrases in METADATA_KEYWORD_SETS.items():
        hits = _match_all(text, phrases)
        if hits:
            out[group] = hits
    return out


def scan_keywords(text: str) -> KeywordScanResult:
    """Run SDS §3 keyword dictionary against normalized news text."""
    normalized = normalize_news_text(text)
    matched: list[str] = []
    dilution = bool(_first_match(normalized, FINANCING_DILUTION_KEYWORDS))
    financing_red = dilution

    ambiguous, root = _check_disambiguation(normalized)
    if ambiguous and not dilution:
        return KeywordScanResult(
            impact_level=IMPACT_GRAY,
            impact_emoji=IMPACT_EMOJI[IMPACT_GRAY],
            catalyst_type="",
            catalyst_tags=_detect_catalyst_tags(normalized),
            matched_keywords=[root] if root else [],
            dilution_risk=False,
            ambiguous_root=True,
            metadata=_detect_metadata(normalized),
            reason=f"ambiguous {root} context",
        )

    high_bull = _first_match(normalized, HIGH_BULLISH_KEYWORDS)
    high_bear = _first_match(normalized, HIGH_BEARISH_KEYWORDS)
    medium = _first_match(normalized, MEDIUM_KEYWORDS)
    low = _first_match(normalized, LOW_KEYWORDS)
    gray = _first_match(normalized, GRAY_KEYWORDS)

    if financing_red:
        hit = _first_match(normalized, FINANCING_DILUTION_KEYWORDS) or "financing/dilution"
        matched.append(hit)
        catalyst = _detect_catalyst_type(normalized) or "Offering"
        return KeywordScanResult(
            impact_level=IMPACT_HIGH,
            impact_emoji=IMPACT_EMOJI[IMPACT_HIGH],
            catalyst_type=catalyst,
            catalyst_tags=_detect_catalyst_tags(normalized),
            matched_keywords=matched,
            dilution_risk=True,
            financing_high_impact=True,
            metadata=_detect_metadata(normalized),
            reason="financing/dilution rule (§3.2)",
        )

    if high_bull or high_bear:
        hit = high_bull or high_bear
        matched.append(hit or "")
        return KeywordScanResult(
            impact_level=IMPACT_HIGH,
            impact_emoji=IMPACT_EMOJI[IMPACT_HIGH],
            catalyst_type=_detect_catalyst_type(normalized),
            catalyst_tags=_detect_catalyst_tags(normalized),
            matched_keywords=matched,
            dilution_risk=bool(high_bear and _first_match(normalized, FINANCING_DILUTION_KEYWORDS)),
            metadata=_detect_metadata(normalized),
            reason="high-impact catalyst",
        )

    if gray and not medium and not low:
        matched.append(gray or "")
        return KeywordScanResult(
            impact_level=IMPACT_GRAY,
            impact_emoji=IMPACT_EMOJI[IMPACT_GRAY],
            catalyst_type=_detect_catalyst_type(normalized),
            catalyst_tags=_detect_catalyst_tags(normalized),
            matched_keywords=matched,
            metadata=_detect_metadata(normalized),
            reason="routine / low-value",
        )

    if medium:
        matched.append(medium or "")
        return KeywordScanResult(
            impact_level=IMPACT_MEDIUM,
            impact_emoji=IMPACT_EMOJI[IMPACT_MEDIUM],
            catalyst_type=_detect_catalyst_type(normalized) or "Partnership",
            catalyst_tags=_detect_catalyst_tags(normalized),
            matched_keywords=matched,
            metadata=_detect_metadata(normalized),
            reason="tradable catalyst",
        )

    if low:
        matched.append(low or "")
        return KeywordScanResult(
            impact_level=IMPACT_LOW,
            impact_emoji=IMPACT_EMOJI[IMPACT_LOW],
            catalyst_type=_detect_catalyst_type(normalized),
            catalyst_tags=_detect_catalyst_tags(normalized),
            matched_keywords=matched,
            metadata=_detect_metadata(normalized),
            reason="watch only",
        )

    return KeywordScanResult(
        impact_level=IMPACT_LOW,
        impact_emoji=IMPACT_EMOJI[IMPACT_LOW],
        catalyst_type=_detect_catalyst_type(normalized),
        catalyst_tags=_detect_catalyst_tags(normalized),
        metadata=_detect_metadata(normalized),
        reason="low impact",
    )
