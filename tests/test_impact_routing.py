from bot.news.impact_routing import (
    impact_channel_keys_for_level,
    resolve_impact_post_targets,
)
from bot.news.news_intelligence import IMPACT_GRAY, IMPACT_HIGH, IMPACT_LOW, IMPACT_MEDIUM, classify_impact


def test_impact_channel_keys_high_includes_all_news():
    keys = impact_channel_keys_for_level(IMPACT_HIGH)
    assert keys == frozenset({"all_news", "high"})


def test_impact_channel_keys_gray_noise_only():
    keys = impact_channel_keys_for_level(IMPACT_GRAY)
    assert keys == frozenset({"noise"})


def test_resolve_gray_posts_to_noise_not_skipped():
    impact = classify_impact("Company reiterates prior guidance in podcast appearance")
    keys, skip = resolve_impact_post_targets(impact, news_filter_enabled=True)
    assert skip is False
    assert keys == frozenset({"noise"})


def test_resolve_high_posts_all_and_high():
    impact = classify_impact("Company receives FDA approval for lead drug")
    keys, skip = resolve_impact_post_targets(impact, news_filter_enabled=True)
    assert skip is False
    assert keys == frozenset({"all_news", "high"})


def test_resolve_medium_and_low_channels():
    medium = classify_impact("Company announces strategic partnership with major retailer")
    low = classify_impact("Company announces appointment of new board member")
    m_keys, _ = resolve_impact_post_targets(medium, news_filter_enabled=True)
    l_keys, _ = resolve_impact_post_targets(low, news_filter_enabled=True)
    assert m_keys == frozenset({"all_news", "medium"})
    assert l_keys == frozenset({"all_news", "low"})


def test_resolve_out_of_universe_skipped():
    impact = classify_impact("FDA approval for lead drug")
    _, skip = resolve_impact_post_targets(
        impact,
        out_of_universe=True,
    )
    assert skip is True
