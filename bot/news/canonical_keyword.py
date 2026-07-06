"""SDS §3.8 / §3.9 — canonical keyword resolution for AI output."""

from __future__ import annotations

from bot.news.keyword_dictionary import ALIAS_TO_CANONICAL
from bot.news.keyword_scanner import normalize_news_text

# Phrase (normalized lowercase) → §3.9 glossary display label
PHRASE_TO_CANONICAL: dict[str, str] = {
    "fda approval": "FDA Approval",
    "fda clearance": "FDA Approval",
    "fda accepts": "FDA Approval",
    "fda accept": "FDA Approval",
    "agency approval granted": "FDA Approval",
    "fast track designation": "Fast Track / Breakthrough Therapy",
    "fast track": "Fast Track / Breakthrough Therapy",
    "breakthrough therapy designation": "Fast Track / Breakthrough Therapy",
    "breakthrough therapy": "Fast Track / Breakthrough Therapy",
    "orphan drug": "Fast Track / Breakthrough Therapy",
    "fda rejection": "FDA Rejection / Complete Response Letter (CRL)",
    "complete response letter": "FDA Rejection / Complete Response Letter (CRL)",
    "clinical hold": "Clinical Hold",
    "fda places hold": "Clinical Hold",
    "trial paused by fda": "Clinical Hold",
    "private placement": "Private Placement",
    "private placement financing": "Private Placement",
    "pipe financing": "Private Placement",
    "pipe": "Private Placement",
    "securities purchase agreement": "Private Placement",
    "registered direct offering": "Registered Direct Offering",
    "registered direct": "Registered Direct Offering",
    "direct offering": "Registered Direct Offering",
    "public offering": "Registered Direct Offering",
    "standby equity purchase agreement": "Registered Direct Offering",
    "sepa": "Registered Direct Offering",
    "equity purchase facility": "Registered Direct Offering",
    "committed equity facility": "Registered Direct Offering",
    "reverse split": "Reverse Split",
    "reverse stock split": "Reverse Split",
    "share consolidation": "Reverse Split",
    "trading halt": "Trading Halt",
    "halted": "Trading Halt",
    "volatility pause": "Trading Halt",
    "resume trading": "Resume Trading",
    "acquisition": "Merger / Acquisition / Buyout",
    "merger": "Merger / Acquisition / Buyout",
    "buyout": "Merger / Acquisition / Buyout",
    "takeover": "Merger / Acquisition / Buyout",
    "partnership": "Partnership / Collaboration",
    "collaboration": "Partnership / Collaboration",
    "strategic alliance": "Partnership / Collaboration",
    "distribution agreement": "Partnership / Collaboration",
    "schedule 13d": "Schedule 13D / 13G",
    "schedule 13g": "Schedule 13D / 13G",
    "lock-up expiration": "Lock-up Expiration",
    "share unlock": "Lock-up Expiration",
    "atm offering": "Registered Direct Offering",
    "shelf registration": "Registered Direct Offering",
    "dilution": "Private Placement",
}

CATALYST_TYPE_TO_CANONICAL: dict[str, str] = {
    "FDA/Biotech": "FDA Approval",
    "Offering": "Registered Direct Offering",
    "Private Placement": "Private Placement",
    "PIPE": "Private Placement",
    "Dilution": "Private Placement",
    "M&A": "Merger / Acquisition / Buyout",
    "Partnership": "Partnership / Collaboration",
}


def _title_case_canonical(key: str) -> str:
    return PHRASE_TO_CANONICAL.get(key, key.title() if key else "—")


def resolve_canonical_keyword(
    text: str,
    *,
    matched: list[str] | None = None,
    catalyst_type: str = "",
) -> str:
    """Map normalized text / matches to one §3.9 canonical keyword label."""
    normalized = normalize_news_text(text)

    for phrase in sorted(PHRASE_TO_CANONICAL.keys(), key=len, reverse=True):
        if phrase in normalized:
            return PHRASE_TO_CANONICAL[phrase]

    for canonical_key, aliases in ALIAS_TO_CANONICAL.items():
        if canonical_key in normalized:
            return _title_case_canonical(canonical_key)
        for alias in aliases:
            if alias in normalized:
                return _title_case_canonical(canonical_key)

    for raw in matched or []:
        key = (raw or "").lower().strip()
        if key in PHRASE_TO_CANONICAL:
            return PHRASE_TO_CANONICAL[key]
        for phrase, label in PHRASE_TO_CANONICAL.items():
            if phrase in key or key in phrase:
                return label

    if catalyst_type and catalyst_type in CATALYST_TYPE_TO_CANONICAL:
        return CATALYST_TYPE_TO_CANONICAL[catalyst_type]

    return "—"
