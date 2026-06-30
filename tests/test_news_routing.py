from bot.news.news_routing import is_crypto_news


def test_crypto_news_by_keyword():
    assert is_crypto_news(title="Bitcoin, Ethereum and XRP are trading higher")


def test_crypto_news_by_miner_symbol():
    assert is_crypto_news(title="Company update", symbols=["BMNR"])


def test_non_crypto_news():
    assert not is_crypto_news(title="FDA approves new drug", symbols=["ABCD"])
