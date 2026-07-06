"""SDS-Core-03 §4 rule engine — reasoning layer on keyword matches."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from bot.news.keyword_dictionary import CATALYST_TYPE_KEYWORDS, FINANCING_DILUTION_KEYWORDS
from bot.news.keyword_scanner import KeywordScanResult, normalize_news_text, scan_keywords
from bot.news.news_intelligence import IMPACT_EMOJI, IMPACT_GRAY, IMPACT_HIGH, IMPACT_LOW, IMPACT_MEDIUM

# §4.1 Exclusion — root → phrases that invalidate catalyst match
EXCLUSION_RULES: dict[str, tuple[str, ...]] = {
    "fda": (
        "fda conference",
        "fda calendar",
        "fda reminder",
        "fda meeting schedule",
        "fda speaker",
        "fda panel discussion",
        "fda webinar",
    ),
    "offering": (
        "our offering of services",
        "product offering",
        "service offering",
    ),
    "partnership": (
        "in partnership with the community",
    ),
    "approval": (
        "subject to approval",
        "pending approval",
        "seeking approval",
    ),
}

NEGATION_PHRASES = (
    "no ",
    " not ",
    "did not",
    "failed to",
    "unable to",
    "terminated",
    "cancelled",
    "canceled",
    "withdrawn",
    " rejected",
    "does not",
    "will not",
    "without approval",
)

FUTURE_TENSE = (
    "will ",
    "expects",
    "plans to",
    " may ",
    " could ",
    "is seeking",
    "intends to",
    "anticipates",
)

COMPLETED_TENSE = (
    "completed",
    "received",
    "approved",
    "closed",
    "executed",
    "has entered into",
    "finalized",
    "grants approval",
)

# §4.5 priority (lower index = higher priority)
EVENT_PRIORITY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Trading Status", ("trading halt", "halted", "resume trading", "volatility pause", "luld")),
    ("FDA/Regulatory", ("fda approval", "fda rejection", "clinical hold", "complete response letter", "fda clearance")),
    ("M&A", ("acquisition", "merger", "buyout", "takeover")),
    ("Financing", FINANCING_DILUTION_KEYWORDS),
    ("Partnership", ("partnership", "collaboration", "strategic alliance")),
)

URGENCY_IMMEDIATE = "Immediate"
URGENCY_TODAY = "Today"
URGENCY_THIS_WEEK = "This Week"
URGENCY_LONG_TERM = "Long Term"

DUPLICATE_WINDOW_SECONDS = 24 * 3600
SIMILARITY_THRESHOLD = 0.88


@dataclass
class DetectedEvent:
    label: str
    catalyst_type: str
    impact_level: str
    role: str  # primary | secondary | risk


@dataclass
class RuleEngineResult:
    keyword: KeywordScanResult
    impact_level: str
    impact_emoji: str
    catalyst_type: str
    catalyst_tags: list[str]
    matched_keywords: list[str]
    dilution_risk: bool
    reason: str
    confidence: float = 75.0
    urgency: str = URGENCY_TODAY
    negated: bool = False
    excluded: bool = False
    is_duplicate: bool = False
    repeated_pr: bool = False
    primary_event: DetectedEvent | None = None
    secondary_events: list[DetectedEvent] = field(default_factory=list)
    metadata: dict[str, list[str]] = field(default_factory=dict)
    canonical_keyword: str = ""


class DuplicateDetector:
    """§4.7 — rolling headline similarity per ticker."""

    def __init__(self, *, window_seconds: int = DUPLICATE_WINDOW_SECONDS) -> None:
        self._window = window_seconds
        self._records: dict[str, list[tuple[float, str, str]]] = {}

    @staticmethod
    def _normalize_headline(text: str) -> str:
        cleaned = normalize_news_text(text)
        cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    def check(self, *, symbol: str, headline: str, catalyst_type: str) -> bool:
        symbol = (symbol or "").upper()
        key = symbol or "_NO_SYMBOL_"
        now = time.time()
        norm = self._normalize_headline(headline)
        if not norm:
            return False

        recent = [
            (ts, head, cat)
            for ts, head, cat in self._records.get(key, [])
            if now - ts <= self._window
        ]
        self._records[key] = recent

        for _, prev_head, prev_cat in recent:
            ratio = SequenceMatcher(None, norm, prev_head).ratio()
            if ratio >= SIMILARITY_THRESHOLD and (not catalyst_type or catalyst_type == prev_cat):
                return True

        recent.append((now, norm, catalyst_type))
        self._records[key] = recent
        return False


_duplicate_detector = DuplicateDetector()


def _contains(text: str, phrase: str | tuple[str, ...]) -> bool:
    if isinstance(phrase, tuple):
        return any(_contains(text, p) for p in phrase)
    if phrase in text:
        return True
    try:
        return bool(re.search(r"\b" + re.escape(phrase) + r"\b", text, re.IGNORECASE))
    except re.error:
        return phrase in text


GRAY_OVERRIDE_PHRASES = (
    "reiterates",
    "podcast",
    "market commentary",
    "industry outlook",
    "reminder",
    "participation notice",
    "blog post",
)


def _is_routine_noise(text: str) -> bool:
    return any(_contains(text, phrase) for phrase in GRAY_OVERRIDE_PHRASES)


def _check_exclusion(text: str) -> str | None:
    for root, phrases in EXCLUSION_RULES.items():
        if root not in text and not any(root in p for p in phrases):
            continue
        for phrase in phrases:
            if _contains(text, phrase):
                return phrase
    return None


def _check_negation(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    idx = text.find(keyword)
    if idx < 0:
        return False
    window = text[max(0, idx - 40) : idx + len(keyword) + 20]
    return any(neg in window for neg in NEGATION_PHRASES)


def _detect_urgency(text: str, impact_level: str) -> str:
    if _contains(text, ("trading halt", "fda approval", "fda rejection", "clinical hold")):
        if any(_contains(text, t) for t in COMPLETED_TENSE):
            return URGENCY_IMMEDIATE
    if any(_contains(text, t) for t in FUTURE_TENSE):
        return URGENCY_LONG_TERM if "facility" in text or "expansion" in text else URGENCY_THIS_WEEK
    if any(_contains(text, t) for t in COMPLETED_TENSE):
        return URGENCY_IMMEDIATE if impact_level == IMPACT_HIGH else URGENCY_TODAY
    if impact_level == IMPACT_HIGH:
        return URGENCY_IMMEDIATE
    if impact_level == IMPACT_MEDIUM:
        return URGENCY_TODAY
    return URGENCY_LONG_TERM


def _score_confidence(text: str, *, negated: bool, source: str = "") -> float:
    from bot.news.source_traceability import detect_source_key, score_confidence_from_source

    key = detect_source_key(source_name=source, text=text)
    return score_confidence_from_source(key, text=text, negated=negated)


def _detect_events(text: str) -> list[DetectedEvent]:
    """§4.4 multi-event detection."""
    events: list[DetectedEvent] = []
    seen: set[str] = set()

    for priority_label, phrases in EVENT_PRIORITY:
        hit = next((p for p in phrases if _contains(text, p)), None)
        if not hit or priority_label in seen:
            continue
        seen.add(priority_label)
        ctype = ""
        for name, kw_phrases in CATALYST_TYPE_KEYWORDS.items():
            if any(_contains(text, p) for p in kw_phrases):
                ctype = name
                break
        if "financing" in priority_label.lower() or hit in FINANCING_DILUTION_KEYWORDS:
            level = IMPACT_HIGH
            role = "risk"
            ctype = ctype or "Offering"
        elif priority_label in {"FDA/Regulatory", "M&A", "Trading Status"}:
            level = IMPACT_HIGH
            role = "primary" if not events else "secondary"
        else:
            level = IMPACT_MEDIUM
            role = "secondary"
        events.append(
            DetectedEvent(
                label=priority_label,
                catalyst_type=ctype or priority_label,
                impact_level=level,
                role=role,
            )
        )

    for ctype, phrases in CATALYST_TYPE_KEYWORDS.items():
        if ctype in seen:
            continue
        if any(_contains(text, p) for p in phrases):
            events.append(
                DetectedEvent(
                    label=ctype,
                    catalyst_type=ctype,
                    impact_level=IMPACT_MEDIUM,
                    role="secondary",
                )
            )
            seen.add(ctype)

    if not events:
        return events

    primary_idx = 0
    for i, ev in enumerate(events):
        if ev.role == "primary" or ev.impact_level == IMPACT_HIGH:
            primary_idx = i
            break
    primary = events[primary_idx]
    primary.role = "primary"
    for j, ev in enumerate(events):
        if j != primary_idx:
            ev.role = "risk" if ev.catalyst_type in {"Offering", "PIPE", "Private Placement", "Dilution"} else "secondary"
    return events


def apply_rule_engine(
    text: str,
    *,
    symbol: str = "",
    article_id: str = "",
    source: str = "benzinga",
) -> RuleEngineResult:
    """Full §4 pipeline on normalized news text."""
    normalized = normalize_news_text(text)
    keyword = scan_keywords(text)

    exclusion = _check_exclusion(normalized)
    if exclusion:
        return RuleEngineResult(
            keyword=keyword,
            impact_level=IMPACT_GRAY,
            impact_emoji=IMPACT_EMOJI[IMPACT_GRAY],
            catalyst_type=keyword.catalyst_type,
            catalyst_tags=keyword.catalyst_tags,
            matched_keywords=keyword.matched_keywords,
            dilution_risk=keyword.dilution_risk,
            reason=f"excluded: {exclusion}",
            confidence=_score_confidence(normalized, negated=False, source=source),
            urgency=URGENCY_LONG_TERM,
            excluded=True,
            metadata=keyword.metadata,
        )

    negated = False
    for kw in keyword.matched_keywords:
        if _check_negation(normalized, kw):
            negated = True
            break

    if _is_routine_noise(normalized) and not keyword.financing_high_impact:
        keyword = KeywordScanResult(
            impact_level=IMPACT_GRAY,
            impact_emoji=IMPACT_EMOJI[IMPACT_GRAY],
            catalyst_type=keyword.catalyst_type,
            catalyst_tags=keyword.catalyst_tags,
            matched_keywords=keyword.matched_keywords,
            dilution_risk=keyword.dilution_risk,
            metadata=keyword.metadata,
            reason="routine / low-value",
        )

    events = _detect_events(normalized)
    primary = events[0] if events else None

    level = keyword.impact_level
    catalyst = keyword.catalyst_type
    dilution = keyword.dilution_risk
    reason = keyword.reason

    if negated and level == IMPACT_HIGH:
        level = IMPACT_GRAY if keyword.ambiguous_root else IMPACT_LOW
        reason = "negated keyword match"

    routine_noise = _is_routine_noise(normalized) and not keyword.financing_high_impact
    if routine_noise:
        level = IMPACT_GRAY
        reason = "routine / low-value"
        events = []
        primary = None
    elif primary:
        level = primary.impact_level
        catalyst = primary.catalyst_type or catalyst
        if primary.role == "risk":
            dilution = True

    headline = text.split("\n", 1)[0]
    is_dup = _duplicate_detector.check(
        symbol=symbol,
        headline=headline,
        catalyst_type=catalyst,
    )

    confidence = _score_confidence(normalized, negated=negated, source=source)
    urgency = _detect_urgency(normalized, level)
    from bot.news.canonical_keyword import resolve_canonical_keyword

    canonical = resolve_canonical_keyword(
        text,
        matched=keyword.matched_keywords,
        catalyst_type=catalyst,
    )

    return RuleEngineResult(
        keyword=keyword,
        impact_level=level,
        impact_emoji=IMPACT_EMOJI.get(level, IMPACT_EMOJI[IMPACT_LOW]),
        catalyst_type=catalyst,
        catalyst_tags=keyword.catalyst_tags,
        matched_keywords=keyword.matched_keywords,
        dilution_risk=dilution,
        reason=reason,
        confidence=confidence,
        urgency=urgency,
        negated=negated,
        is_duplicate=is_dup,
        repeated_pr=is_dup,
        primary_event=primary,
        secondary_events=[e for e in events if e.role != "primary"],
        metadata=keyword.metadata,
        canonical_keyword=canonical,
    )
