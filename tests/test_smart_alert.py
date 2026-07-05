"""Phase 4 — Smart Alert tests."""

from bot.news.smart_alert import evaluate_smart_alert
from bot.news.news_intelligence import SymbolNewsContext, classify_impact


def test_smart_alert_aligned():
    impact = classify_impact("XYZ receives FDA approval", symbol="XYZ", article_id="t2")
    ctx = SymbolNewsContext(
        symbol="ABC",
        rvol=5.0,
        is_runner=True,
        premarket_turnover_usd=400_000,
    )
    assert evaluate_smart_alert(impact, ctx, crowd_score=60) is True


def test_smart_alert_low_crowd():
    impact = classify_impact("XYZ receives FDA approval", symbol="XYZ", article_id="t3")
    assert evaluate_smart_alert(impact, None, crowd_score=30) is False
