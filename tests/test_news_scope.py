from bot.discord_bot.news_embed import build_timeline_news_blocks
from bot.news.benzinga import BenzingaArticle
from bot.news.news_intelligence import classify_impact
from bot.news.news_scope import NEWS_SCOPE_MACRO, classify_news_scope


def test_opec_macro_scope():
    title = "OPEC+ agrees to extend oil production cuts through Q3"
    symbols = ["USO", "SPY", "VGK", "EIS"]
    assert classify_news_scope(title=title, body="", symbols=symbols) == NEWS_SCOPE_MACRO


def test_single_ticker_company_scope():
    assert classify_news_scope(title="KZIA FDA Phase 2 update", symbols=["KZIA"]) == "company"


def test_macro_single_timeline_block():
    article = BenzingaArticle(
        article_id="m1",
        title="OPEC+ extends oil cuts; energy ETFs react",
        body="",
        url="https://example.com",
        published="2026-07-05T14:00:00+00:00",
        symbols=["USO", "SPY", "XLE"],
    )
    impact = classify_impact(article.title)
    symbol_rows = [(s, None, "🇺🇸") for s in article.symbols]
    blocks = build_timeline_news_blocks(
        article,
        symbol_rows=symbol_rows,
        impact=impact,
        news_scope=NEWS_SCOPE_MACRO,
    )
    assert len(blocks) == 1
    assert "Related: USO, SPY, XLE" in blocks[0]
    assert "USO OPEC" not in blocks[0]
