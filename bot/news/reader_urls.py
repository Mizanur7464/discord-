"""Public URLs for the licensed Benzinga news reader."""

from __future__ import annotations


def normalize_reader_base_url(base_url: str) -> str:
    return str(base_url or "").strip().rstrip("/")


def reader_article_url(base_url: str, article_id: str) -> str:
    base = normalize_reader_base_url(base_url)
    article_id = str(article_id or "").strip()
    if not base or not article_id:
        return ""
    return f"{base}/n/{article_id}"
