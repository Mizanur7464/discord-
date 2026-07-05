"""SDS-Core-03 v1.11 source traceability tests."""

from bot.news.benzinga import BenzingaArticle, parse_benzinga_article
from bot.news.source_traceability import (
    build_source_traceability,
    detect_source_key,
    score_confidence_from_source,
)


def test_detect_globenewswire_from_url():
    key = detect_source_key(
        url="https://www.globenewswire.com/news-release/2026/example",
        text="Company announces update",
    )
    assert key == "globenewswire"


def test_build_source_traceability_timeline_fields():
    article = BenzingaArticle(
        article_id="99",
        title="FDA approval for lead drug",
        url="https://www.globenewswire.com/news/example",
        original_url="https://www.globenewswire.com/news/example",
        published="2026-04-01T12:41:56Z",
        source_name="GlobeNewswire",
    )
    trace = build_source_traceability(
        article,
        first_detected_iso="2026-04-01T12:42:11Z",
        mirror_url="http://reader.example/99",
    )
    assert trace.source_name == "GlobeNewswire"
    assert trace.quality_stars == 4
    assert "★★★★" in trace.quality_display
    assert trace.original_url.startswith("https://www.globenewswire.com")
    assert trace.published_et.endswith("ET")
    assert trace.first_detected_et.endswith("ET")
    assert trace.mirror_url == "http://reader.example/99"
    assert trace.confidence >= 75


def test_parse_benzinga_source_fields():
    article = parse_benzinga_article(
        {
            "benzinga_id": 1,
            "title": "Test headline",
            "url": "https://www.benzinga.com/example",
            "author": "GlobeNewswire",
            "published": "2026-04-01T10:00:00Z",
        }
    )
    assert article is not None
    assert article.source_name == "GlobeNewswire"


def test_sec_filing_confidence_boost():
    score = score_confidence_from_source(
        "benzinga",
        text="Company files 8-K regarding FDA update",
    )
    assert score >= 90
