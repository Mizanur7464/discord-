"""Discord user-session forwarder — mirrors Stock PlayMaker news to your server."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from bot.news.mosquito_vision import analyze_mosquito_image_urls
from bot.news.symbols import extract_stock_symbol
from bot.news.url_fetcher import extract_urls, is_allowed_url
from bot.news.volume_signal import parse_volume_signals
from bot.utils.timing import mark_news

if TYPE_CHECKING:
    from bot.utils.config import Settings

logger = logging.getLogger(__name__)


class SessionForwarder:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._seen_message_ids: set[str] = set()
        self._thread: threading.Thread | None = None
        self._running = False
        self._client = None

    @property
    def enabled(self) -> bool:
        cfg = self.settings.forwarder
        has_login = bool(cfg.user_token) or (bool(cfg.user_email) and bool(cfg.user_password))
        return cfg.enabled and has_login

    def start_background(self) -> None:
        if not self.enabled:
            if self.settings.forwarder.enabled:
                logger.warning(
                    "Forwarder waiting — add DISCORD_USER_TOKEN or DISCORD_USER_EMAIL + DISCORD_USER_PASSWORD to .env"
                )
            return
        if self._thread and self._thread.is_alive():
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, name="session-forwarder", daemon=True)
        self._thread.start()
        logger.info(
            "Session forwarder starting — %s source channel(s) → map %s (fallback %s)",
            len(self.settings.forwarder.source_channel_ids),
            self.settings.forwarder.dest_channel_map or "none",
            self.settings.forwarder.dest_channel_id,
        )

    def stop(self) -> None:
        self._running = False
        if self._client:
            try:
                self._client.gateway.close()
            except Exception:
                pass

    def get_status(self) -> str:
        cfg = self.settings.forwarder
        if not cfg.enabled:
            return "disabled"
        if cfg.user_token:
            if self._thread and self._thread.is_alive():
                return "running"
            return "stopped"
        if cfg.user_email and cfg.user_password:
            return "login set — need token (run get_token.py)"
        return "waiting for login"

    def _run(self) -> None:
        try:
            import discum
        except ImportError:
            logger.error("discum not installed — run: pip install discum")
            return

        cfg = self.settings.forwarder
        token = cfg.user_token
        if not token:
            logger.error(
                "DISCORD_USER_TOKEN missing. Log in with alt account email/password, copy token, paste in .env"
            )
            return

        bot = discum.Client(token=token, log={"console": False, "file": False})
        self._client = bot

        @bot.gateway.command
        def on_message(resp):
            if not self._running:
                return
            if resp.event.message:
                try:
                    self._handle_message(bot, resp.parsed.auto())
                except Exception as exc:
                    logger.error("Forwarder error: %s", exc)

        try:
            bot.gateway.run(auto_reconnect=True)
        except Exception as exc:
            logger.error("Forwarder gateway stopped: %s", exc)

    def _fetch_full_message(self, bot, channel_id: int, message_id: str) -> dict[str, Any] | None:
        """Discord gateway CREATE payloads often have incomplete embeds — fetch full message."""
        try:
            resp = bot.getMessage(channel_id, message_id)
            data = resp.json() if hasattr(resp, "json") else resp
            if isinstance(data, dict) and data.get("id"):
                return data
        except Exception as exc:
            logger.warning("Forwarder full fetch failed for %s: %s", message_id, exc)
        return None

    def _signal_from_text(self, text: str) -> tuple[list[str], str]:
        domains = self.settings.news.allowed_url_domains
        urls = [u for u in extract_urls(text) if is_allowed_url(u, domains)]
        symbol = extract_stock_symbol(text)
        if not symbol and self.settings.trading.mosquito_volume_filter_enabled:
            volume_signals = parse_volume_signals(
                text,
                min_value=self.settings.trading.mosquito_volume_min_value,
                min_relative_volume=self.settings.trading.mosquito_min_relative_volume,
            )
            if volume_signals:
                symbol = volume_signals[0].symbol
        return urls, symbol

    def _handle_message(self, bot, data: dict) -> None:
        channel_id = int(data.get("channel_id", 0))
        if channel_id not in self.settings.forwarder.source_channel_ids:
            return

        message_id = str(data.get("id", ""))
        if not message_id or message_id in self._seen_message_ids:
            return

        text = self._build_text(data)
        urls, symbol = self._signal_from_text(text)

        if not urls and not symbol and data.get("embeds"):
            full = self._fetch_full_message(bot, channel_id, message_id)
            if full:
                data = full
                text = self._build_text(data)
                urls, symbol = self._signal_from_text(text)

        if not urls and not symbol:
            image_text = self._extract_text_from_images(data)
            if image_text:
                text = "\n".join(part for part in (text, image_text) if part)
                urls, symbol = self._signal_from_text(text)

        if not text:
            logger.info("Forwarder skip %s — empty message body", message_id)
            return

        if self.settings.forwarder.require_news_url and not urls and not symbol:
            logger.info("Forwarder skip %s — no news URL or ticker", message_id)
            return

        if not urls and not symbol:
            logger.info("Forwarder skip %s — no URL or ticker in: %s", message_id, text[:80])
            return

        mark_news(urls[0] if urls else message_id)
        logger.info("News received — speed timer started%s", f" ({symbol})" if symbol else "")

        dest_id = str(self._resolve_dest(channel_id))
        bot.sendMessage(dest_id, text)

        self._seen_message_ids.add(message_id)
        self._trim_seen()

        author = data.get("author", {}).get("username", "?")
        logger.info("Forwarded to %s from channel %s (by %s)%s", dest_id, channel_id, author, f" [{symbol}]" if symbol else "")

    def _resolve_dest(self, source_channel_id: int) -> int:
        cfg = self.settings.forwarder
        return cfg.dest_channel_map.get(source_channel_id, cfg.dest_channel_id)

    def _collect_image_urls(self, data: dict) -> list[str]:
        urls: list[str] = []

        for attachment in data.get("attachments") or []:
            content_type = str(attachment.get("content_type", "")).lower()
            url = attachment.get("url") or attachment.get("proxy_url")
            if url and (content_type.startswith("image/") or any(str(url).lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp"))):
                urls.append(str(url))

        for embed in data.get("embeds") or []:
            for key in ("image", "thumbnail"):
                image = embed.get(key) or {}
                url = image.get("url") or image.get("proxy_url")
                if url:
                    urls.append(str(url))

        unique: list[str] = []
        for url in urls:
            if url not in unique:
                unique.append(url)
        return unique

    def _extract_text_from_images(self, data: dict) -> str:
        image_urls = self._collect_image_urls(data)
        if not image_urls:
            return ""

        text = analyze_mosquito_image_urls(
            image_urls,
            api_key=self.settings.news.openai_api_key,
            model=self.settings.news.openai_model,
        )
        if text:
            logger.info("Mosquito image OCR extracted %s image(s)", len(image_urls))
        return text

    def _build_text(self, data: dict) -> str:
        parts: list[str] = []
        content = (data.get("content") or "").strip()
        if content:
            parts.append(str(content))
        for embed in data.get("embeds") or []:
            if embed.get("title"):
                parts.append(str(embed["title"]))
            if embed.get("description"):
                parts.append(str(embed["description"]))
            if embed.get("url"):
                parts.append(str(embed["url"]))
            for field in embed.get("fields") or []:
                name = field.get("name", "")
                value = field.get("value", "")
                if name:
                    parts.append(str(name))
                if value:
                    parts.append(str(value))
        return "\n".join(parts).strip()

    def _trim_seen(self) -> None:
        if len(self._seen_message_ids) > 2000:
            self._seen_message_ids = set(list(self._seen_message_ids)[-1000:])
