"""Fetch news article text from external URLs (e.g. nuntiobot.com)."""

from __future__ import annotations

import asyncio
import re
from html import unescape
from urllib.parse import urlparse

import aiohttp

TITLE_PATTERN = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class UrlFetchError(Exception):
    pass


def is_allowed_url(url: str, allowed_domains: list[str]) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(host == domain.lower() or host.endswith(f".{domain.lower()}") for domain in allowed_domains)


def extract_urls(text: str) -> list[str]:
    pattern = re.compile(r"https?://[^\s<>\"']+")
    return pattern.findall(text)


def _clean_html(raw: str) -> str:
    text = TAG_PATTERN.sub(" ", raw)
    text = unescape(text)
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def _request_headers(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return {
        **BROWSER_HEADERS,
        "Referer": f"{origin}/",
    }


def _parse_article_html(html: str) -> tuple[str, str]:
    title_match = TITLE_PATTERN.search(html)
    title = _clean_html(title_match.group(1)) if title_match else "News Article"

    body = _clean_html(html)
    if title and body.startswith(title):
        body = body[len(title) :].strip()

    if len(body) > 4000:
        body = body[:4000]

    if not body:
        raise UrlFetchError("No article content found on page.")

    return title, body


async def fetch_article(url: str) -> tuple[str, str]:
    """Return (title, body text) from a news article URL."""
    from aiohttp.resolver import ThreadedResolver

    headers = _request_headers(url)
    connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
    retry_statuses = {403, 429, 503}

    try:
        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            html = ""
            for attempt in range(2):
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                    if response.status == 200:
                        html = await response.text()
                        break
                    if response.status in retry_statuses and attempt == 0:
                        await asyncio.sleep(0.75)
                        continue
                    raise UrlFetchError(f"HTTP {response.status} for {url}")
            else:
                raise UrlFetchError(f"HTTP error for {url}")
    except aiohttp.ClientError as exc:
        raise UrlFetchError(f"Failed to fetch URL: {exc}") from exc

    return _parse_article_html(html)
