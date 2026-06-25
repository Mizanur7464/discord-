"""Poll Benzinga for new licensed news articles."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from bot.news.benzinga import BenzingaArticle, fetch_recent_news

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "benzinga_feed_state.json"


class BenzingaFeedPoller:
    def __init__(
        self,
        *,
        api_key: str,
        provider: str = "massive",
        page_size: int = 100,
        max_seen: int = 2000,
    ):
        self.api_key = api_key
        self.provider = provider
        self.page_size = page_size
        self.max_seen = max_seen
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._seen_ids: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not STATE_FILE.exists():
            return
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            ids = raw.get("seen_ids") if isinstance(raw, dict) else raw
            if isinstance(ids, list):
                self._seen_ids = {str(item) for item in ids}
        except Exception:
            self._seen_ids = set()

    def _save(self) -> None:
        ids = list(self._seen_ids)
        if len(ids) > self.max_seen:
            ids = ids[-self.max_seen :]
            self._seen_ids = set(ids)
        STATE_FILE.write_text(json.dumps({"seen_ids": ids}, indent=2), encoding="utf-8")

    def poll_new(self) -> list[BenzingaArticle]:
        articles = fetch_recent_news(self.api_key, page_size=self.page_size, provider=self.provider)
        fresh: list[BenzingaArticle] = []
        for article in articles:
            if article.article_id in self._seen_ids:
                continue
            self._seen_ids.add(article.article_id)
            fresh.append(article)
        if fresh:
            self._save()
        return fresh
