from bot.news.benzinga import BenzingaArticle
from bot.discord_bot.news_embed import build_benzinga_news_line


def test_benzinga_news_line_nuntio_style():
    article = BenzingaArticle(
        article_id="1",
        title="ORIS - Oriental Rise Provides Update Regarding Nasdaq Delisting Decision",
        url="https://www.benzinga.com/news/example",
        symbols=["ORIS"],
    )
    line = build_benzinga_news_line(
        article,
        float_shares=2_300_000,
        company_name="Oriental Rise",
        country_flag="🇨🇳",
    )
    assert "`2.3 M`" in line
    assert "🇨🇳" in line
    assert "**ORIS**: Oriental Rise" in line
    assert "`Provides Update`" in line
    assert "`Delisting`" in line
    assert "[Link](https://www.benzinga.com/news/example)" in line
