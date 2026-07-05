from bot.discord_bot.news_embed import _format_published_seconds_et, build_timeline_news_block
from bot.news.benzinga import BenzingaArticle
from bot.news.news_intelligence import SymbolNewsContext, classify_impact


def _article(**kwargs) -> BenzingaArticle:
    defaults = {
        "article_id": "1",
        "title": "KZIA FDA Phase 2 trial update",
        "body": "",
        "url": "https://example.com",
        "published": "2026-07-05T12:42:11+00:00",
        "symbols": ["KZIA"],
    }
    defaults.update(kwargs)
    return BenzingaArticle(**defaults)


def test_timeline_format_full_fields():
    article = _article()
    impact = classify_impact(article.title)
    ctx = SymbolNewsContext(
        symbol="KZIA",
        float_shares=8_100_000,
        market_cap_usd=42_000_000,
        country_flag="🇦🇺",
        sector="Biotechnology",
        exchange="NASDAQ",
        rvol=32.0,
        peak_rvol=48.0,
        peak_rvol_at="09:12",
        price=1.42,
        session_change_pct=68.0,
        session_turnover_usd=480_000,
        is_runner=True,
    )
    block = build_timeline_news_block(
        article,
        symbol="KZIA",
        impact=impact,
        context=ctx,
        sentiment="bullish",
        dilution_risk=False,
    )
    assert "— KZIA" in block
    assert "NASDAQ" in block
    assert "Ind: Biotechnology" in block
    assert "MC: 42M" in block
    assert "F: 8.1M" in block
    assert "Impact:" in block
    assert "Sent: Bullish" in block
    assert "Px: 1.42" in block
    assert "Session TO: 480k" in block
    assert "RVOL@News: 32x" in block
    assert "Peak RVOL: 48x @09:12" in block
    assert "1D: +68%" in block
    assert "Prev Run: Yes" in block
    assert "Dilution: No" in block
    assert "Action:" in block
    assert "[Link]" in block


def test_timeline_published_seconds_format():
    ts = _format_published_seconds_et("2026-07-05T12:42:11+00:00")
    assert len(ts.split(":")) == 3
