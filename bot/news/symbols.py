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
URL_PATTERN = re.compile(r"https?://\S+")
WHITESPACE = re.compile(r"\s+")

# Classic NuntioBot: "79.8 M 🇺🇸 GPUS"
NUNTIO_FIRST_LINE = re.compile(
    r"^[`\s]*[\d.,]+\s*[MKBkmb]?\s*[`\s]*"
    r"(?:[\U0001F1E6-\U0001F1FF]{2}\s*|:flag_[a-z]{2}:\s*)?"
    r"(?:\$|\*{0,2})?([A-Z]{1,5})\*{0,2}\b"
)

# NuntioBot / Discord forwarded lines, e.g.:
# ` 7.8 M` :flag_cn: **DTSS** : Company headline...
# 117 M 🇺🇸 GLND
NUNTIO_TICKER = re.compile(
    r"[\d.,]+\s*[MKBkmb]?\s*[`\s]*"
    r"(?:[\U0001F1E6-\U0001F1FF]{2}\s*|:flag_[a-z]{2}:\s*)"
    r"[\s\S]{0,40}?"
    r"\*{0,2}([A-Z]{1,5})\*{0,2}\b"
)

# Bold ticker fallback: **DTSS** (only when line also has market cap or flag)
BOLD_TICKER_LINE = re.compile(
    r"(?:[\d.,]+\s*[MKBkmb]?|:flag_[a-z]{2}:|[\U0001F1E6-\U0001F1FF]{2}).*?\*\*([A-Z]{1,5})\*\*",
    re.DOTALL,
)

TICKER_HEADLINE_SPLIT = re.compile(
    r"\*{0,2}[A-Z]{1,5}\*{0,2}\s*(?:[:\-–—|]\s*)(.+)",
    re.DOTALL,
)

NUNTIO_HEADER = NUNTIO_TICKER


def is_nuntio_header_line(line: str) -> bool:
    """True if line looks like a NuntioBot ticker header row."""
    line = line.strip()
    if not line:
        return False
    return bool(NUNTIO_FIRST_LINE.match(line) or NUNTIO_TICKER.search(line) or BOLD_TICKER_LINE.search(line))


def _clean_headline_text(text: str) -> str:
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = URL_PATTERN.sub("", text)
    return WHITESPACE.sub(" ", text).strip()


def _line_is_ticker_only(line: str) -> bool:
    line = _clean_headline_text(line)
    if not line or len(line) > 40:
        return False
    symbol = _ticker_from_line(line)
    if not symbol:
        return False
    remainder = re.sub(
        r"[\d.,]+\s*[MKBkmb]?|[\U0001F1E6-\U0001F1FF]{2}|:flag_[a-z]{2}:|\*{0,2}[A-Z]{1,5}\*{0,2}",
        "",
        line,
        flags=re.IGNORECASE,
    )
    remainder = WHITESPACE.sub("", remainder)
    return len(remainder) <= 2


def extract_nuntio_headline(block: str) -> str:
    """Extract the news headline from a NuntioBot Discord block."""
    block = block.strip()
    if not block:
        return ""

    without_urls = URL_PATTERN.sub("", block).strip()

    lines = [line.strip() for line in without_urls.split("\n") if line.strip()]
    for i, line in enumerate(lines):
        if _line_is_ticker_only(line):
            if i + 1 < len(lines):
                next_line = _clean_headline_text(lines[i + 1])
                if next_line and len(next_line) >= 8:
                    return next_line
            continue
        if is_nuntio_header_line(line):
            if i + 1 < len(lines):
                next_line = _clean_headline_text(lines[i + 1])
                if next_line and len(next_line) >= 8:
                    return next_line
            continue
        cleaned = _clean_headline_text(line)
        if len(cleaned) >= 8 and not _line_is_ticker_only(cleaned):
            return cleaned

    one_line = WHITESPACE.sub(" ", without_urls.replace("\n", " ")).strip()

    split_match = TICKER_HEADLINE_SPLIT.search(one_line)
    if split_match:
        headline = _clean_headline_text(split_match.group(1))
        if len(headline) >= 8:
            return headline

    for pattern in (NUNTIO_TICKER, BOLD_TICKER_LINE, NUNTIO_FIRST_LINE):
        match = pattern.search(without_urls)
        if match:
            rest = without_urls[match.end() :].strip()
            rest = rest.lstrip(":|-–—| ").strip()
            rest = _clean_headline_text(rest)
            if len(rest) >= 8:
                return rest

    return ""


def is_weak_headline(headline: str, symbol: str = "") -> bool:
    """True when text is too short for reliable AI classification."""
    text = _clean_headline_text(headline)
    if len(text) < 12:
        return True
    if symbol and text.upper() == symbol.upper():
        return True
    if text.lower() in {"news article", "nuntiobot", "loading", "just a moment..."}:
        return True
    if _line_is_ticker_only(text):
        return True
    return False


def _ticker_from_line(line: str) -> str:
    line = line.strip()
    for pattern in (NUNTIO_FIRST_LINE, NUNTIO_TICKER, BOLD_TICKER_LINE):
        match = pattern.search(line) if pattern is not NUNTIO_FIRST_LINE else pattern.match(line)
        if match:
            return match.group(1).upper()
    return ""


def extract_stock_symbol(text: str) -> str:
    """Return the first ticker found in text, or empty string."""
    for line in text.strip().split("\n"):
        symbol = _ticker_from_line(line)
        if symbol:
            return symbol

    match = NUNTIO_TICKER.search(text)
    if match:
        return match.group(1).upper()

    match = BOLD_TICKER_LINE.search(text)
    if match:
        return match.group(1).upper()

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

    matches = list(NUNTIO_TICKER.finditer(text))
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
