"""Route Benzinga articles into topic-specific Discord channels."""

from __future__ import annotations

import re

CRYPTO_KEYWORDS = (
    "bitcoin",
    "ethereum",
    "crypto",
    "cryptocurrency",
    "blockchain",
    "defi",
    "nft",
    "xrp",
    "ripple",
    "solana",
    "dogecoin",
    "litecoin",
    "binance",
    "coinbase",
    "stablecoin",
    "web3",
    "btc",
    "eth",
    "digital asset",
    "digital currency",
)

# Crypto miners, ETFs, and brokers — buyer treats these as crypto news.
CRYPTO_EQUITY_SYMBOLS = frozenset(
    {
        "ARBK",
        "BITF",
        "BITO",
        "BMNR",
        "BTBT",
        "CIFR",
        "CLSK",
        "COIN",
        "ETHE",
        "GBTC",
        "HUT",
        "IBIT",
        "MARA",
        "MSTR",
        "RIOT",
        "WULF",
    }
)

_CRYPTO_KEYWORD_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in CRYPTO_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def is_crypto_news(
    *,
    title: str = "",
    body: str = "",
    symbols: list[str] | None = None,
) -> bool:
    text = f"{title}\n{body}"
    if _CRYPTO_KEYWORD_PATTERN.search(text):
        return True
    sym_set = {str(symbol).upper() for symbol in (symbols or []) if symbol}
    return bool(sym_set & CRYPTO_EQUITY_SYMBOLS)
