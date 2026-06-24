from bot.news.benzinga import BenzingaArticle
from bot.discord_bot.news_embed import build_benzinga_news_post


def test_benzinga_news_post_has_time_and_no_url_in_embed():
    article = BenzingaArticle(
        article_id="1",
        title="Comparing Microsoft With Industry Competitors",
        url="https://www.benzinga.com/news/example",
        symbols=["MSFT"],
        published="2026-06-19T16:32:00-04:00",
    )
    embed, view = build_benzinga_news_post(article)
    assert "04:32:00 PM ET" in embed.description
    assert "MSFT" in embed.description
    assert "benzinga.com" not in (embed.description or "")
    assert view is not None
    assert len(view.children) == 1
