"""Poll Benzinga for new licensed news articles (gap-free)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.news.benzinga import BenzingaArticle, fetch_recent_news

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "benzinga_feed_state.json"


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


class BenzingaFeedPoller:
    def __init__(
        self,
        *,
        api_key: str,
        provider: str = "massive",
        page_size: int = 1000,
        max_seen: int = 5000,
        max_direct_pages: int = 10,
    ):
        self.api_key = api_key
        self.provider = provider
        # Massive allows huge limits; direct Benzinga caps pageSize at 100.
        self.page_size = page_size if provider != "direct" else min(page_size, 100)
        self.max_seen = max_seen
        self.max_direct_pages = max_direct_pages
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._seen_ids: set[str] = set()
        self._seen_order: list[str] = []
        self._last_published: str = ""
        self._cold_start = not STATE_FILE.exists()
        self._load()

    def _load(self) -> None:
        if not STATE_FILE.exists():
            return
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            ids = raw.get("seen_ids") if isinstance(raw, dict) else raw
            if isinstance(ids, list):
                self._seen_order = [str(item) for item in ids]
                self._seen_ids = set(self._seen_order)
            if isinstance(raw, dict):
                self._last_published = str(raw.get("last_published", "") or "")
        except Exception:
            self._seen_ids = set()
            self._seen_order = []
            self._last_published = ""

    def _save(self) -> None:
        if len(self._seen_order) > self.max_seen:
            self._seen_order = self._seen_order[-self.max_seen :]
            self._seen_ids = set(self._seen_order)
        STATE_FILE.write_text(
            json.dumps(
                {"seen_ids": self._seen_order, "last_published": self._last_published},
                indent=2,
            ),
            encoding="utf-8",
        )

    def _mark_seen(self, article_id: str) -> None:
        if article_id not in self._seen_ids:
            self._seen_ids.add(article_id)
            self._seen_order.append(article_id)

    def _update_last_published(self, article: BenzingaArticle) -> None:
        current = _parse_iso(article.published)
        if not current:
            return
        previous = _parse_iso(self._last_published)
        if previous is None or current > previous:
            self._last_published = article.published

    def poll_new(self) -> list[BenzingaArticle]:
        if self.provider == "direct":
            articles = self._poll_direct()
        else:
            articles = self._poll_massive()

        # Cold start (no prior state): prime the backlog silently so we don't
        # flood the channel with hundreds of old headlines on first launch.
        if self._cold_start:
            for article in articles:
                self._mark_seen(article.article_id)
                self._update_last_published(article)
            self._cold_start = False
            self._save()
            logger.info("Benzinga feed primed with %s existing article(s)", len(articles))
            return []

        fresh: list[BenzingaArticle] = []
        for article in articles:
            if article.article_id in self._seen_ids:
                continue
            self._mark_seen(article.article_id)
            self._update_last_published(article)
            fresh.append(article)

        if fresh:
            self._save()
        # Oldest first so Discord shows news in chronological order.
        fresh.sort(key=lambda art: _parse_iso(art.published) or datetime.min.replace(tzinfo=timezone.utc))
        return fresh

    def _poll_massive(self) -> list[BenzingaArticle]:
        # Delta fetch: everything published since the last article we saw.
        # A small overlap (inclusive gte) is fine — seen_ids dedupes it.
        published_gte = ""
        last = _parse_iso(self._last_published)
        if last:
            published_gte = (last - timedelta(seconds=2)).astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        return fetch_recent_news(
            self.api_key,
            page_size=self.page_size,
            provider=self.provider,
            published_gte=published_gte,
        )

    def _poll_direct(self) -> list[BenzingaArticle]:
        # Direct Benzinga caps pageSize at 100 — walk pages until we hit
        # already-seen articles (or the page cap) so bursts aren't dropped.
        collected: list[BenzingaArticle] = []
        for page in range(self.max_direct_pages):
            batch = fetch_recent_news(
                self.api_key,
                page_size=self.page_size,
                provider=self.provider,
                page=page,
            )
            if not batch:
                break
            collected.extend(batch)
            if any(article.article_id in self._seen_ids for article in batch):
                break
            if len(batch) < self.page_size:
                break
        return collected
