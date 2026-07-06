"""SDS — company vs sector vs macro news scope (routing, not classification by MC)."""

from __future__ import annotations

NEWS_SCOPE_COMPANY = "company"
NEWS_SCOPE_SECTOR = "sector"
NEWS_SCOPE_MACRO = "macro"

MACRO_PHRASES = (
    "opec",
    "oil prices",
    "crude oil",
    "brent crude",
    "wti ",
    "federal reserve",
    "fed chair",
    "fed rate",
    "interest rate",
    "inflation",
    "jobs report",
    "nonfarm payroll",
    "cpi report",
    "gdp ",
    "treasury yield",
    "s&p 500",
    "dow jones",
    "nasdaq composite",
    "market sell-off",
    "market rally",
    "wall street",
    "geopolitical",
    "trade war",
    "tariff",
    "government shutdown",
    "white house",
)

SECTOR_PHRASES = (
    "sector",
    "industry",
    "biotech stocks",
    "tech stocks",
    "energy stocks",
    "semiconductor stocks",
    "retail stocks",
)

COMPANY_CATALYST_PHRASES = (
    "fda approval",
    "fda clearance",
    "clinical hold",
    "phase 1",
    "phase 2",
    "phase 3",
    "trial",
    "offering",
    "private placement",
    "earnings",
    "guidance",
    "acquisition",
    "merger",
    "appoints",
    "ceo ",
    "cfo ",
    "contract awarded",
    "patent",
    "uplisting",
    "reverse split",
    "trading halt",
)


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(p in text for p in phrases)


def classify_news_scope(
    *,
    title: str = "",
    body: str = "",
    symbols: list[str] | None = None,
) -> str:
    """Return company | sector | macro for post routing."""
    text = f"{title}\n{body}".lower()
    tickers = [str(s).upper() for s in (symbols or []) if s]
    count = len(tickers)

    if count == 0:
        return NEWS_SCOPE_MACRO

    has_company_catalyst = _contains_any(text, COMPANY_CATALYST_PHRASES)
    has_macro = _contains_any(text, MACRO_PHRASES)
    has_sector = _contains_any(text, SECTOR_PHRASES)

    if has_macro and count >= 2:
        return NEWS_SCOPE_MACRO
    if count >= 4 and not has_company_catalyst:
        return NEWS_SCOPE_MACRO
    if has_sector and count >= 2 and not has_company_catalyst:
        return NEWS_SCOPE_SECTOR
    if count == 1:
        return NEWS_SCOPE_COMPANY
    if has_company_catalyst:
        return NEWS_SCOPE_COMPANY
    if count >= 3:
        return NEWS_SCOPE_MACRO
    return NEWS_SCOPE_COMPANY


def is_multi_ticker_post(scope: str) -> bool:
    return scope in {NEWS_SCOPE_MACRO, NEWS_SCOPE_SECTOR}
