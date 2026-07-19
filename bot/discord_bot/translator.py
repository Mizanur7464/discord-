"""Auto-translate non-English chat messages to plain English (no embeds)."""

from __future__ import annotations

import json
import logging
import re

import aiohttp

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

# Likely needs translation when non-Latin / CJK is present.
_NON_LATIN = re.compile(
    r"[\u0400-\u04FF\u0600-\u06FF\u0900-\u097F\u3040-\u30FF\u3400-\u9FFF"
    r"\uAC00-\uD7AF\u0E00-\u0E7F]"
)
_URL_ONLY = re.compile(r"https?://\S+")
_EMOJI_ONLY = re.compile(
    r"^[\s\d\W_]+$",
    re.UNICODE,
)

SYSTEM_PROMPT = """You translate Discord chat messages to English.

Return JSON only:
{"skip":true}  — if the text is already English, is only emojis/urls/names, or has nothing useful to translate
{"skip":false,"translation":"..."}  — natural English only, no quotes, no flags, no commentary

Keep the translation short and natural. Do not add prefixes."""


def looks_non_english(text: str) -> bool:
    """True when text has non-Latin scripts (e.g. Chinese) that need translation."""
    return bool(_NON_LATIN.search(text.strip()))


def should_attempt_translate(text: str) -> bool:
    cleaned = (text or "").strip()
    if len(cleaned) < 2:
        return False
    if cleaned.startswith(("!", "/", ".")):
        return False
    without_urls = _URL_ONLY.sub("", cleaned).strip()
    if not without_urls:
        return False
    if not looks_non_english(cleaned):
        return False
    if _EMOJI_ONLY.match(without_urls) and not _NON_LATIN.search(without_urls):
        return False
    return True


async def translate_to_english(
    text: str,
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    timeout: float = 8.0,
) -> str | None:
    """Return English translation, or None if skip / failure."""
    text = text.strip()
    if not text or not api_key:
        return None
    if not should_attempt_translate(text):
        return None

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 120,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text[:1500]},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    from aiohttp.resolver import ThreadedResolver

    connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
    try:
        async with aiohttp.ClientSession(timeout=client_timeout, connector=connector) as session:
            async with session.post(OPENAI_CHAT_URL, json=payload, headers=headers) as resp:
                body = await resp.text()
                if resp.status != 200:
                    logger.warning("Translator HTTP %s: %s", resp.status, body[:160])
                    return None
                data = json.loads(body)
                content = data["choices"][0]["message"]["content"].strip()
                parsed = json.loads(content)
                if parsed.get("skip", False):
                    return None
                translation = str(parsed.get("translation", "")).strip()
                if not translation or translation.lower() == text.lower():
                    return None
                return translation[:500]
    except (aiohttp.ClientError, KeyError, json.JSONDecodeError, IndexError) as exc:
        logger.warning("Translator failed: %s", exc)
        return None
