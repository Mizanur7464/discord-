"""
Quantiqo Discord Bot
====================
How to run:
  1. pip install -r requirements.txt
  2. Copy .env.example to .env and add your token + channel IDs
  3. python run.py
     (starts QuantiqoX + QuantiqoX Translator together when TRANSLATOR_BOT_TOKEN is set)
"""

import asyncio
import logging
import os
import sys


def _fix_windows_dns() -> None:
    """ccxt installs aiodns which can break aiohttp DNS on Windows."""
    try:
        import aiohttp
        from aiohttp.resolver import ThreadedResolver

        original_init = aiohttp.TCPConnector.__init__

        def patched_init(self, *args, **kwargs):
            kwargs.setdefault("resolver", ThreadedResolver())
            original_init(self, *args, **kwargs)

        aiohttp.TCPConnector.__init__ = patched_init
    except Exception:
        pass


_fix_windows_dns()

from bot.discord_bot.client import run_bot
from bot.forwarder.client import SessionForwarder
from bot.utils.config import load_settings


async def _run_all(settings, forwarder) -> None:
    tasks = [asyncio.create_task(run_bot(settings, forwarder), name="quantiquox")]

    translator_token = os.getenv("TRANSLATOR_BOT_TOKEN", "").strip()
    if translator_token:
        from bot.translator_bot.client import TranslatorBot, load_translator_env

        cfg = load_translator_env()
        translator = TranslatorBot(
            openai_api_key=cfg["openai_api_key"],
            openai_model=cfg["openai_model"],
            channel_ids=cfg["channel_ids"],
            excluded_ids=cfg["excluded_ids"],
            bot_name=cfg["bot_name"],
        )

        async def _run_translator() -> None:
            async with translator:
                await translator.start(cfg["token"])

        tasks.append(asyncio.create_task(_run_translator(), name="translator"))
        print(f"   Translator: {cfg['bot_name']} (CN → EN)")
        if cfg["channel_ids"]:
            print(f"   Translator channels: {cfg['channel_ids']}")
    else:
        print("   Translator: off (no TRANSLATOR_BOT_TOKEN)")

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for task in pending:
        task.cancel()
    for task in done:
        exc = task.exception()
        if exc:
            raise exc


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("websocket").setLevel(logging.CRITICAL)
    logging.getLogger("discum").setLevel(logging.CRITICAL)
    logging.getLogger("discord.client").setLevel(logging.INFO)

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"\nSetup error: {exc}\n")
        print("See .env.example and create a .env file.\n")
        sys.exit(1)

    print(f"\nStarting {settings.bot.name}...")
    print(f"   Broker: Alpaca ({'PAPER' if settings.alpaca_paper else 'LIVE'})")
    print(f"   Auto trade: {'enabled' if settings.trading.enabled else 'disabled'}")
    if settings.news.source_channel_ids:
        print(f"   Bot watching: {settings.news.source_channel_ids}")
    else:
        print("   Bot watching: (none yet — set NEWS_SOURCE_CHANNEL_IDS in .env)")
    if settings.forwarder.enabled:
        fwd = "ready" if settings.forwarder.user_token else "waiting for user token"
        print(f"   Session forwarder: {fwd}")
        if settings.forwarder.source_channel_ids:
            print(f"   Forward from: {settings.forwarder.source_channel_ids}")
            print(f"   Forward to: {settings.forwarder.dest_channel_id}")
    if settings.news.reader_enabled:
        print(f"   News reader: {settings.bot.name} (port {settings.news.reader_port})")

    forwarder = None
    if settings.forwarder.enabled and settings.forwarder.source_channel_ids:
        forwarder = SessionForwarder(settings)
        forwarder.start_background()

    print("   Press Ctrl+C to stop\n")
    try:
        asyncio.run(_run_all(settings, forwarder))
    except KeyboardInterrupt:
        print("\nBot stopped.")


if __name__ == "__main__":
    main()
