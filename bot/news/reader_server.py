"""Lightweight HTTP server for paywall-free Benzinga article pages."""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from bot.news.benzinga import BenzingaArticle, fetch_article_by_id
from bot.news.reader_html import render_article_page, render_not_found_page
from bot.news.reader_store import NewsReaderStore

logger = logging.getLogger(__name__)


class NewsReaderServer:
    def __init__(
        self,
        *,
        store: NewsReaderStore,
        port: int = 8787,
        api_key: str = "",
        provider: str = "massive",
        brand_name: str = "",
    ):
        self.store = store
        self.port = max(1024, int(port))
        self.api_key = api_key
        self.provider = provider
        self.brand_name = brand_name or "News Trading Bot"
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    def _lookup_article(self, article_id: str) -> BenzingaArticle | None:
        cached = self.store.get(article_id)
        if cached:
            return cached
        if not self.api_key:
            return None
        article = fetch_article_by_id(
            self.api_key,
            article_id,
            provider=self.provider,
        )
        if article:
            self.store.save(article)
        return article

    async def _handle_health(self, _request: web.Request) -> web.Response:
        return web.Response(text="ok", content_type="text/plain")

    async def _handle_article(self, request: web.Request) -> web.Response:
        article_id = str(request.match_info.get("article_id") or "").strip()
        if not article_id:
            return web.Response(text="Missing article id", status=400)
        article = await asyncio.to_thread(self._lookup_article, article_id)
        if not article:
            return web.Response(
                text=render_not_found_page(article_id, brand_name=self.brand_name),
                content_type="text/html",
                status=404,
            )
        return web.Response(
            text=render_article_page(article, brand_name=self.brand_name),
            content_type="text/html",
        )

    async def start(self) -> None:
        if self._runner:
            return
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/n/{article_id}", self._handle_article)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host="0.0.0.0", port=self.port)
        await self._site.start()
        logger.info(
            "News reader listening for %s on port %s",
            self.brand_name,
            self.port,
        )

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        self._runner = None
        self._site = None
