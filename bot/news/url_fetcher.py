"""Fetch news article text from external URLs (e.g. nuntiobot.com)."""

from __future__ import annotations

import asyncio
import logging
import re
from html import unescape
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

TITLE_PATTERN = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
TITLE_TAG_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
MAIN_TEXT_PATTERN = re.compile(
    r'<div class="main-text"[^>]*>(.*?)</div>\s*(?:</div>|$)',
    re.IGNORECASE | re.DOTALL,
)
CONTENT_CONTAINER_PATTERN = re.compile(
    r'<div class="content-container"[^>]*>(.*?)</div>\s*</body>',
    re.IGNORECASE | re.DOTALL,
)
STYLE_SCRIPT_PATTERN = re.compile(r"<(style|script)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")

GENERIC_TITLES = frozenset({"news article", "nuntiobot", "loading", "just a moment..."})

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
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
        "Origin": origin,
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
    }


def _extract_title(html: str) -> str:
    for pattern in (TITLE_PATTERN, TITLE_TAG_PATTERN):
        match = pattern.search(html)
        if match:
            title = _clean_html(match.group(1))
            if title and title.lower() not in GENERIC_TITLES and len(title) >= 15:
                return title
    return ""


def _extract_body(html: str, title: str) -> str:
    main_match = MAIN_TEXT_PATTERN.search(html)
    if main_match:
        body = _clean_html(main_match.group(1))
        if len(body) >= 50 and not body.startswith("body {"):
            return body[:4000]

    container_match = CONTENT_CONTAINER_PATTERN.search(html)
    if container_match:
        body = _clean_html(container_match.group(1))
        if title and body.startswith(title):
            body = body[len(title) :].strip()
        if len(body) >= 50 and not body.startswith("body {"):
            return body[:4000]

    return title


def _is_weak_article(title: str, body: str) -> bool:
    cleaned_title = title.strip()
    if len(cleaned_title) < 15 or cleaned_title.lower() in GENERIC_TITLES:
        return True
    cleaned_body = body.strip()
    if cleaned_body.startswith("body {") or (cleaned_body and len(cleaned_body) < 30):
        return True
    return False


def _parse_article_html(html: str) -> tuple[str, str]:
    html = STYLE_SCRIPT_PATTERN.sub(" ", html)
    title = _extract_title(html)
    if not title:
        raise UrlFetchError("No article title found on page.")

    body = _extract_body(html, title)
    if not body:
        body = title

    if _is_weak_article(title, body):
        raise UrlFetchError("Article page loaded but headline/content missing.")

    return title, body


async def _fetch_with_aiohttp(url: str) -> tuple[str, str]:
    from aiohttp.resolver import ThreadedResolver

    headers = _request_headers(url)
    connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
    retry_statuses = {403, 429, 503}

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

    return _parse_article_html(html)


def _fetch_with_playwright(url: str) -> tuple[str, str]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=BROWSER_HEADERS["User-Agent"])
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("h1", timeout=20000)
            page.wait_for_timeout(500)
            html = page.content()
        finally:
            browser.close()
    return _parse_article_html(html)


async def fetch_article(url: str) -> tuple[str, str]:
    """Return (title, body text) from a news article URL."""
    last_error: Exception | None = None

    try:
        title, body = await _fetch_with_aiohttp(url)
        logger.info("Fetched article (HTTP): %s", title[:100])
        return title, body
    except UrlFetchError as exc:
        last_error = exc
        if "403" not in str(exc):
            logger.warning("HTTP fetch weak/failed for %s: %s — retrying with Playwright", url, exc)

    if last_error and "403" in str(last_error):
        logger.warning("HTTP 403 for %s — retrying with Playwright", url)
    elif last_error:
        logger.warning("Retrying %s with Playwright after: %s", url, last_error)

    try:
        title, body = await asyncio.to_thread(_fetch_with_playwright, url)
        logger.info("Fetched article (Playwright): %s", title[:100])
        return title, body
    except ImportError:
        raise UrlFetchError(
            f"HTTP fetch failed for {url} and Playwright is not installed"
        ) from None
    except Exception as exc:
        raise UrlFetchError(f"Playwright fetch failed for {url}: {exc}") from exc
