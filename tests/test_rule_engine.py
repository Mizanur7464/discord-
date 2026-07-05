from bot.news.news_intelligence import IMPACT_GRAY, IMPACT_HIGH, classify_impact
from bot.news.rule_engine import DuplicateDetector, apply_rule_engine


def test_exclusion_fda_conference_gray():
    result = apply_rule_engine("Company to present at FDA conference next month")
    assert result.excluded is True
    assert result.impact_level == IMPACT_GRAY


def test_negation_fda_not_high():
    result = apply_rule_engine("Company received no approval from the FDA this quarter")
    assert result.negated is True
    assert result.impact_level in {IMPACT_GRAY, "low"}


def test_multi_event_fda_and_offering():
    text = (
        "Company announces FDA approval, strategic partnership, "
        "and $10M registered direct offering"
    )
    result = apply_rule_engine(text)
    assert result.impact_level == IMPACT_HIGH
    assert result.primary_event is not None
    assert len(result.secondary_events) >= 1
    assert result.dilution_risk is True


def test_duplicate_detection():
    detector = DuplicateDetector(window_seconds=3600)
    assert not detector.check(symbol="ABCD", headline="FDA approval for drug", catalyst_type="FDA/Biotech")
    assert detector.check(symbol="ABCD", headline="FDA approval for drug", catalyst_type="FDA/Biotech")


def test_confidence_sec_filing():
    result = apply_rule_engine("Company files 8-K regarding FDA approval")
    assert result.confidence >= 90


def test_urgency_future_tense():
    result = apply_rule_engine("Company expects FDA approval in Q3")
    assert result.urgency in {"This Week", "Long Term"}


def test_classify_impact_with_symbol():
    impact = classify_impact(
        "XYZ receives FDA approval",
        symbol="XYZ",
        article_id="test-1",
    )
    assert impact.level == IMPACT_HIGH
    assert impact.confidence is not None
