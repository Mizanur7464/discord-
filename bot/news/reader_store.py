"""Persist Benzinga articles for the paywall-free news reader."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from pathlib import Path

from bot.news.benzinga import BenzingaArticle

logger = logging.getLogger(__name__)

STORE_DIR = Path(__file__).resolve().parents[2] / "data" / "news_reader" / "articles"
_SAFE_ID = re.compile(r"[^a-zA-Z0-9._-]+")


class NewsReaderStore:
    def __init__(self, *, max_articles: int = 3000):
        self.max_articles = max(100, max_articles)
        STORE_DIR.mkdir(parents=True, exist_ok=True)

    def _path_for(self, article_id: str) -> Path | None:
        safe = _SAFE_ID.sub("_", str(article_id or "").strip())
        if not safe:
            return None
        return STORE_DIR / f"{safe}.json"

    def save(self, article: BenzingaArticle) -> None:
        path = self._path_for(article.article_id)
        if not path:
            return
        payload = asdict(article)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._prune_if_needed()

    def get(self, article_id: str) -> BenzingaArticle | None:
        path = self._path_for(article_id)
        if not path or not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return None
            return BenzingaArticle(
                article_id=str(raw.get("article_id") or article_id),
                title=str(raw.get("title") or ""),
                url=str(raw.get("url") or ""),
                body=str(raw.get("body") or ""),
                symbols=[str(symbol).upper() for symbol in raw.get("symbols") or [] if symbol],
                published=str(raw.get("published") or ""),
            )
        except Exception as exc:
            logger.warning("News reader cache read failed for %s: %s", article_id, exc)
            return None

    def _prune_if_needed(self) -> None:
        files = sorted(STORE_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime)
        overflow = len(files) - self.max_articles
        if overflow <= 0:
            return
        for path in files[:overflow]:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
