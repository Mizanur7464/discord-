from bot.news.benzinga import BenzingaArticle, parse_benzinga_article
from bot.discord_bot.news_embed import (
    build_ai_news_line,
    build_benzinga_news_blocks,
    build_benzinga_news_line,
    build_benzinga_news_post,
)


def test_build_ai_news_line_traffic_light():
    assert build_ai_news_line(sentiment="bullish", reason="strong beat", category="Earnings") == (
        "🟢 AI: Earnings — strong beat"
    )
    assert build_ai_news_line(sentiment="neutral", reason="minor update", category="").startswith("🟡 AI:")
    assert build_ai_news_line(sentiment="ignored", reason="no catalyst", category="No Clear Catalyst").startswith(
        "🔴 AI:"
    )


def test_benzinga_news_line_nuntio_style():
    article = BenzingaArticle(
        article_id="1",
        title="AMTD - L'OFFICIEL AMTD IDEA Sets 2026 Launch for L'OFFICIEL Taiwan",
        url="https://www.benzinga.com/news/example",
        symbols=["AMTD"],
    )
    line = build_benzinga_news_line(
        article,
        symbol="AMTD",
        float_shares=42_500_000,
        country_flag="🇫🇷",
    )
    assert "`42.5 M`" in line
    assert "🇫🇷" in line
    assert "**AMTD**" in line
    assert "L'OFFICIEL AMTD IDEA" in line
    assert " - [Link](" in line
    assert "(AMTD)" not in line


def test_benzinga_news_line_decodes_html_entities_and_timestamp_on_top():
    article = BenzingaArticle(
        article_id="3",
        title="L&#39;OFFICIEL AMTD IDEA Sets 2026 Launch",
        url="https://www.benzinga.com/news/example",
        symbols=["AMTD"],
        published="2026-06-25T17:52:00Z",
    )
    line = build_benzinga_news_line(
        article,
        symbol="AMTD",
        float_shares=42_500_000,
        country_flag="🇫🇷",
    )
    assert line.startswith("**")
    assert "ET**\n" in line
    assert " | " not in line.split("\n", 1)[0]
    assert "L'OFFICIEL" in line
    assert "&#39;" not in line

    parsed = parse_benzinga_article({"benzinga_id": 1, "title": "L&#39;OFFICIEL"})
    assert parsed is not None
    assert parsed.title == "L'OFFICIEL"


def test_benzinga_news_post_multi_symbol_spacing():
    article = BenzingaArticle(
        article_id="2",
        title="L'OFFICIEL AMTD IDEA Sets 2026 Launch for L'OFFICIEL Taiwan",
        url="https://www.benzinga.com/news/example",
        symbols=["AMTD", "HKD", "TGE"],
    )
    rows = [
        ("AMTD", 42_500_000, "🇫🇷"),
        ("HKD", 117_000_000, "🇺🇸"),
        ("TGE", 9_100_000, "🇺🇸"),
    ]
    blocks = build_benzinga_news_blocks(article, symbol_rows=rows)
    assert len(blocks) == 3
    post = build_benzinga_news_post(article, symbol_rows=rows)
    assert post.count("\n\n") == 2
    assert "**AMTD**" in blocks[0]
    assert "**HKD**" in blocks[1]
    assert "**TGE**" in blocks[2]
    assert " - [Link](https://www.benzinga.com/quote/AMTD)" in blocks[0]
    assert " - [Link](https://www.benzinga.com/quote/HKD)" in blocks[1]
    assert " - [Link](https://www.benzinga.com/quote/TGE)" in blocks[2]
