"""Extract mosquito volume cards from Discord image URLs using OpenAI vision."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = """You read Stock PlayMaker mosquito channel screenshots/cards.

Extract visible stock rows only. Return JSON only:
{"signals":[{"symbol":"ABCD","price":"1.23","rvol":"4.5","vol_1m":"123,456","vol_2m":"234,567","vol_5m":"5.6M","vol_10m":"7.8M","float":"9.1M"}]}

Rules:
- symbol is the ticker shown in the row.
- Keep numeric suffixes K/M/B when visible.
- Use empty string for fields not visible.
- Ignore UI text, channel names, buttons, and non-stock words.
- If no readable stock rows exist, return {"signals":[]}."""


def _post_openai(payload: dict, *, api_key: str, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        OPENAI_CHAT_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI vision HTTP {exc.code}: {body[:200]}") from exc


def _signal_to_text(signal: dict) -> str:
    symbol = str(signal.get("symbol", "")).strip().upper()
    if not symbol:
        return ""

    parts = [symbol]
    price = str(signal.get("price", "")).strip()
    if price:
        parts.append(f"${price.lstrip('$')}")

    labels = (
        ("rvol", "RVol"),
        ("vol_1m", "1m"),
        ("vol_2m", "2m"),
        ("vol_5m", "5m"),
        ("vol_10m", "10m"),
        ("float", "Float"),
    )
    for key, label in labels:
        value = str(signal.get(key, "")).strip()
        if value:
            parts.append(f"{label}: {value}")
    return " ".join(parts)


def analyze_mosquito_image_urls(
    image_urls: list[str],
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    timeout: float = 30.0,
) -> str:
    """Return parseable mosquito volume text from image URLs."""
    if not image_urls or not api_key:
        return ""

    content: list[dict] = [{"type": "text", "text": "Extract mosquito stock volume rows from these images."}]
    for url in image_urls[:4]:
        content.append({"type": "image_url", "image_url": {"url": url}})

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 700,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    }

    try:
        data = _post_openai(payload, api_key=api_key, timeout=timeout)
        raw = data["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
    except Exception as exc:
        logger.warning("Mosquito vision OCR failed: %s", exc)
        return ""

    lines = [_signal_to_text(signal) for signal in parsed.get("signals", []) if isinstance(signal, dict)]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    return "MOSQUITO VOLUME SIGNAL\n" + "\n".join(lines)
