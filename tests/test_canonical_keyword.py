from bot.news.canonical_keyword import resolve_canonical_keyword
from bot.news.ai_output import build_ai_output_from_rules
from bot.news.news_intelligence import classify_impact


def test_fda_approval_canonical():
    assert resolve_canonical_keyword("XYZ receives FDA approval for drug") == "FDA Approval"


def test_private_placement_canonical():
    assert resolve_canonical_keyword("Company closes $10M private placement financing") == "Private Placement"


def test_classify_impact_sets_canonical():
    impact = classify_impact("ABC announces FDA approval for lead candidate", symbol="ABC")
    assert impact.canonical_keyword == "FDA Approval"
    ai = build_ai_output_from_rules(impact)
    assert ai.keyword == "FDA Approval"
