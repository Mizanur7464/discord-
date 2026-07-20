"""Auto-translate Chinese → English in chat (plain text reply, no embeds)."""

from __future__ import annotations

import json
import logging
import re

import aiohttp

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

_CJK = re.compile(r"[\u3400-\u9FFF]")
_HIRAGANA_KATAKANA = re.compile(r"[\u3040-\u30FF]")
_HANGUL = re.compile(r"[\uAC00-\uD7AF]")
_URL_ONLY = re.compile(r"https?://\S+")
_EMOJI_OR_PUNCT = re.compile(r"^[\s\d\W_]+$", re.UNICODE)

DIR_CN_TO_EN = "cn_to_en"

SYSTEM_PROMPT = """You translate Discord chat messages from Chinese to English.

Return JSON only:
{"skip":true}  — if not Chinese, emojis/urls only, already English, or nonsense
{"skip":false,"translation":"..."}  — natural English only, no quotes, no flags, no prefixes

Keep it short and natural."""


def looks_chinese(text: str) -> bool:
    """Chinese characters present, not clearly Japanese/Korean."""
    if not _CJK.search(text):
        return False
    if _HIRAGANA_KATAKANA.search(text) or _HANGUL.search(text):
        return False
    return True


def should_attempt_translate(text: str) -> bool:
    cleaned = (text or "").strip()
    if len(cleaned) < 2:
        return False
    if cleaned.startswith(("!", "/", ".")):
        return False
    without_urls = _URL_ONLY.sub("", cleaned).strip()
    if not without_urls:
        return False
    if _EMOJI_OR_PUNCT.match(without_urls) and not _CJK.search(without_urls):
        return False
    return looks_chinese(cleaned)


async def translate_message(
    text: str,
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    timeout: float = 8.0,
) -> str | None:
    """Translate Chinese → English. Returns plain text or None."""
    text = text.strip()
    if not text or not api_key:
        return None
    if not should_attempt_translate(text):
        return None

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 160,
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


async def translate_to_english(
    text: str,
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    timeout: float = 8.0,
) -> str | None:
    return await translate_message(text, api_key=api_key, model=model, timeout=timeout)
