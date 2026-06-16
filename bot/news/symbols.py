"""Extract US stock ticker symbols from news text."""

from __future__ import annotations

import re

EXCHANGE_TICKER = re.compile(
    r"\((?:NYSE|NASDAQ|AMEX|OTC(?:QB|QX)?):\s*([A-Z]{1,5})\)",
    re.IGNORECASE,
)
PLAIN_EXCHANGE_TICKER = re.compile(
    r"(?:NYSE|NASDAQ|AMEX|OTC(?:QB|QX)?):\s*([A-Z]{1,5})\b",
    re.IGNORECASE,
)
CASH_TAG = re.compile(r"\$([A-Z]{1,5})\b")
# NuntioBot header line e.g. "79.8 M 🇺🇸 GPUS"
NUNTIO_HEADER = re.compile(
    r"^[\d.,]+\s*[MKBkmb]?\s*(?:[\U0001F1E6-\U0001F1FF]{2}\s*)?(?:\$)?([A-Z]{1,5})\b",
    re.MULTILINE,
)
NUNTIO_FIRST_LINE = re.compile(
    r"^[\d.,]+\s*[MKBkmb]?\s*(?:[\U0001F1E6-\U0001F1FF]{2}\s*)?(?:\$)?([A-Z]{1,5})\b"
)


def extract_stock_symbol(text: str) -> str:
    """Return the first ticker found in text, or empty string."""
    for line in text.strip().split("\n"):
        nuntio = NUNTIO_FIRST_LINE.match(line.strip())
        if nuntio:
            return nuntio.group(1).upper()

    for pattern in (EXCHANGE_TICKER, PLAIN_EXCHANGE_TICKER, CASH_TAG):
        match = pattern.search(text)
        if match:
            return match.group(1).upper()
    return ""


def split_news_blocks(text: str) -> list[str]:
    """Split a multi-ticker NuntioBot post into per-symbol chunks."""
    text = text.strip()
    if not text:
        return []

    matches = list(NUNTIO_HEADER.finditer(text))
    if len(matches) <= 1:
        return [text]

    blocks: list[str] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if block:
            blocks.append(block)
    return blocks
