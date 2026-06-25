from bot.news.benzinga import BenzingaArticle
from bot.discord_bot.news_embed import build_benzinga_news_line, build_benzinga_news_post


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


def test_benzinga_news_post_multi_symbol_copy():
    article = BenzingaArticle(
        article_id="2",
        title="L'OFFICIEL AMTD IDEA Sets 2026 Launch for L'OFFICIEL Taiwan",
        url="https://www.benzinga.com/news/example",
        symbols=["AMTD", "HKD", "TGE"],
    )
    post = build_benzinga_news_post(
        article,
        symbol_rows=[
            ("AMTD", 42_500_000, "🇫🇷"),
            ("HKD", 117_000_000, "🇺🇸"),
            ("TGE", 9_100_000, "🇺🇸"),
        ],
    )
    lines = post.split("\n")
    assert len(lines) == 3
    assert "**AMTD**" in lines[0]
    assert "**HKD**" in lines[1]
    assert "**TGE**" in lines[2]
    assert all(" - [Link](" in line for line in lines)
