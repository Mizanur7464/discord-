from bot.news.benzinga import BenzingaArticle
from bot.discord_bot.news_embed import build_benzinga_news_line


def test_benzinga_news_line_spm_mc_style():
    article = BenzingaArticle(
        article_id="1",
        title="VRAX - Virax Biolabs Group Limited Announces 1-for-25 Share Consolidation",
        url="https://www.benzinga.com/news/example",
        symbols=["VRAX"],
    )
    line = build_benzinga_news_line(article, company_name="Virax Biolabs Group Limited")
    assert "**VRAX** (Virax Biolabs Group Limited):" in line
    assert "`1-for-25 Share Consolidation`" in line or "`Announces`" in line
    assert " - [Link](" in line
    assert "`2.3 M`" not in line
    assert "🇨🇳" not in line


def test_benzinga_news_line_oris_style():
    article = BenzingaArticle(
        article_id="2",
        title="ORIS - Oriental Rise Provides Update Regarding Nasdaq Delisting Decision",
        url="https://www.benzinga.com/news/example",
        symbols=["ORIS"],
    )
    line = build_benzinga_news_line(article, company_name="Oriental Rise")
    assert "**ORIS** (Oriental Rise):" in line
    assert "`Provides Update`" in line
    assert "`Delisting`" in line
