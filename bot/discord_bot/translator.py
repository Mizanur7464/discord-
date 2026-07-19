"""Auto-translate Chinese ↔ English chat (plain text reply, no embeds)."""

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
_LATIN_LETTERS = re.compile(r"[A-Za-z]")
_EMOJI_OR_PUNCT = re.compile(r"^[\s\d\W_]+$", re.UNICODE)

DIR_TO_EN = "to_en"
DIR_EN_TO_ZH = "en_to_zh"
# Keep alias used by older code/tests
DIR_ZH_TO_EN = DIR_TO_EN

SYSTEM_PROMPT = """You translate Discord chat messages.

Direction is given by the user message.
Return JSON only:
{"skip":true}  — if nothing useful to translate (emojis/urls only, already target language, nonsense)
{"skip":false,"translation":"..."}  — natural translation only, no quotes, no flags, no prefixes, no commentary

Keep it short and natural."""


def looks_japanese(text: str) -> bool:
    return bool(_HIRAGANA_KATAKANA.search(text))


def looks_korean(text: str) -> bool:
    return bool(_HANGUL.search(text))


def looks_chinese(text: str) -> bool:
    """Chinese characters present, and not clearly Japanese/Korean."""
    if not _CJK.search(text):
        return False
    if _HIRAGANA_KATAKANA.search(text) or _HANGUL.search(text):
        return False
    return True


def looks_english(text: str) -> bool:
    """Latin English chat (skip tiny filler)."""
    if _CJK.search(text) or _HIRAGANA_KATAKANA.search(text) or _HANGUL.search(text):
        return False
    letters = _LATIN_LETTERS.findall(text)
    return len(letters) >= 8


def looks_non_english(text: str) -> bool:
    """True for Chinese/Japanese/Korean text that should translate to English."""
    return looks_chinese(text) or looks_japanese(text) or looks_korean(text)


def detect_direction(text: str) -> str | None:
    cleaned = (text or "").strip()
    if len(cleaned) < 2:
        return None
    if cleaned.startswith(("!", "/", ".")):
        return None
    without_urls = _URL_ONLY.sub("", cleaned).strip()
    if not without_urls:
        return None
    if _EMOJI_OR_PUNCT.match(without_urls) and not (
        _CJK.search(without_urls) or _HIRAGANA_KATAKANA.search(without_urls) or _HANGUL.search(without_urls)
    ):
        return None
    # Asian languages → English; English → Chinese
    if looks_japanese(cleaned) or looks_korean(cleaned) or looks_chinese(cleaned):
        return DIR_ZH_TO_EN  # reuse: any Asian → English
    if looks_english(cleaned):
        return DIR_EN_TO_ZH
    return None


def should_attempt_translate(text: str) -> bool:
    return detect_direction(text) is not None


async def translate_message(
    text: str,
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    timeout: float = 8.0,
) -> str | None:
    """Translate Chinese→English or English→Chinese. Returns plain text or None."""
    text = text.strip()
    if not text or not api_key:
        return None
    direction = detect_direction(text)
    if not direction:
        return None

    if direction == DIR_TO_EN:
        dir_line = "Direction: translate to English (from Chinese/Japanese/Korean)"
    else:
        dir_line = "Direction: English → Chinese (Simplified)"

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 160,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{dir_line}\n\nText:\n{text[:1500]}"},
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
    """Compatibility wrapper — routes ZH↔EN via translate_message."""
    return await translate_message(text, api_key=api_key, model=model, timeout=timeout)
