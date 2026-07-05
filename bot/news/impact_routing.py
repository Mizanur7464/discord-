"""Impact-level Discord channel routing for News Intelligence (SDS-Core-03 §2)."""

from __future__ import annotations

from bot.news.news_intelligence import (
    IMPACT_GRAY,
    IMPACT_HIGH,
    IMPACT_LOW,
    IMPACT_MEDIUM,
    NewsImpact,
)

IMPACT_LEVEL_LABELS = {
    IMPACT_HIGH: "High",
    IMPACT_MEDIUM: "Medium",
    IMPACT_LOW: "Low",
    IMPACT_GRAY: "Noise",
}

# Stored Actionability enum → UI label (§5)
ACTIONABILITY_LABELS = {
    IMPACT_HIGH: "Immediate Watch",
    IMPACT_MEDIUM: "Monitor",
    IMPACT_LOW: "Research",
    IMPACT_GRAY: "Ignore",
}


def impact_channel_keys_for_level(level: str) -> frozenset[str]:
    """Which impact-tree channel keys receive this news item."""
    if level == IMPACT_HIGH:
        return frozenset({"all_news", "high"})
    if level == IMPACT_MEDIUM:
        return frozenset({"all_news", "medium"})
    if level == IMPACT_LOW:
        return frozenset({"all_news", "low"})
    if level == IMPACT_GRAY:
        return frozenset({"noise"})
    return frozenset()


def resolve_impact_post_targets(
    impact: NewsImpact,
    *,
    news_filter_enabled: bool = True,
    out_of_universe: bool = False,
    is_options_without_symbol: bool = False,
) -> tuple[frozenset[str], bool]:
    """Return (impact channel keys, skip_all).

    Gray/noise posts only to the noise channel — never to All News (§2 default-visibility).
    """
    if out_of_universe or is_options_without_symbol:
        return frozenset(), True
    if impact.level == IMPACT_GRAY:
        if news_filter_enabled:
            return frozenset({"noise"}), False
        return frozenset(), True
    if news_filter_enabled and impact.skip_entirely:
        return frozenset(), True
    return impact_channel_keys_for_level(impact.level), False
