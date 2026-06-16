"""Discord bot client with real-time channel news monitoring."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from bot.news.analyzer import MessageAnalyzer, NewsItem
from bot.news.symbols import extract_stock_symbol, split_news_blocks
from bot.news.url_fetcher import UrlFetchError, extract_urls, fetch_article, is_allowed_url
from bot.trading.engine import TradingEngine
from bot.utils.config import Settings
from bot.utils.timing import log_trade_speed, mark_news_if_absent, mark_step

from bot.forwarder.client import SessionForwarder

logger = logging.getLogger(__name__)


class NewsTradingBot(commands.Bot):
    def __init__(self, settings: Settings, forwarder: SessionForwarder | None = None):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True

        super().__init__(
            command_prefix=settings.bot.command_prefix,
            intents=intents,
            help_command=None,
        )

        self.settings = settings
        self.forwarder = forwarder
        self.analyzer = MessageAnalyzer(settings.news)
        self.trading_engine = TradingEngine(settings)
        self._monitoring = False
        self._alert_channel: discord.TextChannel | None = None
        self._processed_messages: set[str] = set()

    def _is_news_author(self, message: discord.Message) -> bool:
        """Allow human posts and trusted news bots (e.g. NuntioBot) in news channels."""
        if self.user and message.author.id == self.user.id:
            return False
        if not message.author.bot:
            return True
        if message.channel.id not in self.settings.news.source_channel_ids:
            return False
        trusted = self.settings.news.trusted_news_bots or ["nuntio"]
        name = message.author.name.lower()
        return any(token.lower() in name for token in trusted)

    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: discord.app_commands.Command,
    ) -> None:
        user = interaction.user
        logger.info(
            "Command /%s used by %s (@%s)",
            command.name,
            user.display_name,
            user.name,
        )

    async def setup_hook(self) -> None:
        await self.add_cog(BotCommands(self))
        await self.tree.sync()
        logger.info("Slash commands synced.")

    async def on_ready(self) -> None:
        channel = self.get_channel(self.settings.alert_channel_id)
        if channel and isinstance(channel, discord.TextChannel):
            self._alert_channel = channel
            source_count = len(self.settings.news.source_channel_ids)
            await channel.send(
                "✅ **News Trading Bot is online!**\n"
                f"Watching {source_count} news channel(s) in real time.\n"
                "Type `/help` to see available commands.\n"
                "Paste a news link or use `/news <url>` to auto-trade."
            )
        else:
            logger.error("Alert channel not found. Check ALERT_CHANNEL_ID.")

        if self.settings.bot.auto_start:
            self._monitoring = True

        logger.info("Logged in as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if not self._is_news_author(message):
            return

        is_dm = message.guild is None
        in_news = message.channel.id in self.settings.news.source_channel_ids

        if not is_dm and not in_news:
            return

        if not self._monitoring and not is_dm:
            return

        if str(message.id) in self._processed_messages:
            return

        source = (
            f"DM from {message.author.display_name}"
            if is_dm
            else f"{message.guild.name} / #{message.channel.name}"
        )

        author_tag = message.author.name
        if message.author.bot:
            author_tag = f"{message.author.name} (bot)"
        logger.info("News message received from %s in channel %s", author_tag, message.channel.id)

        processed = await self._process_news_message(message, source=source)
        if processed:
            self._processed_messages.add(str(message.id))
        if len(self._processed_messages) > 2000:
            self._processed_messages = set(list(self._processed_messages)[-1000:])

    def _collect_message_text(self, message: discord.Message) -> str:
        parts = [message.content]
        for embed in message.embeds:
            if embed.title:
                parts.append(embed.title)
            if embed.description:
                parts.append(embed.description)
            if embed.url:
                parts.append(embed.url)
            for field in embed.fields:
                if field.name:
                    parts.append(field.name)
                if field.value:
                    parts.append(field.value)
        return "\n".join(part for part in parts if part)

    def _extract_urls_from_message(self, message: discord.Message) -> list[str]:
        return self._extract_allowed_urls(self._collect_message_text(message))

    def _extract_allowed_urls(self, text: str) -> list[str]:
        domains = self.settings.news.allowed_url_domains
        return [url for url in extract_urls(text) if is_allowed_url(url, domains)]

    async def _process_item(self, item: NewsItem, timing_key: str = "") -> str | None:
        key = timing_key or item.link
        if key:
            mark_news_if_absent(key)
            mark_step(key, "analyze")

        trade_result = await self.trading_engine.process_signal(
            item.sentiment,
            symbol=item.stock_symbol,
            text=item.title,
        )
        trade_msg = trade_result.message if trade_result else None

        if item.sentiment == "neutral" and not trade_msg:
            trade_msg = "No trade — no keyword match"

        if key:
            if trade_result and trade_result.success:
                action = trade_result.side or "done"
            elif trade_result and trade_result.side == "blocked":
                action = "blocked"
            elif trade_result and trade_result.side == "buy":
                action = "buy-failed"
            elif trade_result:
                action = trade_result.side or "signal"
            elif item.sentiment == "neutral":
                action = "neutral"
            else:
                action = "signal"
            log_trade_speed(key, symbol=item.stock_symbol, action=action)

        return trade_msg

    async def _process_news_message(self, message: discord.Message, *, source: str) -> int:
        """Process every ticker block in a message (URL fetch + Discord text)."""
        text = self._collect_message_text(message)
        if not text.strip():
            logger.warning("Skip message %s — empty content", message.id)
            return 0

        published = message.created_at.strftime("%Y-%m-%d %H:%M UTC")
        blocks = split_news_blocks(text)
        message_urls = self._extract_allowed_urls(text)
        processed = 0

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            symbol = extract_stock_symbol(block)
            sym_key = symbol or "?"
            dedupe_key = f"{message.id}:{sym_key}"
            if dedupe_key in self._processed_messages:
                continue

            block_urls = self._extract_allowed_urls(block)
            url = block_urls[0] if block_urls else None
            if not url and len(blocks) == 1 and message_urls:
                url = message_urls[0]

            item: NewsItem | None = None
            if url and f"url:{url}" not in self._processed_messages:
                item = await self._url_to_item(
                    url,
                    source=source,
                    message_id=dedupe_key,
                    message=message,
                )
                if item:
                    self._processed_messages.add(f"url:{url}")
                    if symbol:
                        item.stock_symbol = symbol
                    elif not item.stock_symbol:
                        item.stock_symbol = extract_stock_symbol(block)

            if not item:
                item = self.analyzer.analyze_text(
                    block,
                    source=source,
                    published=published,
                    message_id=str(message.id),
                    jump_url=message.jump_url,
                )
                if item:
                    if symbol:
                        item.stock_symbol = symbol
                    if url:
                        item.link = url

            if not item:
                continue

            self._processed_messages.add(dedupe_key)
            timing_key = url or dedupe_key
            mark_news_if_absent(timing_key)
            mark_step(timing_key, "received")
            trade_msg = await self._process_item(item, timing_key=timing_key)
            await self.send_news_alert(item, trade_msg)
            processed += 1
            logger.info(
                "Processed message %s — %s %s (%s)",
                message.id,
                item.stock_symbol or "?",
                item.sentiment,
                item.matched_keyword,
            )

        if not processed and text.strip():
            logger.warning(
                "No alert created for message %s — check content/symbol format",
                message.id,
            )

        return processed

    async def _url_to_item(
        self,
        url: str,
        source: str,
        message_id: str,
        *,
        message: discord.Message | None = None,
    ) -> NewsItem | None:
        try:
            title, body = await fetch_article(url)
            mark_step(url, "fetch")
        except UrlFetchError as exc:
            logger.warning("URL fetch failed for %s: %s — trying Discord message fallback", url, exc)
            if message:
                source = source or "news URL"
                for item in self._message_to_items(message, source=source):
                    symbol = item.stock_symbol or extract_stock_symbol(item.title)
                    if symbol:
                        item.stock_symbol = symbol
                    item.link = url
                    return item
            return None

        preview = title if title else body[:300]
        return self.analyzer.analyze_article(
            preview,
            body,
            url=url,
            source=source,
            message_id=message_id,
        )

    async def process_news_url(self, url: str, user: discord.User | discord.Member) -> NewsItem | None:
        if not is_allowed_url(url, self.settings.news.allowed_url_domains):
            return None
        return await self._url_to_item(
            url,
            source=f"/news by {user.display_name}",
            message_id=f"cmd:{url}",
        )

    def _message_to_items(self, message: discord.Message, *, source: str) -> list[NewsItem]:
        text = self._collect_message_text(message)
        published = message.created_at.strftime("%Y-%m-%d %H:%M UTC")
        items: list[NewsItem] = []

        for block in split_news_blocks(text):
            item = self.analyzer.analyze_text(
                block,
                source=source,
                published=published,
                message_id=str(message.id),
                jump_url=message.jump_url,
            )
            if not item:
                continue
            symbol = extract_stock_symbol(block)
            if symbol:
                item.stock_symbol = symbol
            items.append(item)
        return items

    def _message_to_item(self, message: discord.Message) -> NewsItem | None:
        source = (
            f"{message.guild.name} / #{getattr(message.channel, 'name', 'unknown')}"
            if message.guild
            else "DM"
        )
        items = self._message_to_items(message, source=source)
        return items[0] if items else None

    async def send_news_alert(self, item: NewsItem, trade_msg: str | None = None) -> None:
        if not self._alert_channel:
            return

        if item.sentiment == "bullish":
            emoji, color = "🟢", discord.Color.green()
        elif item.sentiment == "ignored":
            emoji, color = "⚪", discord.Color.light_grey()
        elif item.sentiment == "neutral":
            emoji, color = "🟡", discord.Color.gold()
        else:
            emoji, color = "🔴", discord.Color.red()

        embed = discord.Embed(
            title=f"{emoji} {item.sentiment.upper()} News Alert",
            description=item.title[:4096],
            color=color,
            url=item.link or None,
        )
        embed.add_field(name="Source", value=item.source, inline=True)
        embed.add_field(name="Keyword", value=item.matched_keyword, inline=True)
        if item.stock_symbol:
            embed.add_field(name="Symbol", value=item.stock_symbol, inline=True)
        embed.add_field(name="Published", value=item.published, inline=False)

        if item.sentiment == "ignored":
            action = trade_msg or "No trade — ignored signal"
            embed.add_field(name="Action", value=action, inline=False)
        elif item.sentiment == "neutral":
            action = trade_msg or "No trade — no keyword match"
            embed.add_field(name="Action", value=action, inline=False)
        elif trade_msg:
            embed.add_field(name="Trade", value=trade_msg, inline=False)

        await self._alert_channel.send(embed=embed)


class BotCommands(commands.Cog):
    def __init__(self, bot: NewsTradingBot):
        self.bot = bot

    @discord.app_commands.command(name="help", description="Show all commands")
    async def help_cmd(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="📖 Command List",
            description="Use the commands below:",
            color=discord.Color.blue(),
        )
        commands_list = [
            ("/help", "Show this help message"),
            ("/news <url>", "Fetch a news link and auto-trade"),
            ("/status", "Bot and trading status"),
            ("/start", "Start news monitoring"),
            ("/stop", "Stop news monitoring"),
            ("/check", "Scan recent messages from news channels"),
            ("/keywords", "Show keyword list"),
        ]
        for name, desc in commands_list:
            embed.add_field(name=name, value=desc, inline=False)

        embed.set_footer(text="Edit settings in config/settings.yaml and .env")
        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name="status", description="Show bot status")
    async def status_cmd(self, interaction: discord.Interaction) -> None:
        monitoring = "running ✅" if self.bot._monitoring else "stopped ⏸️"
        trade_status = self.bot.trading_engine.get_status()
        source_channels = ", ".join(str(cid) for cid in self.bot.settings.news.source_channel_ids)

        embed = discord.Embed(title="🤖 Bot Status", color=discord.Color.blue())
        embed.add_field(name="Monitoring", value=monitoring, inline=True)
        embed.add_field(name="Source channels", value=source_channels, inline=True)
        embed.add_field(name="Alert channel", value=str(self.bot.settings.alert_channel_id), inline=True)
        embed.add_field(name="Trading", value=trade_status, inline=False)
        if self.bot.forwarder:
            embed.add_field(name="Session forwarder", value=self.bot.forwarder.get_status(), inline=False)

        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name="start", description="Start news monitoring")
    async def start_cmd(self, interaction: discord.Interaction) -> None:
        self.bot._monitoring = True
        await interaction.response.send_message(
            "▶️ **Monitoring started!**\n"
            "Listening for new messages in your news channels."
        )

    @discord.app_commands.command(name="stop", description="Stop news monitoring")
    async def stop_cmd(self, interaction: discord.Interaction) -> None:
        self.bot._monitoring = False
        await interaction.response.send_message("⏸️ **Monitoring stopped.**")

    @discord.app_commands.command(name="check", description="Scan recent messages from news channels")
    async def check_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        found = 0

        for channel_id in self.bot.settings.news.source_channel_ids:
            channel = self.bot.get_channel(channel_id)
            if not channel or not isinstance(channel, discord.TextChannel):
                continue

            async for message in channel.history(limit=30):
                if not self.bot._is_news_author(message):
                    continue
                if str(message.id) in self.bot._processed_messages:
                    continue

                source = (
                    f"{message.guild.name} / #{message.channel.name}"
                    if message.guild
                    else "scan"
                )
                count = await self.bot._process_news_message(message, source=source)
                if count:
                    self.bot._processed_messages.add(str(message.id))
                    found += count

        if found == 0:
            await interaction.followup.send("No new matching messages found.")
            return

        await interaction.followup.send(f"✅ Processed {found} message(s)!")

    @discord.app_commands.command(name="news", description="Fetch a news URL and auto-trade")
    @discord.app_commands.describe(url="News link (e.g. nuntiobot.com)")
    async def news_cmd(self, interaction: discord.Interaction, url: str) -> None:
        await interaction.response.defer()

        if not is_allowed_url(url, self.bot.settings.news.allowed_url_domains):
            allowed = ", ".join(self.bot.settings.news.allowed_url_domains)
            await interaction.followup.send(f"URL not allowed. Allowed domains: {allowed}")
            return

        item = await self.bot.process_news_url(url, interaction.user)
        if not item:
            await interaction.followup.send("No news content found in this article.")
            return

        trade_msg = await self.bot._process_item(item, timing_key=url)
        await self.bot.send_news_alert(item, trade_msg)

        if item.sentiment == "bullish":
            note = f"Buy signal — alert sent ({item.matched_keyword})."
        elif item.sentiment == "ignored":
            note = f"Ignored — {item.matched_keyword}."
        elif item.sentiment == "neutral":
            note = "Neutral — alert sent, no trade."
        else:
            note = "Alert sent."
        await interaction.followup.send(note)

    @discord.app_commands.command(name="keywords", description="Show keyword list")
    async def keywords_cmd(self, interaction: discord.Interaction) -> None:
        kw = self.bot.settings.news.keywords
        bullish = ", ".join(kw.get("bullish", [])) or "none"
        ignore = ", ".join(kw.get("ignore", [])) or "none"

        embed = discord.Embed(title="Keyword List", color=discord.Color.gold())
        embed.add_field(name="Buy signals", value=bullish, inline=False)
        embed.add_field(name="Ignore signals", value=ignore, inline=False)
        embed.set_footer(text="Edit config/settings.yaml to change keywords")

        await interaction.response.send_message(embed=embed)


async def run_bot(settings: Settings, forwarder: SessionForwarder | None = None) -> None:
    bot = NewsTradingBot(settings, forwarder=forwarder)
    async with bot:
        await bot.start(settings.discord_token)
