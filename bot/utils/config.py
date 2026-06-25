"""Simple module for loading application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from bot.trading.exit_manager import ExitTier
from bot.trading.scanner_profiles import ScannerProfile, load_profiles_from_config

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT_DIR / "config" / "settings.yaml"
ENV_PATH = ROOT_DIR / ".env"


@dataclass
class NewsConfig:
    source_channel_ids: list[int]
    allowed_url_domains: list[str]
    process_all_messages: bool = False
    always_process_urls: bool = True
    alert_all_news: bool = True
    trusted_news_bots: list[str] | None = None
    ai_sentiment_enabled: bool = True
    openai_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    benzinga_feed_enabled: bool = False
    benzinga_poll_interval_seconds: int = 15


@dataclass
class TradingConfig:
    enabled: bool
    broker: str
    default_symbol: str
    trade_amount_usd: float
    take_profit_percent: float
    stop_loss_percent: float
    max_trades_per_day: int
    one_trade_per_symbol_per_day: bool = True
    cancel_orders_on_bad_news: bool = True
    sell_position_on_bad_news: bool = True
    remove_watchlist_on_bad_news: bool = True
    block_saturday: bool = True
    block_sunday: bool = True
    block_monday_premarket: bool = False
    regular_market_hours_only: bool = False
    extended_hours_trading: bool = True
    volume_filter_enabled: bool = True
    min_volume_skip: int = 200_000
    low_volume_threshold: int = 1_000_000
    low_volume_trade_amount_usd: float = 25.0
    extended_limit_buffer_percent: float = 2.0
    extended_quote_max_below_trade_percent: float = 10.0
    mosquito_volume_filter_enabled: bool = True
    mosquito_volume_min_value: float = 1_000_000
    mosquito_min_relative_volume: float = 2.0
    mosquito_volume_confirm_minutes: int = 60
    mosquito_alerts_enabled: bool = True
    mosquito_alert_cooldown_seconds: int = 600
    mosquito_max_alerts_per_batch: int = 3
    mosquito_automute_window_seconds: int = 90
    mosquito_automute_max_alerts: int = 8
    mosquito_automute_duration_seconds: int = 180
    watchlist_alert_cooldown_seconds: int = 600
    watchlist_max_alerts_per_batch: int = 3
    watchlist_automute_window_seconds: int = 90
    watchlist_automute_max_alerts: int = 6
    watchlist_automute_duration_seconds: int = 180
    watchlist_mode_enabled: bool = True
    watchlist_days: int = 3
    watchlist_volume_increase_percent: float = 20.0
    watchlist_price_increase_percent: float = 3.0
    watchlist_max_entries: int = 2000
    historical_watchlist_max_entries: int = 2000
    historical_watchlist_retention_days: int = 90
    grid_exit_flexible: bool = True
    grid_rvol_strong: float = 3.0
    grid_rvol_weak: float = 1.5
    grid_tier_adjust_percent: float = 10.0
    ai_exit_enabled: bool = True
    ai_exit_min_profit_percent: float = -5.0
    semi_automated_mode: bool = True
    auto_trade_on_signal: bool = False
    scanner_min_alert_score: int = 50
    scanner_min_rvol: float = 2.0
    scanner_min_daily_volume: int = 500_000
    scanner_min_turnover_usd: float = 1_000_000.0
    scanner_min_price: float = 0.5
    scanner_max_price: float = 20.0
    runner_big_move_percent: float = 50.0
    runner_retention_days: int = 30
    scanner_profiles: dict[str, ScannerProfile] | None = None
    intraday_bar_limit: int = 120
    pullback_entry_percent: float = 3.0
    pullback_max_chase_percent: float = 2.0
    pullback_limit_buffer_percent: float = 0.5
    pullback_lookback_bars: int = 30
    use_pullback_limit_orders: bool = True
    exit_manager_enabled: bool = True
    exit_tiers: list[ExitTier] | None = None
    trailing_stop_percent: float = 5.0
    runner_hold_percent: float = 15.0
    realtime_scanner_enabled: bool = True
    realtime_scan_interval_seconds: int = 30
    realtime_scan_alert_cooldown_seconds: int = 300
    benzinga_enabled: bool = True
    microstructure_enabled: bool = True
    data_provider: str = "alpaca"
    moomoo_host: str = "127.0.0.1"
    moomoo_port: int = 11111
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    ibkr_client_id: int = 1
    universe_scanner_enabled: bool = True
    universe_most_actives_top: int = 100
    universe_movers_top: int = 50
    realtime_max_symbols_per_cycle: int = 100
    realtime_batch_rotation: bool = True
    summary_interval_seconds: int = 60
    summary_live_tick_seconds: int = 30
    summary_top_gainers_limit: int = 15
    potential_enabled: bool = True
    potential_min_score: int = 45
    potential_min_session_change_pct: float = 2.0
    potential_max_session_change_pct: float = 25.0
    potential_max_alerts_per_batch: int = 5
    potential_alert_cooldown_seconds: int = 900
    potential_retention_days: int = 5
    unusual_whales_enabled: bool = True
    tradingview_enabled: bool = True
    tradingview_exchange: str = "NASDAQ"
    tradingview_interval: str = "5m"


@dataclass
class BotConfig:
    command_prefix: str
    auto_start: bool = True


@dataclass
class ForwardConfig:
    enabled: bool
    user_email: str
    user_password: str
    user_token: str
    source_channel_ids: list[int]
    dest_channel_id: int
    dest_channel_map: dict[int, int]
    require_news_url: bool = True


@dataclass
class Settings:
    bot: BotConfig
    news: NewsConfig
    trading: TradingConfig
    forwarder: ForwardConfig
    discord_token: str
    alert_channel_id: int
    watchlist_channel_id: int
    summary_channel_id: int
    news_channel_id: int
    mosquito_channel_id: int
    potential_channel_id: int
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_paper: bool
    benzinga_api_key: str = ""
    benzinga_news_provider: str = "massive"
    finnhub_api_key: str = ""
    unusual_whales_api_key: str = ""


def _resolve_benzinga_credentials() -> tuple[str, str]:
    massive_key = os.getenv("MASSIVE_API_KEY", "").strip()
    direct_key = os.getenv("BENZINGA_API_KEY", "").strip()
    provider = os.getenv("BENZINGA_NEWS_PROVIDER", "").strip().lower()
    if provider == "direct":
        return direct_key, "direct"
    if provider == "massive":
        return massive_key or direct_key, "massive"
    if massive_key:
        return massive_key, "massive"
    return direct_key, "direct" if direct_key else "massive"


def _parse_exit_tiers(raw: list | None) -> list[ExitTier]:
    defaults = [
        ExitTier(profit_percent=10, sell_percent=30),
        ExitTier(profit_percent=20, sell_percent=30),
        ExitTier(profit_percent=30, sell_percent=25),
    ]
    if not raw:
        return defaults
    tiers: list[ExitTier] = []
    for item in raw:
        if isinstance(item, dict):
            tiers.append(
                ExitTier(
                    profit_percent=float(item.get("profit_percent", 10)),
                    sell_percent=float(item.get("sell_percent", 25)),
                )
            )
    return tiers or defaults


def _parse_channel_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            ids.append(int(part))
    return ids


def _parse_channel_map(raw: str) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        src, dst = part.split(":", 1)
        mapping[int(src.strip())] = int(dst.strip())
    return mapping


def load_settings() -> Settings:
    """Load all settings from config files and environment variables."""
    load_dotenv(ENV_PATH)

    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    source_channels = os.getenv("NEWS_SOURCE_CHANNEL_IDS", "").strip()
    alert_channel = os.getenv("ALERT_CHANNEL_ID", "").strip()
    watchlist_channel = os.getenv("WATCHLIST_CHANNEL_ID", "").strip()
    summary_channel = os.getenv("SUMMARY_CHANNEL_ID", "").strip()
    news_channel = os.getenv("NEWS_CHANNEL_ID", "").strip()
    mosquito_channel = os.getenv("MOSQUITO_CHANNEL_ID", "").strip()
    potential_channel = os.getenv("POTENTIAL_CHANNEL_ID", "").strip()
    user_token = os.getenv("DISCORD_USER_TOKEN", "").strip()
    user_email = os.getenv("DISCORD_USER_EMAIL", "").strip()
    user_password = os.getenv("DISCORD_USER_PASSWORD", "").strip()
    forward_sources = os.getenv("FORWARD_SOURCE_CHANNEL_IDS", "").strip()
    forward_dest = os.getenv("FORWARD_DEST_CHANNEL_ID", "").strip()
    forward_map_raw = os.getenv("FORWARD_CHANNEL_MAP", "").strip()
    benzinga_api_key, benzinga_news_provider = _resolve_benzinga_credentials()

    if not source_channels and forward_dest:
        source_channels = forward_dest
    if not forward_dest and source_channels:
        forward_dest = source_channels.split(",")[0].strip()

    if not token:
        raise ValueError(
            "DISCORD_BOT_TOKEN not found. Copy .env.example to .env and add your token."
        )
    if not alert_channel:
        raise ValueError(
            "ALERT_CHANNEL_ID not found. Add the alert output channel ID in .env."
        )

    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    news_raw = raw["news"]
    trading_raw = raw["trading"]
    forwarder_raw = raw.get("forwarder", {})

    source_channel_ids = _parse_channel_ids(source_channels)
    forward_source_ids = _parse_channel_ids(forward_sources) if forward_sources else []
    forward_dest_id = int(forward_dest) if forward_dest else (source_channel_ids[0] if source_channel_ids else 0)
    forward_dest_map = _parse_channel_map(forward_map_raw)

    return Settings(
        bot=BotConfig(**raw["bot"]),
        news=NewsConfig(
            source_channel_ids=_parse_channel_ids(source_channels),
            allowed_url_domains=news_raw.get("allowed_url_domains", ["news.nuntiobot.com"]),
            process_all_messages=news_raw.get("process_all_messages", False),
            always_process_urls=news_raw.get("always_process_urls", True),
            alert_all_news=news_raw.get("alert_all_news", True),
            trusted_news_bots=news_raw.get("trusted_news_bots", ["nuntio"]),
            ai_sentiment_enabled=news_raw.get("ai_sentiment_enabled", True),
            openai_model=news_raw.get("openai_model", "gpt-4o-mini"),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            benzinga_feed_enabled=news_raw.get(
                "benzinga_feed_enabled",
                bool(benzinga_api_key),
            ),
            benzinga_poll_interval_seconds=int(news_raw.get("benzinga_poll_interval_seconds", 15)),
        ),
        trading=TradingConfig(
            enabled=trading_raw["enabled"],
            broker=trading_raw.get("broker", "alpaca"),
            default_symbol=trading_raw.get("default_symbol", ""),
            trade_amount_usd=float(trading_raw.get("trade_amount_usd", 100)),
            take_profit_percent=float(trading_raw.get("take_profit_percent", 3)),
            stop_loss_percent=float(trading_raw.get("stop_loss_percent", 2)),
            max_trades_per_day=int(trading_raw.get("max_trades_per_day", 5)),
            one_trade_per_symbol_per_day=trading_raw.get("one_trade_per_symbol_per_day", True),
            cancel_orders_on_bad_news=trading_raw.get("cancel_orders_on_bad_news", True),
            sell_position_on_bad_news=trading_raw.get("sell_position_on_bad_news", True),
            remove_watchlist_on_bad_news=trading_raw.get("remove_watchlist_on_bad_news", True),
            block_saturday=trading_raw.get("block_saturday", True),
            block_sunday=trading_raw.get("block_sunday", True),
            block_monday_premarket=trading_raw.get("block_monday_premarket", False),
            regular_market_hours_only=trading_raw.get("regular_market_hours_only", False),
            extended_hours_trading=trading_raw.get("extended_hours_trading", True),
            volume_filter_enabled=trading_raw.get("volume_filter_enabled", True),
            min_volume_skip=int(trading_raw.get("min_volume_skip", 200_000)),
            low_volume_threshold=int(trading_raw.get("low_volume_threshold", 1_000_000)),
            low_volume_trade_amount_usd=float(trading_raw.get("low_volume_trade_amount_usd", 25)),
            extended_limit_buffer_percent=float(trading_raw.get("extended_limit_buffer_percent", 2.0)),
            extended_quote_max_below_trade_percent=float(trading_raw.get("extended_quote_max_below_trade_percent", 10.0)),
            mosquito_volume_filter_enabled=trading_raw.get("mosquito_volume_filter_enabled", True),
            mosquito_volume_min_value=float(trading_raw.get("mosquito_volume_min_value", 1_000_000)),
            mosquito_min_relative_volume=float(trading_raw.get("mosquito_min_relative_volume", 2.0)),
            mosquito_volume_confirm_minutes=int(trading_raw.get("mosquito_volume_confirm_minutes", 60)),
            mosquito_alerts_enabled=trading_raw.get("mosquito_alerts_enabled", True),
            mosquito_alert_cooldown_seconds=int(trading_raw.get("mosquito_alert_cooldown_seconds", 600)),
            mosquito_max_alerts_per_batch=int(trading_raw.get("mosquito_max_alerts_per_batch", 3)),
            mosquito_automute_window_seconds=int(trading_raw.get("mosquito_automute_window_seconds", 90)),
            mosquito_automute_max_alerts=int(trading_raw.get("mosquito_automute_max_alerts", 8)),
            mosquito_automute_duration_seconds=int(trading_raw.get("mosquito_automute_duration_seconds", 180)),
            watchlist_alert_cooldown_seconds=int(trading_raw.get("watchlist_alert_cooldown_seconds", 600)),
            watchlist_max_alerts_per_batch=int(trading_raw.get("watchlist_max_alerts_per_batch", 3)),
            watchlist_automute_window_seconds=int(trading_raw.get("watchlist_automute_window_seconds", 90)),
            watchlist_automute_max_alerts=int(trading_raw.get("watchlist_automute_max_alerts", 6)),
            watchlist_automute_duration_seconds=int(trading_raw.get("watchlist_automute_duration_seconds", 180)),
            watchlist_mode_enabled=trading_raw.get("watchlist_mode_enabled", True),
            watchlist_days=int(trading_raw.get("watchlist_days", 3)),
            watchlist_volume_increase_percent=float(trading_raw.get("watchlist_volume_increase_percent", 20)),
            watchlist_price_increase_percent=float(trading_raw.get("watchlist_price_increase_percent", 3)),
            watchlist_max_entries=int(trading_raw.get("watchlist_max_entries", 2000)),
            historical_watchlist_max_entries=int(trading_raw.get("historical_watchlist_max_entries", 2000)),
            historical_watchlist_retention_days=int(trading_raw.get("historical_watchlist_retention_days", 90)),
            grid_exit_flexible=trading_raw.get("grid_exit_flexible", True),
            grid_rvol_strong=float(trading_raw.get("grid_rvol_strong", 3.0)),
            grid_rvol_weak=float(trading_raw.get("grid_rvol_weak", 1.5)),
            grid_tier_adjust_percent=float(trading_raw.get("grid_tier_adjust_percent", 10.0)),
            ai_exit_enabled=trading_raw.get("ai_exit_enabled", True),
            ai_exit_min_profit_percent=float(trading_raw.get("ai_exit_min_profit_percent", -5.0)),
            semi_automated_mode=trading_raw.get("semi_automated_mode", True),
            auto_trade_on_signal=trading_raw.get("auto_trade_on_signal", False),
            scanner_min_alert_score=int(trading_raw.get("scanner_min_alert_score", 50)),
            scanner_min_rvol=float(trading_raw.get("scanner_min_rvol", 2.0)),
            scanner_min_daily_volume=int(trading_raw.get("scanner_min_daily_volume", 500_000)),
            scanner_min_turnover_usd=float(trading_raw.get("scanner_min_turnover_usd", 1_000_000)),
            scanner_min_price=float(trading_raw.get("scanner_min_price", 0.5)),
            scanner_max_price=float(trading_raw.get("scanner_max_price", 20.0)),
            runner_big_move_percent=float(trading_raw.get("runner_big_move_percent", 50.0)),
            runner_retention_days=int(trading_raw.get("runner_retention_days", 30)),
            scanner_profiles=load_profiles_from_config(trading_raw.get("scanner_profiles")),
            intraday_bar_limit=int(trading_raw.get("intraday_bar_limit", 120)),
            pullback_entry_percent=float(trading_raw.get("pullback_entry_percent", 3.0)),
            pullback_max_chase_percent=float(trading_raw.get("pullback_max_chase_percent", 2.0)),
            pullback_limit_buffer_percent=float(trading_raw.get("pullback_limit_buffer_percent", 0.5)),
            pullback_lookback_bars=int(trading_raw.get("pullback_lookback_bars", 30)),
            use_pullback_limit_orders=trading_raw.get("use_pullback_limit_orders", True),
            exit_manager_enabled=trading_raw.get("exit_manager_enabled", True),
            exit_tiers=_parse_exit_tiers(trading_raw.get("exit_tiers")),
            trailing_stop_percent=float(trading_raw.get("trailing_stop_percent", 5.0)),
            runner_hold_percent=float(trading_raw.get("runner_hold_percent", 15.0)),
            realtime_scanner_enabled=trading_raw.get("realtime_scanner_enabled", True),
            realtime_scan_interval_seconds=int(trading_raw.get("realtime_scan_interval_seconds", 30)),
            realtime_scan_alert_cooldown_seconds=int(
                trading_raw.get("realtime_scan_alert_cooldown_seconds", 300)
            ),
            benzinga_enabled=trading_raw.get("benzinga_enabled", True),
            microstructure_enabled=trading_raw.get("microstructure_enabled", True),
            data_provider=str(trading_raw.get("data_provider", "alpaca")),
            moomoo_host=str(trading_raw.get("moomoo_host", "127.0.0.1")),
            moomoo_port=int(trading_raw.get("moomoo_port", 11111)),
            ibkr_host=str(trading_raw.get("ibkr_host", "127.0.0.1")),
            ibkr_port=int(trading_raw.get("ibkr_port", 7497)),
            ibkr_client_id=int(trading_raw.get("ibkr_client_id", 1)),
            universe_scanner_enabled=trading_raw.get("universe_scanner_enabled", True),
            universe_most_actives_top=int(trading_raw.get("universe_most_actives_top", 100)),
            universe_movers_top=int(trading_raw.get("universe_movers_top", 50)),
            realtime_max_symbols_per_cycle=int(trading_raw.get("realtime_max_symbols_per_cycle", 100)),
            realtime_batch_rotation=trading_raw.get("realtime_batch_rotation", True),
            summary_interval_seconds=int(trading_raw.get("summary_interval_seconds", 60)),
            summary_live_tick_seconds=int(trading_raw.get("summary_live_tick_seconds", 30)),
            summary_top_gainers_limit=int(trading_raw.get("summary_top_gainers_limit", 15)),
            potential_enabled=trading_raw.get("potential_enabled", True),
            potential_min_score=int(trading_raw.get("potential_min_score", 45)),
            potential_min_session_change_pct=float(
                trading_raw.get("potential_min_session_change_pct", 2.0)
            ),
            potential_max_session_change_pct=float(
                trading_raw.get("potential_max_session_change_pct", 25.0)
            ),
            potential_max_alerts_per_batch=int(trading_raw.get("potential_max_alerts_per_batch", 5)),
            potential_alert_cooldown_seconds=int(
                trading_raw.get("potential_alert_cooldown_seconds", 900)
            ),
            potential_retention_days=int(trading_raw.get("potential_retention_days", 5)),
            unusual_whales_enabled=trading_raw.get("unusual_whales_enabled", True),
            tradingview_enabled=trading_raw.get("tradingview_enabled", True),
            tradingview_exchange=str(trading_raw.get("tradingview_exchange", "NASDAQ")),
            tradingview_interval=str(trading_raw.get("tradingview_interval", "5m")),
        ),
        forwarder=ForwardConfig(
            enabled=forwarder_raw.get("enabled", True),
            user_email=user_email,
            user_password=user_password,
            user_token=user_token,
            source_channel_ids=forward_source_ids,
            dest_channel_id=forward_dest_id,
            dest_channel_map=forward_dest_map,
            require_news_url=forwarder_raw.get("require_news_url", True),
        ),
        discord_token=token,
        alert_channel_id=int(alert_channel),
        watchlist_channel_id=int(watchlist_channel) if watchlist_channel else 0,
        summary_channel_id=int(summary_channel) if summary_channel else 0,
        news_channel_id=int(news_channel) if news_channel else forward_dest_id,
        mosquito_channel_id=int(mosquito_channel) if mosquito_channel else 0,
        potential_channel_id=int(potential_channel) if potential_channel else 0,
        alpaca_api_key=os.getenv("ALPACA_API_KEY", "").strip(),
        alpaca_secret_key=os.getenv("ALPACA_SECRET_KEY", "").strip(),
        alpaca_paper=os.getenv("ALPACA_PAPER", "true").strip().lower() == "true",
        benzinga_api_key=benzinga_api_key,
        benzinga_news_provider=benzinga_news_provider,
        finnhub_api_key=os.getenv("FINNHUB_API_KEY", "").strip(),
        unusual_whales_api_key=os.getenv("UNUSUAL_WHALES_API_KEY", "").strip(),
    )
