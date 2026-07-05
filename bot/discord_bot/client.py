"""Discord bot client with real-time channel news monitoring."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from bot.news.analyzer import MessageAnalyzer, NewsItem
from bot.news.benzinga_feed import BenzingaFeedPoller
from bot.news.reader_server import NewsReaderServer
from bot.news.reader_store import NewsReaderStore
from bot.news.reader_urls import reader_article_url
from bot.news.mosquito_vision import analyze_mosquito_image_urls
from bot.news.symbols import extract_nuntio_headline, extract_stock_symbol, split_news_blocks
from bot.news.url_fetcher import UrlFetchError, extract_urls, fetch_article, is_allowed_url
from bot.news.volume_signal import VolumeSignal, VolumeSignalTracker
from bot.news.watchlist import WatchEntry, WatchTrigger, WatchlistStore
from bot.trading.data_providers import build_data_provider
from bot.trading.engine import TradingEngine
from bot.trading.historical_watchlist import HistoricalWatchlistStore
from bot.trading.potential_store import PotentialStore
from bot.trading.realtime_scanner import RealtimeScanner
from bot.trading.runner_history import RunnerHistoryStore
from bot.trading.scanner import ScanResult, SymbolScanner
from bot.trading.universe_scanner import fetch_market_top_gainers, fetch_universe_symbols
from bot.utils.config import Settings
from bot.utils.timing import log_trade_speed, mark_news_if_absent, mark_step

from bot.discord_bot.mosquito_automute import ChannelAutoMute, MosquitoAutoMute
from bot.discord_bot.mosquito_embed import build_mosquito_alert
from bot.discord_bot.news_embed import (
    _format_published_et,
    build_benzinga_news_blocks,
    build_timeline_news_blocks,
)
from bot.news.impact_routing import resolve_impact_post_targets
from bot.news.ai_output import NewsAIOutput
from bot.news.news_intelligence import (
    NewsImpact,
    SymbolNewsContext,
    build_priority_line,
    build_trader_context_line,
    classify_impact,
    is_options_news,
    is_out_of_news_universe,
    is_dilution_news,
    resolve_news_routing,
)

# Trailing blank line (zero-width space) to add visual spacing between
# consecutive news posts, matching the SPM/NB look.
_NEWS_GAP = "\n\u200b"
from bot.discord_bot.scan_embed import build_scan_embed, format_scan_summary, _resolve_min_score
from bot.discord_bot.watchlist_monitor_line import build_watchlist_monitor_line
from bot.discord_bot.summary_publisher import SummaryPublisher
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
        self.volume_tracker = VolumeSignalTracker(
            min_value=settings.trading.mosquito_volume_min_value,
            min_relative_volume=settings.trading.mosquito_min_relative_volume,
            confirm_seconds=settings.trading.mosquito_volume_confirm_minutes * 60,
        )
        self.watchlist = WatchlistStore(
            days=settings.trading.watchlist_days,
            volume_increase_percent=settings.trading.watchlist_volume_increase_percent,
            price_increase_percent=settings.trading.watchlist_price_increase_percent,
            max_entries=settings.trading.watchlist_max_entries,
        )
        self.historical_watchlist = HistoricalWatchlistStore(
            max_entries=settings.trading.historical_watchlist_max_entries,
            retention_days=settings.trading.historical_watchlist_retention_days,
        )
        self.runner_history = RunnerHistoryStore(
            big_move_percent=settings.trading.runner_big_move_percent,
            retention_days=settings.trading.runner_retention_days,
        )
        self.data_provider = build_data_provider(
            settings.trading.data_provider,
            get_clients=self.trading_engine._get_clients,
            get_last_price=self.trading_engine._get_last_price,
            get_latest_trade_price=self.trading_engine._get_latest_trade_price,
            moomoo_host=settings.trading.moomoo_host,
            moomoo_port=settings.trading.moomoo_port,
            ibkr_host=settings.trading.ibkr_host,
            ibkr_port=settings.trading.ibkr_port,
            ibkr_client_id=settings.trading.ibkr_client_id,
        )
        self.scanner = SymbolScanner(
            settings.trading,
            self.runner_history,
            get_clients=self.trading_engine._get_clients,
            get_last_price=self.trading_engine._get_last_price,
            get_latest_trade_price=self.trading_engine._get_latest_trade_price,
            data_provider=self.data_provider,
            benzinga_api_key=settings.benzinga_api_key,
            benzinga_news_provider=settings.benzinga_news_provider,
            finnhub_api_key=settings.finnhub_api_key,
            unusual_whales_api_key=settings.unusual_whales_api_key,
            watchlist_symbols_fn=self._collect_scan_symbols,
            watchlist_activity_fn=self._watchlist_activity_for,
        )
        self.potential_store = PotentialStore(
            retention_days=settings.trading.potential_retention_days,
        )
        self.summary_publisher = SummaryPublisher(
            top_limit=settings.trading.summary_top_gainers_limit,
        )
        self.benzinga_feed: BenzingaFeedPoller | None = None
        if settings.benzinga_api_key and settings.news.benzinga_feed_enabled:
            self.benzinga_feed = BenzingaFeedPoller(
                api_key=settings.benzinga_api_key,
                provider=settings.benzinga_news_provider,
            )
        self.news_reader_store: NewsReaderStore | None = None
        self.news_reader_server: NewsReaderServer | None = None
        if settings.news.reader_enabled and settings.benzinga_api_key:
            self.news_reader_store = NewsReaderStore()
            self.news_reader_server = NewsReaderServer(
                store=self.news_reader_store,
                port=settings.news.reader_port,
                api_key=settings.benzinga_api_key,
                provider=settings.benzinga_news_provider,
                brand_name=settings.bot.name,
                scan_provider=self._scan_for_reader,
            )
        self.realtime_scanner: RealtimeScanner | None = None
        if settings.trading.realtime_scanner_enabled:
            self.realtime_scanner = RealtimeScanner(
                interval_seconds=settings.trading.realtime_scan_interval_seconds,
                min_score=settings.trading.scanner_min_alert_score,
                alert_cooldown_seconds=settings.trading.realtime_scan_alert_cooldown_seconds,
                scan_fn=self._scan_symbol_sync,
                collect_symbols_fn=self._collect_scan_symbols,
                send_alert_fn=self._send_realtime_alert,
                universe_symbols_fn=self._fetch_universe_symbols
                if settings.trading.universe_scanner_enabled
                else None,
                max_symbols_per_cycle=settings.trading.realtime_max_symbols_per_cycle,
                batch_rotation=settings.trading.realtime_batch_rotation,
                batch_hook_fn=self._on_scan_batch,
            )
        self._monitoring = False
        self._background_tasks: list[asyncio.Task] = []
        self._alert_channel: discord.TextChannel | None = None
        self._watchlist_channel: discord.TextChannel | None = None
        self._summary_channel: discord.TextChannel | None = None
        self._news_channel: discord.TextChannel | None = None
        self._news_all_channel: discord.TextChannel | None = None
        self._news_high_channel: discord.TextChannel | None = None
        self._news_medium_channel: discord.TextChannel | None = None
        self._news_low_channel: discord.TextChannel | None = None
        self._news_noise_channel: discord.TextChannel | None = None
        self._mosquito_channel: discord.TextChannel | None = None
        self._potential_channel: discord.TextChannel | None = None
        self._mc_600m_potential_channel: discord.TextChannel | None = None
        self._mc_600m_scanner_channel: discord.TextChannel | None = None
        self._mc_3b_potential_channel: discord.TextChannel | None = None
        self._mc_3b_scanner_channel: discord.TextChannel | None = None
        self._news_250m_channel: discord.TextChannel | None = None
        self._news_600m_channel: discord.TextChannel | None = None
        self._crypto_news_channel: discord.TextChannel | None = None
        self._world_news_channel: discord.TextChannel | None = None
        self._mosquito_recent: dict[str, float] = {}
        self._watchlist_recent: dict[str, float] = {}
        self._potential_recent: dict[str, float] = {}
        self._watchlist_batch_sent: int = 0
        self._potential_batch_sent: int = 0
        cfg = settings.trading
        self._mosquito_automute = MosquitoAutoMute(
            window_seconds=cfg.mosquito_automute_window_seconds,
            max_alerts_in_window=cfg.mosquito_automute_max_alerts,
            mute_seconds=cfg.mosquito_automute_duration_seconds,
        )
        self._watchlist_automute = ChannelAutoMute(
            window_seconds=cfg.watchlist_automute_window_seconds,
            max_alerts_in_window=cfg.watchlist_automute_max_alerts,
            mute_seconds=cfg.watchlist_automute_duration_seconds,
        )
        self._mosquito_mute_notice_at: float = 0.0
        self._watchlist_mute_notice_at: float = 0.0
        self._scan_detail_cache: dict[str, tuple[ScanResult, int]] = {}
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
        if self.settings.bot.alerts_enabled and self.settings.alert_channel_id:
            channel = self.get_channel(self.settings.alert_channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                self._alert_channel = channel
                source_count = len(self.settings.news.source_channel_ids)
                mode_line = (
                    "Mode: semi-automated scanner + alerts (use `/buy SYMBOL` to confirm trades).\n"
                    if self._semi_automated()
                    else "Mode: automatic trading on bullish signals.\n"
                )
                try:
                    await channel.send(
                        f"✅ **{self.settings.bot.name} is online!**\n"
                        f"Watching {source_count} news channel(s) in real time.\n"
                        f"{mode_line}"
                        "Type `/help` to see available commands."
                    )
                except discord.Forbidden:
                    logger.warning(
                        "Alerts channel locked or missing Send Messages — alerts disabled for this session."
                    )
                    self._alert_channel = None
            else:
                logger.error("Alert channel not found. Check ALERT_CHANNEL_ID.")
        elif not self.settings.bot.alerts_enabled:
            logger.info("Alerts channel disabled (bot.alerts_enabled=false).")

        if self.settings.watchlist_channel_id:
            watchlist_channel = self.get_channel(self.settings.watchlist_channel_id)
            if isinstance(watchlist_channel, discord.TextChannel):
                self._watchlist_channel = watchlist_channel
            else:
                logger.warning("Watchlist channel not found. Falling back to alerts.")
        else:
            self._watchlist_channel = None

        if self.settings.summary_channel_id:
            summary_channel = self.get_channel(self.settings.summary_channel_id)
            if isinstance(summary_channel, discord.TextChannel):
                self._summary_channel = summary_channel
            else:
                logger.warning("Summary channel not found. Check SUMMARY_CHANNEL_ID.")

        if self.settings.news_channel_id:
            news_channel = self.get_channel(self.settings.news_channel_id)
            if isinstance(news_channel, discord.TextChannel):
                self._news_channel = news_channel
            else:
                logger.warning("News channel not found. Check NEWS_CHANNEL_ID.")

        impact_channel_map = [
            ("news_all_channel_id", "_news_all_channel", "NEWS_ALL_CHANNEL_ID"),
            ("news_high_impact_channel_id", "_news_high_channel", "NEWS_HIGH_IMPACT_CHANNEL_ID"),
            ("news_medium_impact_channel_id", "_news_medium_channel", "NEWS_MEDIUM_IMPACT_CHANNEL_ID"),
            ("news_low_impact_channel_id", "_news_low_channel", "NEWS_LOW_IMPACT_CHANNEL_ID"),
            ("news_noise_channel_id", "_news_noise_channel", "NEWS_NOISE_CHANNEL_ID"),
        ]
        for setting_attr, channel_attr, env_name in impact_channel_map:
            channel_id = getattr(self.settings, setting_attr)
            if not channel_id:
                continue
            channel = self.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                setattr(self, channel_attr, channel)
            else:
                logger.warning("%s channel not found. Check %s.", channel_attr, env_name)
        if not self._news_all_channel:
            self._news_all_channel = self._news_channel

        if self.settings.mosquito_channel_id:
            mosquito_channel = self.get_channel(self.settings.mosquito_channel_id)
            if isinstance(mosquito_channel, discord.TextChannel):
                self._mosquito_channel = mosquito_channel
            else:
                logger.warning("Mosquito channel not found. Check MOSQUITO_CHANNEL_ID.")

        if self.settings.potential_channel_id:
            potential_channel = self.get_channel(self.settings.potential_channel_id)
            if isinstance(potential_channel, discord.TextChannel):
                self._potential_channel = potential_channel
            else:
                logger.warning("Potential channel not found. Check POTENTIAL_CHANNEL_ID.")

        mc_channel_map = [
            ("mc_600m_potential_channel_id", "_mc_600m_potential_channel", "MC_600M_POTENTIAL_CHANNEL_ID"),
            ("mc_600m_scanner_channel_id", "_mc_600m_scanner_channel", "MC_600M_SCANNER_CHANNEL_ID"),
            ("mc_3b_potential_channel_id", "_mc_3b_potential_channel", "MC_3B_POTENTIAL_CHANNEL_ID"),
            ("mc_3b_scanner_channel_id", "_mc_3b_scanner_channel", "MC_3B_SCANNER_CHANNEL_ID"),
            ("news_250m_channel_id", "_news_250m_channel", "NEWS_250M_CHANNEL_ID"),
            ("news_600m_channel_id", "_news_600m_channel", "NEWS_600M_CHANNEL_ID"),
            ("crypto_news_channel_id", "_crypto_news_channel", "CRYPTO_NEWS_CHANNEL_ID"),
            ("world_news_channel_id", "_world_news_channel", "WORLD_NEWS_CHANNEL_ID"),
        ]
        for setting_attr, channel_attr, env_name in mc_channel_map:
            channel_id = getattr(self.settings, setting_attr)
            if not channel_id:
                continue
            channel = self.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                setattr(self, channel_attr, channel)
            else:
                logger.warning("%s channel not found. Check %s.", channel_attr, env_name)

        if self.settings.bot.auto_start:
            self._monitoring = True

        if self._summary_channel:
            await self._purge_summary_channel(self._summary_channel)

        self._start_background_tasks()
        logger.info("Logged in as %s", self.user)

    async def purge_bot_messages(
        self,
        channel: discord.TextChannel,
        *,
        max_messages: int = 1000,
    ) -> int:
        """Delete this bot's messages (Discord bulk purge, last 14 days)."""
        if not self.user:
            return 0
        bot_id = self.user.id
        total = 0
        try:
            while total < max_messages:
                batch = await channel.purge(
                    limit=min(100, max_messages - total),
                    check=lambda message: message.author.id == bot_id,
                )
                if not batch:
                    break
                total += len(batch)
                if len(batch) < 100:
                    break
        except discord.Forbidden:
            raise
        except Exception as exc:
            logger.warning("Purge failed in #%s: %s", channel.name, exc)
        return total

    async def _purge_summary_channel(self, channel: discord.TextChannel) -> None:
        self.summary_publisher.reset_message()
        try:
            deleted = await self.purge_bot_messages(channel)
            logger.info("Summary channel cleaned (%s old bot message(s) removed)", deleted)
        except discord.Forbidden:
            logger.warning("Cannot purge #summary-channel — bot needs Manage Messages permission")
        except Exception as exc:
            logger.warning("Summary channel purge failed: %s", exc)

    def _start_background_tasks(self) -> None:
        self._background_tasks.append(asyncio.create_task(self._exit_monitor_loop()))
        if self.realtime_scanner:
            self._background_tasks.append(asyncio.create_task(self.realtime_scanner.run_loop()))
        if self._summary_channel:
            self._background_tasks.append(asyncio.create_task(self._summary_loop()))
        if self.benzinga_feed:
            self._background_tasks.append(asyncio.create_task(self._benzinga_feed_loop()))
        if self.news_reader_server:
            self._background_tasks.append(asyncio.create_task(self.news_reader_server.start()))

    def _reader_base_url(self) -> str:
        if self.settings.news.reader_enabled and self.settings.news.reader_base_url:
            return self.settings.news.reader_base_url
        return ""

    def _article_public_url(self, article) -> str:
        reader_url = reader_article_url(self._reader_base_url(), getattr(article, "article_id", ""))
        return reader_url or getattr(article, "url", "") or ""

    async def _benzinga_feed_loop(self) -> None:
        if not self.benzinga_feed:
            return
        interval = max(10, self.settings.news.benzinga_poll_interval_seconds)
        logger.info("Benzinga news feed started (every %ss)", interval)
        while True:
            try:
                articles = await asyncio.to_thread(self.benzinga_feed.poll_new)
                for article in articles:
                    task = asyncio.create_task(self._ingest_benzinga_article(article))
                    self._background_tasks.append(task)
            except Exception as exc:
                logger.warning("Benzinga feed loop failed: %s", exc)
            await asyncio.sleep(interval)

    async def _benzinga_symbol_rows(
        self, symbols: list[str]
    ) -> list[tuple[str, float | None, str]]:
        if not symbols:
            return [("", None, "🇺🇸")]
        if not self.settings.finnhub_api_key:
            return [(symbol, None, "🇺🇸") for symbol in symbols]

        from bot.trading.market_data import fetch_company_profile_sync, fetch_float_shares_sync

        async def _row(symbol: str) -> tuple[str, float | None, str]:
            if not symbol:
                return ("", None, "🇺🇸")
            float_shares, profile = await asyncio.gather(
                asyncio.to_thread(
                    fetch_float_shares_sync,
                    symbol,
                    self.settings.finnhub_api_key,
                    massive_api_key=self.settings.benzinga_api_key,
                ),
                asyncio.to_thread(
                    fetch_company_profile_sync, symbol, self.settings.finnhub_api_key
                ),
            )
            _, country_flag = profile
            return (symbol, float_shares, country_flag or "🇺🇸")

        return list(await asyncio.gather(*[_row(symbol) for symbol in symbols]))

    async def _build_symbol_news_contexts(self, symbols: list[str]) -> dict[str, SymbolNewsContext]:
        """Trader context (MC, float, RVOL, runner, sector) for news lines."""
        if not symbols:
            return {}
        from bot.trading.market_data import (
            fetch_float_shares_sync,
            fetch_market_cap_sync,
            fetch_symbol_profile_sync,
        )
        from bot.trading.schedule import is_premarket_hours

        def _peak_time_et(peak_at: float) -> str:
            if not peak_at:
                return ""
            from datetime import datetime
            from zoneinfo import ZoneInfo

            return datetime.fromtimestamp(peak_at, tz=ZoneInfo("America/New_York")).strftime("%H:%M")

        async def _one(symbol: str) -> SymbolNewsContext:
            symbol = symbol.upper()
            if not symbol:
                return SymbolNewsContext(symbol="")
            float_shares = None
            profile_market_cap = None
            country_flag = "🇺🇸"
            sector = ""
            exchange = ""
            if self.settings.finnhub_api_key:
                float_shares, profile, mcap = await asyncio.gather(
                    asyncio.to_thread(
                        fetch_float_shares_sync,
                        symbol,
                        self.settings.finnhub_api_key,
                        massive_api_key=self.settings.benzinga_api_key,
                    ),
                    asyncio.to_thread(
                        fetch_symbol_profile_sync, symbol, self.settings.finnhub_api_key
                    ),
                    asyncio.to_thread(
                        fetch_market_cap_sync, symbol, self.settings.finnhub_api_key
                    ),
                )
                country_flag = profile.country_flag or "🇺🇸"
                sector = profile.sector
                exchange = profile.exchange
                profile_market_cap = profile.market_cap_usd or mcap
            runner = self.runner_history.get(symbol)
            cached = self._scan_detail_cache.get(symbol)
            price = None
            session_change_pct = None
            rvol = None
            turnover = None
            peak_rvol = None
            peak_rvol_at = ""
            if cached:
                scan = cached[0]
                price = scan.price
                session_change_pct = scan.session_change_pct
                rvol = scan.rvol
                turnover = scan.turnover_usd
                peak_rvol = scan.peak_rvol
                if scan.peak_rvol_at:
                    peak_rvol_at = scan.peak_rvol_at[:5] if len(scan.peak_rvol_at) >= 5 else scan.peak_rvol_at
            else:
                peak_record = self.scanner._peak_rvol_store.get(symbol)
                if peak_record:
                    peak_rvol = peak_record.peak_rvol or None
                    peak_rvol_at = _peak_time_et(peak_record.peak_at)
            session_turnover = turnover
            pm_turnover = turnover if is_premarket_hours() else None
            return SymbolNewsContext(
                symbol=symbol,
                float_shares=float_shares,
                market_cap_usd=profile_market_cap,
                country_flag=country_flag,
                sector=sector,
                exchange=exchange,
                rvol=rvol,
                peak_rvol=peak_rvol,
                peak_rvol_at=peak_rvol_at,
                price=price,
                session_change_pct=session_change_pct,
                session_turnover_usd=session_turnover,
                premarket_turnover_usd=pm_turnover,
                is_runner=runner is not None
                and (runner.stars > 0 or runner.times_seen >= 2),
                runner_stars=runner.stars if runner else 0,
            )

        contexts = await asyncio.gather(*[_one(symbol) for symbol in symbols if symbol])
        return {ctx.symbol: ctx for ctx in contexts}

    async def _news_cap_channels(self, symbols: list[str]) -> list[discord.TextChannel]:
        """Extra cap-split news channels based on the smallest-cap symbol.

        <$250M -> news-250m + news-600m. $250M-$600M -> news-600m only.
        All news always goes to the main news channel as well.
        """
        if not (self._news_250m_channel or self._news_600m_channel):
            return []
        if not self.settings.finnhub_api_key:
            return []
        from bot.trading.market_data import fetch_market_cap_sync

        caps = await asyncio.gather(
            *[
                asyncio.to_thread(fetch_market_cap_sync, symbol, self.settings.finnhub_api_key)
                for symbol in symbols
                if symbol
            ]
        )
        caps = [c for c in caps if c is not None and c > 0]
        if not caps:
            return []
        smallest = min(caps)
        cfg = self.settings.trading
        cap_250 = getattr(cfg, "news_250m_market_cap_usd", 0) or 0
        cap_600 = getattr(cfg, "news_600m_market_cap_usd", 0) or 0
        channels: list[discord.TextChannel] = []
        if self._news_600m_channel and cap_600 > 0 and smallest < cap_600:
            channels.append(self._news_600m_channel)
        if self._news_250m_channel and cap_250 > 0 and smallest < cap_250:
            channels.append(self._news_250m_channel)
        return channels

    def _news_intelligence_enabled(self) -> bool:
        return getattr(self.settings.news, "news_intelligence_enabled", True)

    def _impact_channels_ready(self) -> bool:
        return any(
            (
                self._news_all_channel,
                self._news_high_channel,
                self._news_medium_channel,
                self._news_low_channel,
                self._news_noise_channel,
            )
        )

    def _resolve_impact_channels(self, keys: frozenset[str]) -> list[discord.TextChannel]:
        mapping: dict[str, discord.TextChannel | None] = {
            "all_news": self._news_all_channel or self._news_channel,
            "high": self._news_high_channel,
            "medium": self._news_medium_channel,
            "low": self._news_low_channel,
            "noise": self._news_noise_channel,
        }
        seen: set[int] = set()
        channels: list[discord.TextChannel] = []
        for key in keys:
            channel = mapping.get(key)
            if channel and channel.id not in seen:
                seen.add(channel.id)
                channels.append(channel)
        return channels

    async def _post_benzinga_news(
        self,
        article,
        *,
        impact: NewsImpact | None = None,
        priority_line: str = "",
        sentiment: str = "",
        dilution_risk: bool | None = None,
        ai_output: NewsAIOutput | None = None,
    ) -> None:
        from bot.news.benzinga import BenzingaArticle
        from bot.news.ai_output import NewsAIOutput as _NewsAIOutput
        from bot.news.crowd_attention import compute_crowd_attention_score
        from bot.news.smart_alert import evaluate_smart_alert
        from bot.news.source_traceability import build_source_traceability
        from bot.news.timeline_evolution import record_timeline_event
        from datetime import datetime, timezone

        if not isinstance(article, BenzingaArticle):
            return
        if not self._news_channel and not self._impact_channels_ready():
            return
        if self.news_reader_store:
            await asyncio.to_thread(self.news_reader_store.save, article)

        # Buyer: general/world news (no stock symbol) goes to #world-news with a
        # short AI summary instead of the main per-ticker feed.
        if self._world_news_channel and not article.symbols:
            await self._post_world_news(article)
            return

        symbols = article.symbols or [""]
        news_cfg = self.settings.news
        filter_enabled = getattr(news_cfg, "news_filter_enabled", True)
        crypto_exclusive = getattr(news_cfg, "crypto_news_exclusive", True)
        intelligence = self._news_intelligence_enabled()
        timeline = getattr(news_cfg, "news_timeline_format", True)
        text = article.title if not article.body else f"{article.title}\n{article.body[:4000]}"
        if impact is None:
            impact = classify_impact(
                text,
                symbol=symbols[0] if symbols and symbols[0] else "",
                article_id=str(getattr(article, "article_id", "")),
                source="benzinga",
            )
        if dilution_risk is None:
            dilution_risk = impact.dilution_risk if impact else is_dilution_news(text)

        from bot.news.news_routing import is_crypto_news

        is_crypto = is_crypto_news(
            title=article.title,
            body=article.body,
            symbols=article.symbols,
        )

        try:
            contexts = await asyncio.wait_for(
                self._build_symbol_news_contexts([s for s in symbols if s]), timeout=5.0
            )
        except TimeoutError:
            logger.warning("Benzinga news context timeout for %s", symbols)
            contexts = {}

        caps = [c.market_cap_usd for c in contexts.values() if c.market_cap_usd]
        smallest_mcap = min(caps) if caps else None
        max_universe = float(
            getattr(news_cfg, "news_universe_max_market_cap_usd", 0)
            or self.settings.trading.scanner_max_market_cap_usd
        )

        if intelligence:
            impact_keys, skip_all = resolve_impact_post_targets(
                impact,
                news_filter_enabled=filter_enabled,
                out_of_universe=is_out_of_news_universe(smallest_mcap, max_universe),
                is_options_without_symbol=is_options_news(
                    title=article.title, body=article.body or ""
                )
                and not (article.symbols or []),
            )
            if skip_all:
                logger.info("Skipped news (intelligence): %s", article.title[:80])
                return
        else:
            post_main = True
            post_cap = True
            skip_all = False
            if filter_enabled:
                post_main, post_cap, skip_all = resolve_news_routing(
                    title=article.title,
                    body=article.body or "",
                    symbols=article.symbols or [],
                    smallest_market_cap_usd=smallest_mcap,
                    max_low_cap_usd=max_universe,
                    is_crypto=is_crypto,
                    impact=impact,
                    crypto_exclusive=crypto_exclusive,
                    intelligence_mode=False,
                )
                if skip_all:
                    logger.info("Skipped low-value news: %s", article.title[:80])
                    return

        try:
            symbol_rows = await asyncio.wait_for(self._benzinga_symbol_rows(symbols), timeout=5.0)
        except TimeoutError:
            logger.warning("Benzinga news metadata timeout for %s", symbols)
            symbol_rows = [(symbol, None, "🇺🇸") for symbol in symbols]

        reader_url = self._reader_base_url()
        first_detected = datetime.now(timezone.utc).isoformat()
        source_trace = build_source_traceability(
            article,
            first_detected_iso=first_detected,
            mirror_url=reader_article_url(reader_url, article.article_id),
            negated=bool(getattr(impact, "negated", False)) if impact else False,
        )
        ai_outputs: dict[str, _NewsAIOutput] = {}
        primary_sym = symbols[0].upper() if symbols and symbols[0] else ""
        if intelligence and timeline:
            for sym, ctx in contexts.items():
                base = ai_output
                if base is None:
                    continue
                if sym != primary_sym and len(symbols) > 1:
                    continue
                crowd = compute_crowd_attention_score(
                    impact_level=impact.level,
                    context=ctx,
                    repeated_pr=bool(getattr(impact, "repeated_pr", False)),
                )
                timeline_label = f"{impact.emoji} {impact.category or impact.catalyst_type or 'News'}"
                timeline_note = record_timeline_event(sym, timeline_label)
                smart = evaluate_smart_alert(impact, ctx, crowd_score=crowd, repeated_pr=impact.repeated_pr)
                ai_outputs[sym] = _NewsAIOutput(
                    impact_level=base.impact_level,
                    impact_emoji=base.impact_emoji,
                    sentiment=base.sentiment,
                    confidence=base.confidence,
                    dilution_risk=base.dilution_risk,
                    liquidity_risk=base.liquidity_risk,
                    category=base.category,
                    keyword=base.keyword,
                    summary=base.summary,
                    suggested_action=base.suggested_action,
                    catalyst_type=base.catalyst_type,
                    catalyst_tags=base.catalyst_tags,
                    crowd_attention_score=crowd,
                    smart_alert=smart,
                    timeline_note=timeline_note,
                )
            if ai_output and primary_sym and primary_sym not in ai_outputs:
                ctx = contexts.get(primary_sym)
                crowd = compute_crowd_attention_score(
                    impact_level=impact.level,
                    context=ctx,
                    repeated_pr=bool(getattr(impact, "repeated_pr", False)),
                )
                timeline_note = record_timeline_event(
                    primary_sym,
                    f"{impact.emoji} {impact.category or impact.catalyst_type or 'News'}",
                )
                smart = evaluate_smart_alert(impact, ctx, crowd_score=crowd, repeated_pr=impact.repeated_pr)
                ai_outputs[primary_sym] = _NewsAIOutput(
                    impact_level=ai_output.impact_level,
                    impact_emoji=ai_output.impact_emoji,
                    sentiment=ai_output.sentiment,
                    confidence=ai_output.confidence,
                    dilution_risk=ai_output.dilution_risk,
                    liquidity_risk=ai_output.liquidity_risk,
                    category=ai_output.category,
                    keyword=ai_output.keyword,
                    summary=ai_output.summary,
                    suggested_action=ai_output.suggested_action,
                    catalyst_type=ai_output.catalyst_type,
                    catalyst_tags=ai_output.catalyst_tags,
                    crowd_attention_score=crowd,
                    smart_alert=smart,
                    timeline_note=timeline_note,
                )
            blocks = build_timeline_news_blocks(
                article,
                symbol_rows=symbol_rows,
                reader_base_url=reader_url,
                contexts=contexts,
                impact=impact,
                sentiment=sentiment,
                dilution_risk=dilution_risk,
                ai_outputs=ai_outputs or None,
                source_trace=source_trace,
            )
        else:
            context_lines = {
                sym: build_trader_context_line(ctx, catalyst=impact.category)
                for sym, ctx in contexts.items()
            }
            blocks = build_benzinga_news_blocks(
                article,
                symbol_rows=symbol_rows,
                reader_base_url=reader_url,
                context_lines=context_lines,
                priority_line=priority_line,
            )
        if not blocks:
            return

        target_channels: list[discord.TextChannel] = []
        if is_crypto and crypto_exclusive and self._crypto_news_channel:
            target_channels = [self._crypto_news_channel]
        elif intelligence:
            target_channels = self._resolve_impact_channels(impact_keys)
        else:
            cap_channels: list[discord.TextChannel] = []
            if post_cap:
                try:
                    cap_channels = await asyncio.wait_for(
                        self._news_cap_channels(article.symbols or []), timeout=5.0
                    )
                except TimeoutError:
                    cap_channels = []
            if post_main and self._news_channel:
                target_channels.append(self._news_channel)
            for channel in cap_channels:
                if channel and channel not in target_channels:
                    target_channels.append(channel)
            if is_crypto and self._crypto_news_channel and self._crypto_news_channel not in target_channels:
                target_channels.append(self._crypto_news_channel)

        if not target_channels:
            return

        for block in blocks:
            content = f"{block}{_NEWS_GAP}"
            for channel in target_channels:
                try:
                    await channel.send(content, suppress_embeds=True)
                except Exception as exc:
                    logger.warning("Benzinga news send failed: %s", exc)
        for symbol in article.symbols:
            await self._maybe_send_potential_hit(symbol, article)

    async def _post_world_news(self, article) -> None:
        """Post no-symbol general news to #world-news with a short AI summary."""
        from bot.news.ai_sentiment import summarize_world_news

        title = article.title.strip()
        summary = ""
        impact = "neutral"
        if self.settings.news.openai_api_key and self.settings.news.ai_sentiment_enabled:
            try:
                summary, impact = await asyncio.wait_for(
                    summarize_world_news(
                        title,
                        api_key=self.settings.news.openai_api_key,
                        model=self.settings.news.openai_model,
                        article_text=article.body or "",
                    ),
                    timeout=12.0,
                )
            except (TimeoutError, Exception) as exc:
                logger.warning("World-news summary error: %s", exc)
        impact_emoji = {"positive": "🟢", "negative": "🔴", "neutral": "🟡"}.get(impact, "🟡")
        published_et = _format_published_et(article.published)
        link = self._article_public_url(article) or article.url

        # Format matches other news channels: time, then headline + Link,
        # then a colour-labelled AI summary line below the news.
        news_line = f"**{title}**"
        if link:
            news_line = f"{news_line} - [Link]({link})"
        lines: list[str] = []
        if published_et:
            lines.append(f"**{published_et}**")
        lines.append(news_line)
        if summary and summary.strip().lower() != title.lower():
            lines.append(f"{impact_emoji} {summary.strip()}")
        else:
            lines.append(f"{impact_emoji} AI summary unavailable")
        content = "\n".join(lines) + _NEWS_GAP
        try:
            await self._world_news_channel.send(content, suppress_embeds=True)
        except Exception as exc:
            logger.warning("World-news send failed: %s", exc)

    async def _analyze_benzinga_article(self, article):
        text = article.title if not article.body else f"{article.title}\n{article.body[:4000]}"
        return await self.analyzer.analyze_text_async(
            text,
            source="Benzinga",
            published=article.published or "Benzinga",
            message_id=f"bz:{article.article_id}",
            jump_url=self._article_public_url(article),
            headline=article.title,
            timing_key=f"bz:{article.article_id}",
        )

    async def _finalize_benzinga_ai(self, article, item) -> None:
        if item is None:
            return
        symbol = article.symbols[0] if article.symbols else ""
        if symbol:
            item.stock_symbol = symbol
        trade_msg = await self._process_item(item, timing_key=f"bz:{article.article_id}")
        await self.send_news_alert(item, trade_msg)
        logger.info("Benzinga article processed: %s", article.title[:80])

    async def _ingest_benzinga_article(self, article) -> None:
        from bot.news.benzinga import BenzingaArticle

        from bot.news.source_traceability import detect_source_key

        if not isinstance(article, BenzingaArticle):
            return
        try:
            item = await self._analyze_benzinga_article(article)
            text = article.title if not article.body else f"{article.title}\n{article.body[:4000]}"
            category = getattr(item, "news_category", "") if item else ""
            sentiment = getattr(item, "sentiment", "") if item else ""
            ai_reason = getattr(item, "ai_reason", "") if item else ""
            source_key = detect_source_key(
                source_name=article.source_name,
                url=article.url or article.original_url,
                text=text,
            )
            impact = classify_impact(
                text,
                category=category,
                sentiment=sentiment,
                symbol=article.symbols[0] if article.symbols else "",
                article_id=str(article.article_id),
                source=source_key,
            )
            from bot.news.ai_output import build_ai_output_from_rules, classify_news_ai_output

            ai_output = build_ai_output_from_rules(impact, sentiment=sentiment, ai_reason=ai_reason)
            news_cfg = self.settings.news
            if news_cfg.openai_api_key and news_cfg.ai_sentiment_enabled:
                try:
                    enriched = await asyncio.wait_for(
                        classify_news_ai_output(
                            headline=article.title,
                            article_text=article.body or "",
                            symbol=article.symbols[0] if article.symbols else "",
                            impact=impact,
                            api_key=news_cfg.openai_api_key,
                            model=news_cfg.openai_model,
                        ),
                        timeout=14.0,
                    )
                    if enriched:
                        ai_output = enriched
                except TimeoutError:
                    logger.warning("News AI output timeout for %s", article.title[:80])
            priority_line = build_priority_line(impact=impact, ai_reason=ai_output.summary or ai_reason)
            await self._post_benzinga_news(
                article,
                impact=impact,
                priority_line=priority_line,
                sentiment=ai_output.sentiment.lower() if ai_output.sentiment else sentiment,
                dilution_risk=impact.dilution_risk,
                ai_output=ai_output,
            )
            await self._finalize_benzinga_ai(article, item)
        except Exception as exc:
            logger.warning("Benzinga ingest failed: %s", exc)

    async def _summary_loop(self) -> None:
        interval = max(30, self.settings.trading.summary_interval_seconds)
        tick = max(5, self.settings.trading.summary_live_tick_seconds)
        elapsed = 0
        while True:
            try:
                if self._summary_channel:
                    if elapsed >= interval or not self.summary_publisher.has_data():
                        await self._refresh_summary_gainers()
                        await self.summary_publisher.publish(self._summary_channel)
                        elapsed = 0
                        await asyncio.sleep(1)
                        await self.summary_publisher.tick_footer(self._summary_channel)
                    else:
                        await self.summary_publisher.tick_footer(self._summary_channel)
            except Exception as exc:
                logger.warning("Summary publish failed: %s", exc)
            await asyncio.sleep(tick)
            elapsed += tick

    async def _refresh_summary_gainers(self) -> None:
        """Summary board: live market top gainers; watchlist symbols get ★ mark."""
        limit = self.settings.trading.summary_top_gainers_limit
        gainers = await asyncio.to_thread(
            fetch_market_top_gainers,
            self.settings.alpaca_api_key,
            self.settings.alpaca_secret_key,
            top=limit,
        )
        if not gainers:
            return

        scans: list[ScanResult] = []
        for candidate in gainers:
            scan = await asyncio.to_thread(self._scan_symbol_sync, candidate.symbol)
            if candidate.change_pct is not None:
                scan.session_change_pct = candidate.change_pct
            scans.append(scan)

        from bot.trading.market_data import fetch_float_shares_sync

        for scan in scans:
            if scan.float_shares and scan.float_shares > 0:
                continue
            shares = await asyncio.to_thread(
                fetch_float_shares_sync,
                scan.symbol,
                self.settings.finnhub_api_key,
                massive_api_key=self.settings.benzinga_api_key,
            )
            if shares:
                scan.float_shares = shares

        watchlist_symbols = {entry.symbol.upper() for entry in self.watchlist.active_entries()}
        self.summary_publisher.update_scans(
            scans,
            watchlist_symbols=watchlist_symbols,
            market_ordered=True,
        )

    async def _exit_monitor_loop(self) -> None:
        cfg = self.settings.trading
        if not cfg.exit_manager_enabled and not cfg.ai_exit_enabled:
            return
        while True:
            try:
                messages: list[str] = []
                if cfg.exit_manager_enabled or cfg.ai_exit_enabled:
                    messages.extend(await self.trading_engine.check_grid_exits())
                if messages and self._alert_channel:
                    body = "\n".join(messages[:8])
                    await self._alert_channel.send(f"📤 **Exit actions**\n{body}")
            except Exception as exc:
                logger.warning("Exit monitor failed: %s", exc)
            await asyncio.sleep(30)

    def _scan_symbol_sync(self, symbol: str) -> ScanResult:
        mosquito_signal = self.volume_tracker.get_recent(symbol)
        return self.scanner.scan(symbol, mosquito_signal=mosquito_signal, news_bullish=False)

    def _collect_scan_symbols(self) -> list[str]:
        symbols: list[str] = []
        for entry in self.watchlist.active_entries():
            if entry.symbol not in symbols:
                symbols.append(entry.symbol)
        for runner in self.runner_history.active_runners()[:50]:
            if runner.symbol not in symbols:
                symbols.append(runner.symbol)
                self.historical_watchlist.add(runner.symbol, source="runner", note=runner.notes)
        for symbol in self.historical_watchlist.symbols():
            if symbol not in symbols:
                symbols.append(symbol)
        return symbols[: self.settings.trading.historical_watchlist_max_entries]

    def _watchlist_activity_for(self, symbol: str) -> str:
        import time

        symbol = symbol.upper()
        entry = self.watchlist.get_entry(symbol)
        if entry:
            days = max(0, int((time.time() - entry.added_at) / 86400))
            status = "triggered" if entry.triggered else "waiting breakout"
            return f"AI watchlist · {status} · day {days}"
        if symbol in self.historical_watchlist.symbols():
            return "Historical runner pool"
        if self.runner_history.get(symbol):
            return "Runner history tracked"
        return "None"

    def _track_historical_symbol(self, symbol: str, *, source: str, note: str = "") -> None:
        if symbol:
            self.historical_watchlist.add(symbol, source=source, note=note)

    def _abort_symbol_on_bad_news(self, symbol: str) -> None:
        if not symbol or not self.settings.trading.remove_watchlist_on_bad_news:
            return
        self.watchlist.remove(symbol)
        self.historical_watchlist.remove(symbol)

    def _fetch_universe_symbols(self) -> list[str]:
        cfg = self.settings.trading
        universe = fetch_universe_symbols(
            self.settings.alpaca_api_key,
            self.settings.alpaca_secret_key,
            most_actives_top=cfg.universe_most_actives_top,
            movers_top=cfg.universe_movers_top,
            min_price=cfg.scanner_min_price,
            max_price=cfg.scanner_max_price,
        )
        return universe.symbols

    def _scan_for_reader(self, symbol: str):
        """Sync scan lookup for the reader server's /scan/{symbol} page."""
        symbol = symbol.upper()
        cached = self._scan_detail_cache.get(symbol)
        if cached:
            return cached[0]
        try:
            return self.scanner.scan(symbol)
        except Exception:
            return None

    def _scan_public_url(self, symbol: str) -> str:
        base = self._reader_base_url()
        if not base or not symbol:
            return ""
        return f"{base}/scan/{symbol.upper()}"

    async def _pct_from_52w_low(self, scan: ScanResult) -> float | None:
        if not scan.symbol or not self.settings.finnhub_api_key or not scan.price:
            return None
        from bot.trading.market_data import fetch_52week_low_sync

        low = await asyncio.to_thread(
            fetch_52week_low_sync, scan.symbol, self.settings.finnhub_api_key
        )
        if not low or low <= 0:
            return None
        return (scan.price / low - 1) * 100

    def _meets_turnover_threshold(self, scan: ScanResult) -> bool:
        from bot.trading.scanner_gates import meets_turnover_threshold

        return meets_turnover_threshold(scan, self.settings.trading)

    @staticmethod
    def _total_change_pct(scan: ScanResult) -> float | None:
        from bot.trading.scanner_gates import total_change_pct

        return total_change_pct(scan)

    @staticmethod
    def _session_range_pct(scan: ScanResult) -> float | None:
        from bot.trading.scanner_gates import session_range_pct

        return session_range_pct(scan)

    def _qualifies_scanner(self, scan: ScanResult) -> bool:
        from bot.trading.scanner_gates import qualifies_scanner_alert

        return qualifies_scanner_alert(
            scan,
            self.settings.trading,
            min_score=self._scanner_min_score(scan),
        )

    def _scanner_mute_channel(self) -> discord.TextChannel | None:
        return (
            self._mc_3b_scanner_channel
            or self._mc_600m_scanner_channel
            or self._watchlist_channel
        )

    def _cap_channels(self, scan: ScanResult, kind: str) -> list[discord.TextChannel]:
        """Route an alert by market cap into the cap-specific channel.

        kind = "scanner" or "potential".
        <$600M  -> 600m channel + 3b channel (micro is also low-cap).
        $600M-$3B / unknown -> 3b channel only.
        >$3B    -> nothing (out of low-cap focus).
        Falls back to legacy channels only when no cap channels are configured.
        """
        if kind == "potential":
            ch_600m = self._mc_600m_potential_channel
            ch_3b = self._mc_3b_potential_channel
            fallback = self._potential_channel
        else:
            ch_600m = self._mc_600m_scanner_channel
            ch_3b = self._mc_3b_scanner_channel
            fallback = self._watchlist_channel

        if ch_600m or ch_3b:
            cfg = self.settings.trading
            mcap = scan.market_cap_usd
            max_cap = getattr(cfg, "scanner_max_market_cap_usd", 0) or 0
            micro_cap = getattr(cfg, "scanner_micro_cap_market_cap_usd", 0) or 0
            channels: list[discord.TextChannel] = []
            if ch_3b and (max_cap <= 0 or mcap is None or mcap < max_cap):
                channels.append(ch_3b)
            if ch_600m and mcap is not None and micro_cap > 0 and mcap < micro_cap:
                channels.append(ch_600m)
            return channels
        return [fallback] if fallback else []

    async def _send_scan_alert(
        self,
        scan: ScanResult,
        *,
        title_prefix: str = "Realtime Scanner",
    ) -> None:
        import time

        target_channels = self._cap_channels(scan, "scanner")
        if not target_channels:
            return
        if not self._qualifies_scanner(scan):
            return

        if not self._watchlist_automute.can_send():
            await self._maybe_notify_watchlist_mute()
            return
        if self._watchlist_batch_sent >= self.settings.trading.watchlist_max_alerts_per_batch:
            return
        now = time.time()
        cooldown = self.settings.trading.watchlist_alert_cooldown_seconds
        if now - self._watchlist_recent.get(scan.symbol, 0) < cooldown:
            return

        min_score = self._scanner_min_score(scan)
        self._scan_detail_cache[scan.symbol.upper()] = (scan, min_score)

        country_flag = "🇺🇸"
        if scan.symbol and self.settings.finnhub_api_key:
            from bot.trading.market_data import fetch_company_profile_sync

            _, country_flag = await asyncio.to_thread(
                fetch_company_profile_sync, scan.symbol, self.settings.finnhub_api_key
            )

        _, news_url = self._related_news_for_symbol(scan.symbol)
        pct_low = await self._pct_from_52w_low(scan)
        content = build_watchlist_monitor_line(
            scan, country_flag=country_flag, news_url=news_url, pct_from_52w_low=pct_low
        )
        for channel in target_channels:
            await channel.send(content=f"{content}{_NEWS_GAP}", suppress_embeds=True)

        self._watchlist_recent[scan.symbol] = time.time()
        self._watchlist_automute.record_send()
        self._watchlist_batch_sent += 1

    def reset_watchlist_batch_counter(self) -> None:
        self._watchlist_batch_sent = 0

    def reset_potential_batch_counter(self) -> None:
        self._potential_batch_sent = 0

    def _related_news_for_symbol(self, symbol: str) -> tuple[str, str]:
        symbol = symbol.upper()
        potential = self.potential_store.get(symbol)
        if potential and (potential.related_news_title or potential.related_news_url):
            return potential.related_news_title, potential.related_news_url
        for entry in self.watchlist.active_entries():
            if entry.symbol == symbol:
                return entry.title, entry.link
        return "", ""

    def _qualifies_potential(self, scan: ScanResult) -> bool:
        cfg = self.settings.trading
        if not cfg.potential_enabled:
            return False
        if scan.score < cfg.potential_min_score:
            return False
        pct = scan.session_change_pct
        if pct is None:
            return False
        if pct < cfg.potential_min_session_change_pct:
            return False
        if pct >= cfg.potential_max_session_change_pct:
            return False
        rvol = scan.current_rvol or scan.rvol or 0.0
        liquidity = float(scan.liquidity_expansion or 0)
        if rvol < 1.5 and liquidity < 35:
            return False
        if not self._meets_turnover_threshold(scan):
            return False
        return True

    def _has_potential_channel(self) -> bool:
        return bool(self._mc_600m_potential_channel or self._mc_3b_potential_channel or self._potential_channel)

    async def _process_potential_batch(self, scans: list[ScanResult]) -> None:
        if not self._has_potential_channel() or not self.settings.trading.potential_enabled:
            return
        import time

        candidates = [scan for scan in scans if self._qualifies_potential(scan)]
        if not candidates:
            return
        candidates.sort(
            key=lambda scan: (
                scan.score,
                scan.liquidity_expansion or 0,
                scan.current_rvol or scan.rvol or 0,
            ),
            reverse=True,
        )
        limit = max(1, self.settings.trading.potential_max_alerts_per_batch)
        now = time.time()
        cooldown = self.settings.trading.potential_alert_cooldown_seconds
        for scan in candidates[:limit]:
            if self._potential_batch_sent >= limit:
                break
            if now - self._potential_recent.get(scan.symbol, 0) < cooldown:
                continue
            self.potential_store.add_or_update(
                symbol=scan.symbol,
                score=scan.score,
                grade=scan.grade,
                session_change_pct=scan.session_change_pct,
                reasons=scan.reasons[:4] or [f"Score {scan.score}/100"],
            )
            await self._send_potential_alert(scan)
            self._potential_recent[scan.symbol] = now
            self._potential_batch_sent += 1

    async def _send_potential_alert(self, scan: ScanResult) -> None:
        target_channels = self._cap_channels(scan, "potential")
        if not target_channels:
            return
        min_score = self._scanner_min_score(scan)
        self._scan_detail_cache[scan.symbol.upper()] = (scan, min_score)
        country_flag = "🇺🇸"
        if scan.symbol and self.settings.finnhub_api_key:
            from bot.trading.market_data import fetch_company_profile_sync

            _, country_flag = await asyncio.to_thread(
                fetch_company_profile_sync, scan.symbol, self.settings.finnhub_api_key
            )
        _, news_url = self._related_news_for_symbol(scan.symbol)
        pct_low = await self._pct_from_52w_low(scan)
        content = build_watchlist_monitor_line(
            scan,
            country_flag=country_flag,
            news_url=news_url,
            pct_from_52w_low=pct_low,
            details_url=self._scan_public_url(scan.symbol),
        )
        for channel in target_channels:
            await channel.send(content=f"{content}{_NEWS_GAP}", suppress_embeds=True)

    async def _maybe_send_potential_hit(self, symbol: str, article) -> None:
        if not symbol or not self.potential_store.has_active(symbol):
            return
        entry = self.potential_store.attach_news(
            symbol,
            title=article.title,
            url=self._article_public_url(article),
        )
        if not entry or not self._alert_channel:
            return
        self.potential_store.mark_hit(symbol)
        embed = discord.Embed(
            title=f"🎯 HIT — {symbol.upper()}",
            description=(
                f"Our **potential list** flagged `{symbol.upper()}` before this headline landed.\n\n"
                f"**{article.title[:900]}**"
            ),
            color=discord.Color.green(),
            url=self._article_public_url(article) or None,
        )
        embed.add_field(name="Potential Score", value=f"{entry.grade} {entry.score}/100", inline=True)
        if entry.session_change_pct is not None:
            embed.add_field(name="Move at flag", value=f"{entry.session_change_pct:+.1f}%", inline=True)
        embed.set_footer(text=f"{self.settings.bot.name} · potential match")
        await self._alert_channel.send(embed=embed)
        logger.info("Potential HIT alert for %s", symbol)

    async def _maybe_notify_watchlist_mute(self) -> None:
        import time

        channel = self._scanner_mute_channel()
        if not channel:
            return
        now = time.time()
        if now - self._watchlist_mute_notice_at < 300:
            return
        remaining = self._watchlist_automute.muted_seconds_remaining
        if remaining <= 0:
            return
        await channel.send(
            f"🔇 **Watchlist auto-muted** — too many alerts. Resuming in ~{remaining // 60 or 1} min."
        )
        self._watchlist_mute_notice_at = now
        logger.info("Watchlist auto-muted for %ss", remaining)

    async def _on_scan_batch(self, scans: list[ScanResult]) -> None:
        self.reset_watchlist_batch_counter()
        self.reset_potential_batch_counter()
        await self._process_potential_batch(scans)
        if not self.settings.trading.mosquito_alerts_enabled:
            return
        candidates = [scan for scan in scans if self._qualifies_mosquito(scan)]
        if not candidates:
            return
        candidates.sort(key=self._mosquito_rank_score, reverse=True)
        limit = max(1, self.settings.trading.mosquito_max_alerts_per_batch)
        for scan in candidates[:limit]:
            await self._maybe_send_mosquito_alert(scan)

    @staticmethod
    def _mosquito_rank_score(scan: ScanResult) -> float:
        rvol = scan.current_rvol or scan.rvol or 0.0
        expansion = scan.expansion.volume_expansion_pct if scan.expansion else 0.0
        liquidity = float(scan.liquidity_expansion or 0)
        nhod_bonus = 10.0 if scan.mosquito_nhod else 0.0
        return rvol * 10 + max(expansion, 0) + liquidity + nhod_bonus

    def _qualifies_mosquito(self, scan: ScanResult) -> bool:
        cfg = self.settings.trading
        rvol = scan.current_rvol or scan.rvol
        if rvol is not None and rvol >= max(cfg.mosquito_min_relative_volume, 2.5):
            return True
        if scan.expansion and scan.expansion.volume_expansion_pct is not None:
            if scan.expansion.volume_expansion_pct >= 50 and rvol is not None and rvol >= 2.0:
                return True
        if scan.mosquito_nhod and rvol is not None and rvol >= 2.0:
            return True
        return False

    async def _maybe_send_mosquito_alert(self, scan: ScanResult) -> None:
        if not self._mosquito_channel or not self._qualifies_mosquito(scan):
            return
        import time

        if not self._mosquito_automute.can_send():
            await self._maybe_notify_mosquito_mute()
            return

        now = time.time()
        cooldown = self.settings.trading.mosquito_alert_cooldown_seconds
        if now - self._mosquito_recent.get(scan.symbol, 0) < cooldown:
            return
        content, _ = build_mosquito_alert(scan, bot_name=self.settings.bot.name)
        await self._mosquito_channel.send(content=content)
        self._mosquito_recent[scan.symbol] = now
        self._mosquito_automute.record_send()

    async def _maybe_notify_mosquito_mute(self) -> None:
        import time

        if not self._mosquito_channel:
            return
        now = time.time()
        if now - self._mosquito_mute_notice_at < 300:
            return
        remaining = self._mosquito_automute.muted_seconds_remaining
        if remaining <= 0:
            return
        await self._mosquito_channel.send(
            f"🔇 **Mosquito auto-muted** — too many alerts. Resuming in ~{remaining // 60 or 1} min."
        )
        self._mosquito_mute_notice_at = now
        logger.info("Mosquito auto-muted for %ss", remaining)

    async def _send_realtime_alert(self, scan: ScanResult) -> None:
        await self._send_scan_alert(scan, title_prefix="Realtime Scanner")

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

    def _collect_image_urls(self, message: discord.Message) -> list[str]:
        urls: list[str] = []
        for attachment in message.attachments:
            content_type = (attachment.content_type or "").lower()
            if content_type.startswith("image/") or attachment.url.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                urls.append(attachment.url)
        for embed in message.embeds:
            if embed.image and embed.image.url:
                urls.append(embed.image.url)
            if embed.thumbnail and embed.thumbnail.url:
                urls.append(embed.thumbnail.url)
        return list(dict.fromkeys(urls))

    def _extract_urls_from_message(self, message: discord.Message) -> list[str]:
        return self._extract_allowed_urls(self._collect_message_text(message))

    def _extract_allowed_urls(self, text: str) -> list[str]:
        domains = self.settings.news.allowed_url_domains
        return [url for url in extract_urls(text) if is_allowed_url(url, domains)]

    def _embed_headline_for_url(self, message: discord.Message, url: str) -> str:
        """Use Discord embed title/description when the block text lacks a headline."""
        if not url:
            return ""

        normalized_url = url.rstrip("/")
        for embed in message.embeds:
            embed_url = (embed.url or "").rstrip("/")
            if embed_url and (embed_url == normalized_url or normalized_url in embed_url or embed_url in normalized_url):
                for part in (embed.title, embed.description):
                    if part and len(part.strip()) >= 12:
                        return part.strip()

        for embed in message.embeds:
            blob = "\n".join(part for part in (embed.title, embed.description, embed.url) if part)
            if normalized_url in blob:
                for part in (embed.title, embed.description):
                    if part and len(part.strip()) >= 12:
                        return part.strip()
        return ""

    def _resolve_block_headline(
        self,
        block: str,
        message: discord.Message | None,
        url: str | None,
    ) -> str:
        headline = extract_nuntio_headline(block) or self.analyzer.extract_headline(block)
        if message and url and (not headline or len(headline) < 12):
            embed_headline = self._embed_headline_for_url(message, url)
            if embed_headline:
                headline = embed_headline
        return headline

    async def _analyze_block(
        self,
        block: str,
        *,
        source: str,
        published: str,
        message_id: str,
        jump_url: str,
        message: discord.Message | None = None,
        url: str | None = None,
        timing_key: str = "",
    ) -> NewsItem | None:
        symbol = extract_stock_symbol(block)
        headline = self._resolve_block_headline(block, message, url)
        item = await self.analyzer.analyze_text_async(
            block,
            source=source,
            published=published,
            message_id=message_id,
            jump_url=jump_url,
            headline=headline,
            timing_key=timing_key,
        )
        if not item:
            return None
        if symbol:
            item.stock_symbol = symbol
        if url:
            item.link = url
        if headline and (not item.title or len(item.title) < 12):
            item.title = headline[:300]
        return item

    def _semi_automated(self) -> bool:
        cfg = self.settings.trading
        return cfg.semi_automated_mode and not cfg.auto_trade_on_signal

    async def _scan_symbol(
        self,
        symbol: str,
        *,
        mosquito_signal: VolumeSignal | None = None,
        news_bullish: bool = False,
    ) -> ScanResult:
        return await asyncio.to_thread(
            self.scanner.scan,
            symbol,
            mosquito_signal=mosquito_signal,
            news_bullish=news_bullish,
        )

    def _scanner_min_score(self, scan: ScanResult) -> int:
        return _resolve_min_score(
            scan,
            self.settings.trading.scanner_min_alert_score,
            self.settings.trading.scanner_profiles,
        )

    def _format_scan_action(self, scan: ScanResult) -> str:
        return format_scan_summary(scan, min_score=self._scanner_min_score(scan))

    async def _process_item(self, item: NewsItem, timing_key: str = "") -> str | None:
        key = timing_key or item.link
        if key:
            mark_news_if_absent(key)
            mark_step(key, "analyze")

        if (
            self.settings.trading.mosquito_volume_filter_enabled
            and item.sentiment == "bullish"
            and item.stock_symbol
            and self._semi_automated()
        ):
            volume_signal = self.volume_tracker.get_recent(item.stock_symbol)
            if self.settings.trading.watchlist_mode_enabled and not volume_signal:
                entry = self.watchlist.add_or_update(
                    symbol=item.stock_symbol,
                    title=item.title,
                    ai_reason=item.ai_reason,
                    source=item.source,
                    link=item.link,
                    baseline_signal=volume_signal,
                )
                self._track_historical_symbol(
                    item.stock_symbol,
                    source="ai-news",
                    note=item.ai_reason,
                )
                item.sentiment = "neutral"
                item.ai_reason = "AI: bullish news added to watchlist"
                trade_msg = (
                    f"Watchlist — waiting for mosquito breakout "
                    f"({self.settings.trading.watchlist_volume_increase_percent:g}% volume "
                    f"or {self.settings.trading.watchlist_price_increase_percent:g}% price)"
                )
                await self._send_watchlist_update(entry, trade_msg)
                if item.stock_symbol:
                    item.daily_volume = await asyncio.to_thread(
                        self.trading_engine.get_daily_volume_for_symbol,
                        item.stock_symbol,
                    )
                if key:
                    log_trade_speed(key, symbol=item.stock_symbol, action="watchlist")
                return trade_msg

            scan = await self._scan_symbol(
                item.stock_symbol,
                mosquito_signal=volume_signal,
                news_bullish=True,
            )
            item.daily_volume = scan.daily_volume
            trade_msg = self._format_scan_action(scan)
            if scan.score < self.settings.trading.scanner_min_alert_score:
                item.sentiment = "neutral"
                item.ai_reason = f"{item.ai_reason}; scanner score {scan.score}/100"
            if key:
                log_trade_speed(key, symbol=item.stock_symbol, action=f"scan-{scan.grade}")
            return trade_msg

        if item.sentiment == "ignored":
            if item.stock_symbol:
                self._abort_symbol_on_bad_news(item.stock_symbol)
            trade_result = await self.trading_engine.process_signal(
                item.sentiment,
                symbol=item.stock_symbol,
                text=item.title,
            )
            trade_msg = trade_result.message if trade_result else None
            if trade_msg and item.stock_symbol and self.settings.trading.sell_position_on_bad_news:
                trade_msg = f"News abort — {trade_msg}"
            if key:
                log_trade_speed(key, symbol=item.stock_symbol, action="abort")
            return trade_msg

        if (
            self.settings.trading.mosquito_volume_filter_enabled
            and item.sentiment == "bullish"
            and item.stock_symbol
        ):
            volume_signal = self.volume_tracker.get_recent(item.stock_symbol)
            if self.settings.trading.watchlist_mode_enabled:
                entry = self.watchlist.add_or_update(
                    symbol=item.stock_symbol,
                    title=item.title,
                    ai_reason=item.ai_reason,
                    source=item.source,
                    link=item.link,
                    baseline_signal=volume_signal,
                )
                self._track_historical_symbol(
                    item.stock_symbol,
                    source="ai-news",
                    note=item.ai_reason,
                )
                item.sentiment = "neutral"
                item.ai_reason = "AI: bullish news added to watchlist"
                trade_msg = (
                    f"Watchlist — waiting for mosquito breakout "
                    f"({self.settings.trading.watchlist_volume_increase_percent:g}% volume "
                    f"or {self.settings.trading.watchlist_price_increase_percent:g}% price)"
                )
                await self._send_watchlist_update(entry, trade_msg)
                if item.stock_symbol:
                    item.daily_volume = await asyncio.to_thread(
                        self.trading_engine.get_daily_volume_for_symbol,
                        item.stock_symbol,
                    )
                if key:
                    log_trade_speed(key, symbol=item.stock_symbol, action="watchlist")
                return trade_msg

            if not volume_signal:
                item.sentiment = "neutral"
                item.ai_reason = "AI: waiting for mosquito volume confirmation"
                trade_msg = "No trade — no recent mosquito money-flow/volume signal"
                if item.stock_symbol:
                    item.daily_volume = await asyncio.to_thread(
                        self.trading_engine.get_daily_volume_for_symbol,
                        item.stock_symbol,
                    )
                if key:
                    log_trade_speed(key, symbol=item.stock_symbol, action="volume-wait")
                return trade_msg
            item.ai_reason = f"{item.ai_reason}; mosquito volume confirmed ({volume_signal.value:,.0f})"

        trade_result = await self.trading_engine.process_signal(
            item.sentiment,
            symbol=item.stock_symbol,
            text=item.title,
        )
        trade_msg = trade_result.message if trade_result else None

        if trade_result and trade_result.daily_volume is not None:
            item.daily_volume = trade_result.daily_volume
        elif item.stock_symbol:
            item.daily_volume = await asyncio.to_thread(
                self.trading_engine.get_daily_volume_for_symbol,
                item.stock_symbol,
            )

        if item.sentiment == "neutral" and not trade_msg:
            trade_msg = f"No trade — {item.ai_reason or 'AI: no catalyst'}"

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

    async def _send_watchlist_update(self, entry: WatchEntry, note: str) -> None:
        _ = note
        volume_signal = self.volume_tracker.get_recent(entry.symbol)
        scan = await self._scan_symbol(
            entry.symbol,
            mosquito_signal=volume_signal,
            news_bullish=True,
        )
        await self._send_scan_alert(scan, title_prefix="Watchlist")

    async def _process_watchlist_triggers(self, signals: list[VolumeSignal]) -> None:
        for signal in signals:
            trigger = self.watchlist.check_signal(signal)
            if not trigger:
                continue
            await self._execute_watchlist_trigger(trigger)

    async def _execute_watchlist_trigger(self, trigger: WatchTrigger) -> None:
        entry = trigger.entry
        msg = (
            f"Watchlist trigger — {trigger.reason}; "
            f"mosquito {trigger.signal.label}"
        )
        if self._semi_automated():
            scan = await self._scan_symbol(
                entry.symbol,
                mosquito_signal=trigger.signal,
                news_bullish=True,
            )
            await self._send_scan_alert(scan, title_prefix="Watchlist Trigger")
            logger.info(
                "Watchlist trigger %s — %s — %s",
                entry.symbol,
                msg,
                self._format_scan_action(scan),
            )
            return

        trade_result = await self.trading_engine.process_signal(
            "bullish",
            symbol=entry.symbol,
            text=entry.title,
        )
        trade_msg = trade_result.message if trade_result else "No trade result"
        channel = self._watchlist_channel or self._alert_channel
        if channel:
            await channel.send(
                f"🚀 **Watchlist Trigger** `{entry.symbol}`\n"
                f"{msg}\n"
                f"Trade: {trade_msg}"
            )
        logger.info("Watchlist trigger %s — %s — %s", entry.symbol, msg, trade_msg)

    async def _process_news_message(self, message: discord.Message, *, source: str) -> int:
        """Process every ticker block in a message (URL fetch + Discord text)."""
        text = self._collect_message_text(message)
        if not text.strip():
            logger.warning("Skip message %s — empty content", message.id)
            return 0

        if self.settings.trading.mosquito_volume_filter_enabled:
            volume_signals = self.volume_tracker.update_from_text(text)
            if not volume_signals:
                image_text = await asyncio.to_thread(
                    analyze_mosquito_image_urls,
                    self._collect_image_urls(message),
                    api_key=self.settings.news.openai_api_key,
                    model=self.settings.news.openai_model,
                )
                if image_text:
                    volume_signals = self.volume_tracker.update_from_text(image_text)
            if volume_signals:
                symbols = ", ".join(signal.label for signal in volume_signals[:8])
                logger.info("Mosquito volume signal stored: %s", symbols)
                await self._process_watchlist_triggers(volume_signals)
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
                    block=block,
                    timing_key=url or dedupe_key,
                )
                if item:
                    self._processed_messages.add(f"url:{url}")
                    if symbol:
                        item.stock_symbol = symbol
                    elif not item.stock_symbol:
                        item.stock_symbol = extract_stock_symbol(block)

            if not item:
                timing_key = url or dedupe_key
                item = await self._analyze_block(
                    block,
                    source=source,
                    published=published,
                    message_id=str(message.id),
                    jump_url=message.jump_url,
                    message=message,
                    url=url,
                    timing_key=timing_key,
                )

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
                item.ai_reason,
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
        block: str = "",
        timing_key: str = "",
    ) -> NewsItem | None:
        key = timing_key or url
        try:
            title, body = await fetch_article(url)
            mark_step(key, "fetch")
        except UrlFetchError as exc:
            logger.warning("URL fetch failed for %s: %s — using Discord block fallback", url, exc)
            if message and block.strip():
                published = message.created_at.strftime("%Y-%m-%d %H:%M UTC")
                item = await self._analyze_block(
                    block,
                    source=source or "news URL",
                    published=published,
                    message_id=message_id,
                    jump_url=message.jump_url,
                    message=message,
                    url=url,
                    timing_key=key,
                )
                if item:
                    return item
            if message:
                published = message.created_at.strftime("%Y-%m-%d %H:%M UTC")
                items = await self._message_to_items_async(message, source=source, timing_key=key)
                for item in items:
                    symbol = item.stock_symbol or extract_stock_symbol(item.title)
                    if symbol:
                        item.stock_symbol = symbol
                    item.link = url
                    return item
            return None

        preview = title if title else body[:300]
        item = await self.analyzer.analyze_article_async(
            preview,
            body,
            url=url,
            source=source,
            message_id=message_id,
            timing_key=key,
        )
        if item and not item.stock_symbol:
            item.stock_symbol = extract_stock_symbol(f"{title}\n{body}")
        if item and message and block.strip():
            block_headline = self._resolve_block_headline(block, message, url)
            if block_headline and len(block_headline) > len(item.title or ""):
                item.title = block_headline[:300]
        return item

    async def process_news_url(self, url: str, user: discord.User | discord.Member) -> NewsItem | None:
        if not is_allowed_url(url, self.settings.news.allowed_url_domains):
            return None
        return await self._url_to_item(
            url,
            source=f"/news by {user.display_name}",
            message_id=f"cmd:{url}",
        )

    async def _message_to_items_async(
        self,
        message: discord.Message,
        *,
        source: str,
        timing_key: str = "",
    ) -> list[NewsItem]:
        text = self._collect_message_text(message)
        published = message.created_at.strftime("%Y-%m-%d %H:%M UTC")
        items: list[NewsItem] = []

        for block in split_news_blocks(text):
            block_urls = self._extract_allowed_urls(block)
            url = block_urls[0] if block_urls else None
            item = await self._analyze_block(
                block,
                source=source,
                published=published,
                message_id=str(message.id),
                jump_url=message.jump_url,
                message=message,
                url=url,
                timing_key=timing_key,
            )
            if not item:
                continue
            symbol = extract_stock_symbol(block)
            if symbol:
                item.stock_symbol = symbol
            items.append(item)
        return items

    @staticmethod
    def _is_trade_action(trade_msg: str | None) -> bool:
        """True only for real trade/exit actions (buyer: alert channel must not
        duplicate the news + AI line that already shows in #news)."""
        if not trade_msg:
            return False
        low = trade_msg.lower()
        skip_tokens = (
            "no trade",
            "watchlist",
            "waiting for",
            "scanner score",
            "below threshold",
            "manual confirm",
        )
        return not any(token in low for token in skip_tokens)

    async def send_news_alert(self, item: NewsItem, trade_msg: str | None = None) -> None:
        if not self._alert_channel:
            return

        # Alert channel is reserved for actual trade/exit actions; plain news
        # analysis is already posted (with AI line) in the news channel.
        if not self._is_trade_action(trade_msg):
            return

        category_colors = {
            "Major Catalyst": discord.Color.green(),
            "Earnings": discord.Color.from_rgb(46, 204, 113),
            "FDA / Biotech Catalyst": discord.Color.from_rgb(52, 152, 219),
            "Contract Announcement": discord.Color.from_rgb(41, 128, 185),
            "Partnership": discord.Color.from_rgb(26, 188, 156),
            "Public Offering": discord.Color.orange(),
            "Reverse Split": discord.Color.red(),
            "Ordinary News": discord.Color.gold(),
            "No Clear Catalyst": discord.Color.light_grey(),
        }

        if item.sentiment == "bullish":
            emoji = "🟢"
        elif item.sentiment == "ignored":
            emoji = "⚪"
        elif item.sentiment == "neutral":
            emoji = "🟡"
        else:
            emoji = "🔴"

        color = category_colors.get(item.news_category, discord.Color.gold())

        embed = discord.Embed(
            title=f"{emoji} {item.news_category}",
            description=item.title[:4096],
            color=color,
            url=item.link or None,
        )
        embed.add_field(name="News Category", value=item.news_category, inline=True)
        embed.add_field(name="Sentiment", value=item.sentiment.upper(), inline=True)
        embed.add_field(name="Source", value=item.source, inline=True)
        embed.add_field(name="AI Says", value=item.ai_reason, inline=False)
        if item.daily_volume is not None:
            embed.add_field(name="Volume", value=f"{item.daily_volume:,} daily", inline=True)
        if self.analyzer.config.ai_sentiment_enabled and self.analyzer.config.openai_api_key:
            embed.set_footer(text=f"{self.settings.bot.name} · OpenAI analysis")
        else:
            embed.set_footer(text=self.settings.bot.name)
        if item.stock_symbol:
            embed.add_field(name="Symbol", value=item.stock_symbol, inline=True)
        embed.add_field(name="Published", value=item.published, inline=False)

        if item.sentiment == "ignored":
            action = trade_msg or "No trade — news abort (orders cancelled, position sold if open)"
            embed.add_field(name="Action", value=action, inline=False)
        elif item.sentiment == "neutral":
            action = trade_msg or f"No trade — {item.ai_reason or 'AI: no catalyst'}"
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
            title=f"📖 {self.bot.settings.bot.name} Commands",
            description="Use the commands below:",
            color=discord.Color.blue(),
        )
        commands_list = [
            ("/help", "Show this help message"),
            ("/news <url>", "Fetch a news link and run scanner"),
            ("/scan <symbol>", "Run scanner on a symbol"),
            ("/marketscan", "Run realtime + universe scanner once"),
            ("/universe", "Show broad market universe symbols"),
            ("/watchlist", "Show AI + historical watchlist stats"),
            ("/buy <symbol>", "Manually confirm and place a buy"),
            ("/exits", "Show tiered exit / trailing stop status"),
            ("/status", "Bot and trading status"),
            ("/start", "Start news monitoring"),
            ("/stop", "Stop news monitoring"),
            ("/check", "Scan recent messages from news channels"),
            ("/purge", "Delete this bot's old messages (news/summary)"),
            ("/paper_reset", "Cancel paper orders and close positions"),
        ]
        for name, desc in commands_list:
            embed.add_field(name=name, value=desc, inline=False)

        embed.set_footer(text=f"{self.bot.settings.bot.name} · /help for commands")
        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name="status", description="Show bot status")
    async def status_cmd(self, interaction: discord.Interaction) -> None:
        monitoring = "running ✅" if self.bot._monitoring else "stopped ⏸️"
        trade_status = self.bot.trading_engine.get_status()
        source_channels = ", ".join(str(cid) for cid in self.bot.settings.news.source_channel_ids)

        embed = discord.Embed(title=f"🤖 {self.bot.settings.bot.name} Status", color=discord.Color.blue())
        embed.add_field(name="Monitoring", value=monitoring, inline=True)
        embed.add_field(name="Source channels", value=source_channels, inline=True)
        embed.add_field(name="Alert channel", value=str(self.bot.settings.alert_channel_id), inline=True)
        embed.add_field(name="Trading", value=trade_status, inline=False)
        if self.bot.forwarder:
            embed.add_field(name="Session forwarder", value=self.bot.forwarder.get_status(), inline=False)
        ai_on = self.bot.analyzer.config.ai_sentiment_enabled and self.bot.analyzer.config.openai_api_key
        embed.add_field(
            name="AI sentiment",
            value=f"OpenAI ({self.bot.analyzer.config.openai_model})" if ai_on else "disabled",
            inline=False,
        )

        embed.set_footer(text=self.bot.settings.bot.name)
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

    @discord.app_commands.command(name="purge", description="Delete this bot's old messages from a channel")
    @discord.app_commands.describe(
        target="news = #news-channel, summary = #summary-channel, all = both, this = current channel"
    )
    @discord.app_commands.choices(
        target=[
            discord.app_commands.Choice(name="News channel", value="news"),
            discord.app_commands.Choice(name="Summary channel", value="summary"),
            discord.app_commands.Choice(name="News + Summary", value="all"),
            discord.app_commands.Choice(name="This channel", value="this"),
        ]
    )
    async def purge_cmd(self, interaction: discord.Interaction, target: str = "all") -> None:
        await interaction.response.defer(ephemeral=True)

        channels: list[tuple[str, discord.TextChannel]] = []
        if target == "this":
            if isinstance(interaction.channel, discord.TextChannel):
                channels.append(("this channel", interaction.channel))
        elif target == "news":
            if self.bot._news_channel:
                channels.append(("news", self.bot._news_channel))
        elif target == "summary":
            if self.bot._summary_channel:
                channels.append(("summary", self.bot._summary_channel))
        else:
            if self.bot._news_channel:
                channels.append(("news", self.bot._news_channel))
            if self.bot._summary_channel:
                channels.append(("summary", self.bot._summary_channel))

        if not channels:
            await interaction.followup.send("No channel found to purge. Check `.env` channel IDs.")
            return

        lines: list[str] = []
        try:
            for label, channel in channels:
                if label == "summary":
                    self.bot.summary_publisher.reset_message()
                deleted = await self.bot.purge_bot_messages(channel)
                lines.append(f"**#{channel.name}** ({label}): deleted **{deleted}** bot message(s)")
        except discord.Forbidden:
            await interaction.followup.send(
                "Bot needs **Manage Messages** permission in that channel."
            )
            return

        note = "\n".join(lines)
        await interaction.followup.send(
            f"✅ Purge done.\n{note}\n\n_Note: Discord only bulk-deletes messages from the last 14 days._"
        )

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

    @discord.app_commands.command(name="scan", description="Run the semi-automated scanner on a symbol")
    @discord.app_commands.describe(symbol="Stock ticker, e.g. CAST")
    async def scan_cmd(self, interaction: discord.Interaction, symbol: str) -> None:
        await interaction.response.defer()
        symbol = symbol.upper().strip()
        mosquito_signal = self.bot.volume_tracker.get_recent(symbol)
        try:
            scan = await self.bot._scan_symbol(
                symbol,
                mosquito_signal=mosquito_signal,
                news_bullish=False,
            )
        except Exception as exc:
            await interaction.followup.send(f"Scanner failed for `{symbol}`: {exc}")
            return
        await interaction.followup.send(
            embed=build_scan_embed(
                scan,
                min_score=self.bot._scanner_min_score(scan),
                title_prefix="Scanner",
                bot_name=self.bot.settings.bot.name,
            )
        )

    @discord.app_commands.command(name="universe", description="Show broad market universe from Alpaca screener")
    async def universe_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        symbols = await asyncio.to_thread(self.bot._fetch_universe_symbols)
        if not symbols:
            await interaction.followup.send("No universe symbols returned (check Alpaca keys).")
            return
        preview = ", ".join(symbols[:40])
        extra = f" … +{len(symbols) - 40} more" if len(symbols) > 40 else ""
        await interaction.followup.send(f"🌐 **Universe** ({len(symbols)} symbols)\n{preview}{extra}")

    @discord.app_commands.command(name="watchlist", description="Show AI news + historical watchlist status")
    async def watchlist_cmd(self, interaction: discord.Interaction) -> None:
        ai_entries = self.bot.watchlist.active_entries()
        hist_count = self.bot.historical_watchlist.count()
        hist_max = self.bot.settings.trading.historical_watchlist_max_entries
        ai_preview = ", ".join(entry.symbol for entry in ai_entries[:25])
        hist_preview = ", ".join(self.bot.historical_watchlist.symbols()[:25])
        extra_ai = f" … +{len(ai_entries) - 25} more" if len(ai_entries) > 25 else ""
        extra_hist = f" … +{hist_count - 25} more" if hist_count > 25 else ""
        await interaction.response.send_message(
            f"👀 **AI Watchlist** ({len(ai_entries)}/{self.bot.settings.trading.watchlist_max_entries})\n"
            f"{ai_preview or 'empty'}{extra_ai}\n\n"
            f"📊 **Historical runners** ({hist_count}/{hist_max})\n"
            f"{hist_preview or 'empty'}{extra_hist}"
        )

    @discord.app_commands.command(name="marketscan", description="Run realtime scanner once on watchlist symbols")
    async def marketscan_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not self.bot.realtime_scanner:
            await interaction.followup.send("Realtime scanner is disabled in settings.")
            return
        scans = await self.bot.realtime_scanner.scan_now()
        if not scans:
            await interaction.followup.send("No symbols in watchlist/runner history to scan.")
            return
        actionable = [
            scan
            for scan in scans
            if scan.score >= self.bot._scanner_min_score(scan)
        ][:5]
        if not actionable:
            await interaction.followup.send("No actionable setups found in the current watchlist scan.")
            return
        await interaction.followup.send(
            f"🔎 **Market scan** — {len(actionable)} setup(s)",
            embeds=[
                build_scan_embed(
                    scan,
                    min_score=self.bot._scanner_min_score(scan),
                    title_prefix="Market Scan",
                    bot_name=self.bot.settings.bot.name,
                )
                for scan in actionable
            ],
        )

    @discord.app_commands.command(name="exits", description="Show active tiered exit and trailing stop plans")
    async def exits_cmd(self, interaction: discord.Interaction) -> None:
        lines = self.bot.trading_engine.exit_manager.status_lines()
        await interaction.response.send_message("📤 **Exit plans**\n" + "\n".join(lines))

    @discord.app_commands.command(name="buy", description="Manually confirm and place a buy order")
    @discord.app_commands.describe(symbol="Stock ticker, e.g. CAST")
    async def buy_cmd(self, interaction: discord.Interaction, symbol: str) -> None:
        await interaction.response.defer()
        symbol = symbol.upper().strip()
        mosquito_signal = self.bot.volume_tracker.get_recent(symbol)
        scan = await self.bot._scan_symbol(
            symbol,
            mosquito_signal=mosquito_signal,
            news_bullish=False,
        )
        limit_price = None
        if self.bot.settings.trading.use_pullback_limit_orders and scan.suggested_limit_price:
            limit_price = scan.suggested_limit_price
        trade_result = await self.bot.trading_engine.manual_buy(
            symbol,
            text=f"manual /buy by {interaction.user.display_name}",
            limit_price=limit_price,
        )
        scan_note = self.bot._format_scan_action(scan)
        if scan.pullback and scan.pullback.is_chasing:
            scan_note = (
                f"⚠️ Chasing detected — limit order placed at pullback ${limit_price:.2f}, not market.\n"
                f"{scan_note}"
            )
        if trade_result.success:
            await interaction.followup.send(f"✅ {trade_result.message}\n\n{scan_note}")
        else:
            await interaction.followup.send(f"❌ {trade_result.message}\n\n{scan_note}")

    @discord.app_commands.command(name="paper_reset", description="Cancel open paper orders and close positions")
    async def paper_reset_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        msg = await self.bot.trading_engine.reset_paper_account()
        await interaction.followup.send(msg)

    @discord.app_commands.command(name="news", description="Fetch a news URL and run scanner")
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
            note = trade_msg or f"Buy signal — {item.ai_reason}"
        elif item.sentiment == "ignored":
            note = f"Ignored — {item.ai_reason}."
        elif item.sentiment == "neutral":
            note = f"Neutral — {item.ai_reason or 'AI: no catalyst'}"
        else:
            note = "Alert sent."
        await interaction.followup.send(note)


async def run_bot(settings: Settings, forwarder: SessionForwarder | None = None) -> None:
    bot = NewsTradingBot(settings, forwarder=forwarder)
    async with bot:
        await bot.start(settings.discord_token)
