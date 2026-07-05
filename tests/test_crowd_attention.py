"""Phase 4 — Crowd Attention Score tests."""

from bot.news.crowd_attention import compute_crowd_attention_score
from bot.news.news_intelligence import IMPACT_GRAY, IMPACT_HIGH, SymbolNewsContext


def test_crowd_score_high_with_runner():
    ctx = SymbolNewsContext(
        symbol="ABC",
        rvol=6.0,
        is_runner=True,
        premarket_turnover_usd=500_000,
    )
    score = compute_crowd_attention_score(impact_level=IMPACT_HIGH, context=ctx)
    assert score >= 70


def test_crowd_score_noise_low():
    score = compute_crowd_attention_score(
        impact_level=IMPACT_GRAY,
        context=None,
        repeated_pr=True,
    )
    assert score <= 20
