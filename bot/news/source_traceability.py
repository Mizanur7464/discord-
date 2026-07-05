"""SDS-Core-03 v1.11 §4.6 / §5 source traceability for News Intelligence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bot.news.benzinga import BenzingaArticle

_ET = ZoneInfo("America/New_York")

# §4.6 Source Quality Rating
SOURCE_PROFILES: dict[str, dict[str, str | float | tuple[float, float]]] = {
    "sec_filing": {"label": "SEC Filing", "type": "SEC Filing", "stars": 5, "conf": (90.0, 98.0)},
    "fda": {"label": "FDA", "type": "Regulatory", "stars": 5, "conf": (90.0, 98.0)},
    "clinicaltrials": {"label": "ClinicalTrials.gov", "type": "Clinical", "stars": 5, "conf": (90.0, 98.0)},
    "company_pr": {"label": "Company PR", "type": "Company PR", "stars": 4, "conf": (75.0, 90.0)},
    "globenewswire": {"label": "GlobeNewswire", "type": "Newswire", "stars": 4, "conf": (75.0, 90.0)},
    "business_wire": {"label": "Business Wire", "type": "Newswire", "stars": 4, "conf": (75.0, 90.0)},
    "pr_newswire": {"label": "PR Newswire", "type": "Newswire", "stars": 4, "conf": (75.0, 90.0)},
    "reuters": {"label": "Reuters", "type": "Wire", "stars": 3, "conf": (55.0, 75.0)},
    "benzinga": {"label": "Benzinga", "type": "Aggregator", "stars": 3, "conf": (55.0, 75.0)},
    "social_media": {"label": "Social Media", "type": "Social", "stars": 2, "conf": (20.0, 50.0)},
    "community": {"label": "Community Post", "type": "Community", "stars": 1, "conf": (20.0, 50.0)},
}

_URL_HINTS: tuple[tuple[str, str], ...] = (
    ("sec.gov", "sec_filing"),
    ("fda.gov", "fda"),
    ("clinicaltrials.gov", "clinicaltrials"),
    ("globenewswire.com", "globenewswire"),
    ("businesswire.com", "business_wire"),
    ("prnewswire.com", "pr_newswire"),
    ("reuters.com", "reuters"),
    ("benzinga.com", "benzinga"),
    ("twitter.com", "social_media"),
    ("x.com", "social_media"),
    ("reddit.com", "community"),
)

_NAME_HINTS: tuple[tuple[str, str], ...] = (
    ("globe newswire", "globenewswire"),
    ("globenewswire", "globenewswire"),
    ("business wire", "business_wire"),
    ("pr newswire", "pr_newswire"),
    ("prnewswire", "pr_newswire"),
    ("reuters", "reuters"),
    ("benzinga", "benzinga"),
    ("sec filing", "sec_filing"),
    ("fda", "fda"),
    ("clinicaltrials", "clinicaltrials"),
    ("company pr", "company_pr"),
)


@dataclass
class SourceTraceability:
    source_type: str
    source_name: str
    quality_stars: int
    quality_display: str
    original_url: str
    mirror_url: str
    published_et: str
    first_detected_et: str
    confidence: float
    source_key: str = ""


def _format_et(iso_ts: str) -> str:
    if not iso_ts:
        return ""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.astimezone(_ET).strftime("%H:%M:%S ET")
    except (TypeError, ValueError):
        return ""


def _stars_display(count: int) -> str:
    count = max(1, min(5, count))
    return "★" * count + "☆" * (5 - count)


def _confidence_for_key(key: str, *, negated: bool = False) -> float:
    profile = SOURCE_PROFILES.get(key, SOURCE_PROFILES["benzinga"])
    lo, hi = profile["conf"]  # type: ignore[misc]
    base = (float(lo) + float(hi)) / 2.0
    if negated:
        base = max(20.0, base - 25.0)
    return round(min(98.0, max(20.0, base)), 1)


def detect_source_key(
    *,
    source_name: str = "",
    url: str = "",
    text: str = "",
) -> str:
    """Resolve canonical source key from name, URL, or article text."""
    hay = f"{source_name} {url} {text}".lower()
    for needle, key in _NAME_HINTS:
        if needle in hay:
            return key
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    for fragment, key in _URL_HINTS:
        if fragment in host or fragment in hay:
            return key
    if re.search(r"\b(8-k|10-q|10-k|s-1|s-3|sec filing)\b", hay):
        return "sec_filing"
    if "globenewswire" in hay:
        return "globenewswire"
    return "benzinga"


def build_source_traceability(
    article: BenzingaArticle,
    *,
    first_detected_iso: str = "",
    mirror_url: str = "",
    negated: bool = False,
) -> SourceTraceability:
    """Build §5 static source fields for timeline display."""
    text = f"{article.title}\n{article.body}"
    key = detect_source_key(
        source_name=article.source_name or article.source_type,
        url=article.url,
        text=text,
    )
    profile = SOURCE_PROFILES.get(key, SOURCE_PROFILES["benzinga"])
    stars = int(profile["stars"])  # type: ignore[arg-type]
    label = str(profile["label"])
    source_type = str(profile["type"])
    original = (article.original_url or article.url or "").strip()
    published_et = _format_et(article.published)
    first_et = _format_et(first_detected_iso) if first_detected_iso else ""
    return SourceTraceability(
        source_type=source_type,
        source_name=label,
        quality_stars=stars,
        quality_display=_stars_display(stars),
        original_url=original,
        mirror_url=(mirror_url or "").strip(),
        published_et=published_et,
        first_detected_et=first_et,
        confidence=_confidence_for_key(key, negated=negated),
        source_key=key,
    )


def score_confidence_from_source(
    source_key: str,
    *,
    text: str = "",
    negated: bool = False,
) -> float:
    """§4.6 confidence from source quality; text cues can upgrade to SEC/FDA tier."""
    key = source_key or "benzinga"
    lower = text.lower()
    if re.search(r"\b(8-k|10-q|10-k|s-1|s-3|sec filing)\b", lower):
        key = "sec_filing"
    elif "clinicaltrials.gov" in lower:
        key = "clinicaltrials"
    elif "fda.gov" in lower:
        key = "fda"
    return _confidence_for_key(key, negated=negated)
