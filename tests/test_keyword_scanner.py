from bot.news.keyword_scanner import normalize_news_text, scan_keywords
from bot.news.news_intelligence import IMPACT_GRAY, IMPACT_HIGH, IMPACT_MEDIUM, classify_impact, is_dilution_news


def test_alias_normalization_fda():
    text = normalize_news_text("Company receives FDA grants approval for lead drug")
    assert "fda approval" in text


def test_scan_fda_approval_high():
    result = scan_keywords("XYZ receives FDA approval for lead candidate")
    assert result.impact_level == IMPACT_HIGH
    assert result.catalyst_type == "FDA/Biotech"
    assert "FDA" in result.catalyst_tags or "Biotech" in result.catalyst_tags


def test_scan_dilution_rule_pipe():
    result = scan_keywords("Company announces PIPE financing with institutional investors")
    assert result.impact_level == IMPACT_HIGH
    assert result.dilution_risk is True
    assert result.financing_high_impact is True


def test_scan_partnership_medium():
    result = scan_keywords("Company announces strategic partnership with retailer")
    assert result.impact_level == IMPACT_MEDIUM


def test_scan_ambiguous_fda_gray():
    result = scan_keywords("Management discusses FDA outlook at conference")
    assert result.impact_level == IMPACT_GRAY
    assert result.ambiguous_root is True


def test_scan_gray_routine():
    result = scan_keywords("Company reiterates prior guidance in podcast")
    assert result.impact_level == IMPACT_GRAY


def test_classify_impact_uses_scanner():
    impact = classify_impact("Company receives FDA approval")
    assert impact.level == IMPACT_HIGH
    assert impact.catalyst_type == "FDA/Biotech"


def test_is_dilution_news_sepa():
    assert is_dilution_news("Enters Standby Equity Purchase Agreement with Lincoln Park")
