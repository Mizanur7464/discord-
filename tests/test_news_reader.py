from bot.discord_bot.news_embed import build_benzinga_news_post
from bot.news.benzinga import BenzingaArticle
from bot.news.reader_html import render_article_page
from bot.news.reader_store import NewsReaderStore
from bot.news.reader_urls import reader_article_url


def test_reader_article_url():
    assert reader_article_url("http://news.example.com", "44577082") == (
        "http://news.example.com/n/44577082"
    )


def test_news_embed_uses_reader_link_for_multi_symbol():
    article = BenzingaArticle(
        article_id="44577082",
        title="Shared headline",
        url="https://www.benzinga.com/news/example",
        symbols=["AMTD", "HKD"],
    )
    post = build_benzinga_news_post(
        article,
        symbol_rows=[
            ("AMTD", 42_500_000, "🇫🇷"),
            ("HKD", 117_000_000, "🇺🇸"),
        ],
        reader_base_url="http://news.example.com",
    )
    assert "http://news.example.com/n/44577082" in post
    assert "benzinga.com/quote/" not in post


def test_reader_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.news.reader_store.STORE_DIR", tmp_path)
    store = NewsReaderStore(max_articles=10)
    article = BenzingaArticle(
        article_id="99",
        title="Test headline",
        body="<p>Full article body</p>",
        url="https://www.benzinga.com/news/99",
        symbols=["AAPL"],
        published="2026-06-25T17:52:00Z",
    )
    store.save(article)
    loaded = store.get("99")
    assert loaded is not None
    assert loaded.title == "Test headline"
    assert loaded.body == "<p>Full article body</p>"


def test_render_article_page_includes_body():
    article = BenzingaArticle(
        article_id="1",
        title="L'OFFICIEL AMTD IDEA Sets 2026 Launch",
        body="<p>Launch details here.</p>",
        symbols=["AMTD"],
        published="2026-06-25T17:52:00Z",
    )
    html = render_article_page(article)
    assert "L&#x27;OFFICIEL AMTD IDEA Sets 2026 Launch" in html
    assert "Launch details here." in html
    assert "AMTD" in html
