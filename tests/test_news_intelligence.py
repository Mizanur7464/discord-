from bot.news.news_intelligence import (
    IMPACT_GRAY,
    IMPACT_HIGH,
    IMPACT_LOW,
    IMPACT_MEDIUM,
    SymbolNewsContext,
    build_priority_line,
    build_trader_context_line,
    classify_impact,
    is_options_news,
    resolve_news_routing,
)


def test_classify_high_impact_fda():
    impact = classify_impact("Company receives FDA approval for lead drug")
    assert impact.level == IMPACT_HIGH
    assert impact.post_main is True
    assert impact.skip_entirely is False


def test_classify_gray_routine_skipped():
    impact = classify_impact("Company provides market commentary on industry outlook")
    assert impact.level == IMPACT_GRAY
    assert impact.skip_entirely is True


def test_classify_medium_partnership():
    impact = classify_impact("Company announces strategic partnership with major retailer")
    assert impact.level == IMPACT_MEDIUM


def test_classify_low_appointment():
    impact = classify_impact("Company announces appointment of new board member")
    assert impact.level == IMPACT_LOW
    assert impact.post_main is False
    assert impact.post_cap is True


def test_is_options_news():
    assert is_options_news(title="Unusual options activity detected in XYZ")
    assert not is_options_news(title="FDA approves drug", body="Phase 3 success")


def test_resolve_crypto_exclusive():
    impact = classify_impact("Bitcoin surges on ETF inflows")
    post_main, post_cap, skip = resolve_news_routing(
        title="Bitcoin surges",
        body="",
        symbols=[],
        smallest_market_cap_usd=None,
        max_low_cap_usd=3_000_000_000,
        is_crypto=True,
        impact=impact,
        crypto_exclusive=True,
    )
    assert post_main is False
    assert post_cap is False
    assert skip is False


def test_resolve_large_cap_skipped():
    impact = classify_impact("Apple announces new product launch partnership")
    post_main, post_cap, skip = resolve_news_routing(
        title=impact.category,
        body="",
        symbols=["AAPL"],
        smallest_market_cap_usd=3_500_000_000_000,
        max_low_cap_usd=3_000_000_000,
        is_crypto=False,
        impact=impact,
    )
    assert skip is True
    assert post_main is False


def test_resolve_gray_skipped_legacy():
    impact = classify_impact("Company reiterates prior guidance in podcast appearance")
    _, _, skip = resolve_news_routing(
        title="update",
        body="",
        symbols=["ABCD"],
        smallest_market_cap_usd=50_000_000,
        max_low_cap_usd=3_000_000_000,
        is_crypto=False,
        impact=impact,
        intelligence_mode=False,
    )
    assert skip is True


def test_resolve_gray_intelligence_not_skipped():
    impact = classify_impact("Company reiterates prior guidance in podcast appearance")
    post_main, post_cap, skip = resolve_news_routing(
        title="update",
        body="",
        symbols=["ABCD"],
        smallest_market_cap_usd=50_000_000,
        max_low_cap_usd=3_000_000_000,
        is_crypto=False,
        impact=impact,
        intelligence_mode=True,
    )
    assert skip is False
    assert post_main is False
    assert post_cap is False


def test_build_trader_context_line():
    ctx = SymbolNewsContext(
        symbol="ABCD",
        float_shares=12_500_000,
        market_cap_usd=85_000_000,
        sector="Biotechnology",
        rvol=4.2,
        is_runner=True,
        runner_stars=2,
    )
    line = build_trader_context_line(ctx, catalyst="FDA / Biotech Catalyst")
    assert "MC $85M" in line
    assert "Float 12.5M" in line
    assert "RVOL 4.2x" in line
    assert "★★ Runner" in line
    assert "Biotechnology" in line


def test_build_priority_line():
    impact = classify_impact("FDA approval for lead candidate")
    line = build_priority_line(impact=impact, ai_reason="breakthrough therapy designation")
    assert line.startswith("🔴")
    assert "breakthrough" in line.lower()
