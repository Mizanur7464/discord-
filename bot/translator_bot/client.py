"""Standalone QuantiqoX Translator bot (CN → EN, channel reply)."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import discord
from dotenv import load_dotenv

from bot.discord_bot.translator import translate_message
from bot.utils.config import _parse_channel_ids

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"


class TranslatorBot(discord.Client):
    def __init__(
        self,
        *,
        openai_api_key: str,
        openai_model: str,
        channel_ids: list[int],
        excluded_ids: set[int],
        bot_name: str,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.channel_ids = set(channel_ids)
        self.excluded_ids = excluded_ids
        self.bot_name = bot_name

    def _allowed(self, channel_id: int) -> bool:
        if channel_id in self.excluded_ids:
            return False
        if self.channel_ids:
            return channel_id in self.channel_ids
        return True

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (translator)", self.user)
        if self.channel_ids:
            logger.info("Translating only in channels: %s", sorted(self.channel_ids))
        else:
            logger.info("Translating in all chat channels (NB excluded)")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not message.guild:
            return
        if not self._allowed(message.channel.id):
            return
        text = (message.content or "").strip()
        if not text:
            return

        translation = await translate_message(
            text,
            api_key=self.openai_api_key,
            model=self.openai_model,
        )
        if not translation:
            return

        try:
            await message.reply(translation, mention_author=False)
        except discord.Forbidden:
            logger.warning("Missing permission in #%s", getattr(message.channel, "name", "?"))
        except Exception as exc:
            logger.warning("Reply failed: %s", exc)


def load_translator_env() -> dict:
    load_dotenv(ENV_PATH)
    token = os.getenv("TRANSLATOR_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TRANSLATOR_BOT_TOKEN missing in .env")
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not openai_key:
        raise ValueError("OPENAI_API_KEY missing in .env")
    model = os.getenv("TRANSLATOR_OPENAI_MODEL", "").strip() or "gpt-4o-mini"
    name = os.getenv("TRANSLATOR_BOT_NAME", "").strip() or "QuantiqoX Translator"
    channel_ids = _parse_channel_ids(os.getenv("TRANSLATOR_CHANNEL_IDS", "").strip())
    excluded = {
        *_parse_channel_ids(os.getenv("NEWS_CHANNEL_ID", "").strip()),
        *_parse_channel_ids(os.getenv("NEWS_ALL_CHANNEL_ID", "").strip()),
        *_parse_channel_ids(os.getenv("NEWS_SOURCE_CHANNEL_IDS", "").strip()),
        *_parse_channel_ids(os.getenv("SUMMARY_CHANNEL_ID", "").strip()),
        *_parse_channel_ids(os.getenv("MOSQUITO_CHANNEL_ID", "").strip()),
    }
    return {
        "token": token,
        "openai_api_key": openai_key,
        "openai_model": model,
        "channel_ids": channel_ids,
        "excluded_ids": excluded,
        "bot_name": name,
    }


async def run_translator() -> None:
    cfg = load_translator_env()
    client = TranslatorBot(
        openai_api_key=cfg["openai_api_key"],
        openai_model=cfg["openai_model"],
        channel_ids=cfg["channel_ids"],
        excluded_ids=cfg["excluded_ids"],
        bot_name=cfg["bot_name"],
    )
    await client.start(cfg["token"])


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        cfg = load_translator_env()
    except ValueError as exc:
        print(f"\nSetup error: {exc}\n")
        raise SystemExit(1) from exc
    print(f"\nStarting {cfg['bot_name']}...")
    if cfg["channel_ids"]:
        print(f"   Channels: {cfg['channel_ids']}")
    else:
        print("   Channels: all (except NB feeds)")
    print("   Mode: Chinese → English")
    print("   Press Ctrl+C to stop\n")
    try:
        asyncio.run(run_translator())
    except KeyboardInterrupt:
        print("\nTranslator bot stopped.")
