"""
Discord News Trading Bot
========================
How to run:
  1. pip install -r requirements.txt
  2. Copy .env.example to .env and add your token + channel IDs
  3. python run.py
"""

import asyncio
import logging
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
        reader_url = settings.news.reader_base_url or f"http://127.0.0.1:{settings.news.reader_port}"
        print(f"   News reader: {reader_url}")
    print("   Press Ctrl+C to stop\n")

    forwarder = None
    if settings.forwarder.enabled and settings.forwarder.source_channel_ids:
        forwarder = SessionForwarder(settings)
        forwarder.start_background()

    try:
        asyncio.run(run_bot(settings, forwarder))
    except KeyboardInterrupt:
        print("\nBot stopped.")


if __name__ == "__main__":
    main()
