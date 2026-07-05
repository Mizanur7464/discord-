"""Phase 4 — SDS §6 AI output tests."""

from bot.news.ai_output import build_ai_output_from_rules
from bot.news.news_intelligence import IMPACT_HIGH, classify_impact


def test_build_ai_output_from_rules_fda():
    impact = classify_impact("XYZ receives FDA approval", symbol="XYZ", article_id="t1")
    ai = build_ai_output_from_rules(impact, sentiment="bullish", ai_reason="FDA approval catalyst")
    assert ai.impact_level == IMPACT_HIGH
    assert ai.summary
    assert ai.keyword


def test_build_ai_output_offering_dilution():
    impact = classify_impact("Company announces public offering priced at $2 per share")
    ai = build_ai_output_from_rules(impact)
    assert impact.dilution_risk
    assert ai.dilution_risk is True
