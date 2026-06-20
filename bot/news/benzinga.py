"""Optional Benzinga news catalyst lookup."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import quote

logger = logging.getLogger(__name__)

CATALYST_KEYWORDS = (
    "fda",
    "approval",
    "contract",
    "partnership",
    "acquisition",
    "merger",
    "earnings",
    "guidance",
    "upgrade",
    "downgrade",
    "offering",
    "buyback",
    "short squeeze",
    "breakthrough",
    "patent",
    "trial",
    "phase",
    "launch",
)


@dataclass
class CatalystResult:
    symbol: str
    headline: str
    url: str = ""
    keywords: list[str] = field(default_factory=list)
    is_bullish_catalyst: bool = False

    @property
    def summary(self) -> str:
        if not self.keywords:
            return self.headline[:200]
        return f"{self.headline[:160]} [{', '.join(self.keywords[:4])}]"


def _extract_keywords(text: str) -> list[str]:
    lower = text.lower()
    found = [word for word in CATALYST_KEYWORDS if word in lower]
    return found[:6]


def parse_benzinga_payload(symbol: str, payload) -> CatalystResult | None:
    items = payload if isinstance(payload, list) else payload.get("news") or payload.get("data") or []
    if not items:
        return None
    item = items[0]
    title = str(item.get("title") or item.get("headline") or "").strip()
    if not title:
        return None
    url = str(item.get("url") or item.get("link") or "")
    keywords = _extract_keywords(title)
    bearish = any(token in title.lower() for token in ("downgrade", "offering", "bankruptcy", "delisting"))
    return CatalystResult(
        symbol=symbol.upper(),
        headline=title,
        url=url,
        keywords=keywords,
        is_bullish_catalyst=bool(keywords) and not bearish,
    )


def fetch_catalyst_sync(symbol: str, api_key: str) -> CatalystResult | None:
    if not api_key:
        return None
    try:
        import urllib.request

        url = (
            "https://api.benzinga.com/api/v2/news"
            f"?token={quote(api_key)}&symbols={quote(symbol.upper())}&pageSize=3&displayOutput=full"
        )
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        if raw.lstrip().startswith("<"):
            logger.warning("Benzinga returned non-JSON for %s", symbol)
            return None
        import json

        payload = json.loads(raw)
        return parse_benzinga_payload(symbol, payload)
    except Exception as exc:
        logger.warning("Benzinga catalyst lookup failed for %s: %s", symbol, exc)
        return None


def score_catalyst(catalyst: CatalystResult | None) -> tuple[int, list[str], list[str]]:
    if not catalyst:
        return 0, [], []
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []
    if catalyst.is_bullish_catalyst:
        score += 8
        reasons.append(f"Benzinga catalyst: {catalyst.summary[:120]}")
    elif catalyst.keywords:
        score += 3
        warnings.append(f"Benzinga headline with mixed keywords: {', '.join(catalyst.keywords)}")
    else:
        warnings.append("Benzinga headline without strong catalyst keywords")
    return score, reasons, warnings
