from bot.news.benzinga import (
    _news_items_from_payload,
    fetch_recent_news,
    parse_benzinga_article,
    parse_benzinga_payload,
)


def test_massive_results_payload_parsing():
    payload = {
        "status": "OK",
        "results": [
            {
                "benzinga_id": 60088950,
                "title": "Aditxt (ADTX) Stock Sinks 20% After-Hours",
                "url": "https://www.benzinga.com/markets/equities/26/06/60088950/example",
                "teaser": "Aditxt stock falls after Nasdaq delisting decision.",
                "tickers": ["ADTX"],
                "published": "2026-06-25T05:48:50Z",
            }
        ],
    }
    items = _news_items_from_payload(payload)
    assert len(items) == 1
    article = parse_benzinga_article(items[0])
    assert article is not None
    assert article.article_id == "60088950"
    assert article.symbols == ["ADTX"]
    assert "Aditxt" in article.title


def test_massive_catalyst_payload():
    items = [
        {
            "benzinga_id": 1,
            "title": "FDA approval lifts shares",
            "url": "https://www.benzinga.com/example",
        }
    ]
    catalyst = parse_benzinga_payload("XYZ", items)
    assert catalyst is not None
    assert catalyst.is_bullish_catalyst is True
    assert "fda" in catalyst.keywords


def test_fetch_recent_news_massive_live():
    from bot.utils.config import load_settings

    settings = load_settings()
    if not settings.benzinga_api_key:
        return
    articles = fetch_recent_news(
        settings.benzinga_api_key,
        page_size=2,
        provider=settings.benzinga_news_provider,
    )
    assert articles
    assert articles[0].title
