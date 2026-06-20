"""Semi-automated scanner scoring for low-cap momentum setups."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from bot.news.benzinga import CatalystResult, fetch_catalyst_sync, score_catalyst
from bot.news.volume_signal import VolumeSignal
from bot.trading.data_providers import MarketDataProvider
from bot.trading.indicators import IndicatorSnapshot
from bot.trading.market_data import fetch_gap_and_session_change
from bot.trading.microstructure import MicrostructureSnapshot, analyze_microstructure, score_microstructure
from bot.trading.pullback import PullbackSetup, analyze_pullback
from bot.trading.runner_history import RunnerHistoryStore
from bot.trading.scanner_profiles import ScannerProfile, get_active_profile
from bot.trading.timeframes import MultiTimeframeAnalysis, analyze_multi_timeframe
from bot.trading.volume import get_daily_volume
from bot.utils.config import TradingConfig

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    symbol: str
    score: int = 0
    grade: str = "D"
    profile_name: str = ""
    price: float | None = None
    daily_volume: int | None = None
    avg_volume: int | None = None
    rvol: float | None = None
    turnover_usd: float | None = None
    gap_pct: float | None = None
    session_change_pct: float | None = None
    float_shares: float | None = None
    market_cap_usd: float | None = None
    stars: int = 0
    is_repeat_runner: bool = False
    mosquito_confirmed: bool = False
    news_bullish: bool = False
    indicators: IndicatorSnapshot | None = None
    timeframes: MultiTimeframeAnalysis | None = None
    pullback: PullbackSetup | None = None
    suggested_limit_price: float | None = None
    catalyst: CatalystResult | None = None
    microstructure: MicrostructureSnapshot | None = None
    data_provider_name: str = "alpaca"
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"Score {self.score}/100 ({self.grade})"]
        if self.profile_name:
            parts.append(f"profile {self.profile_name}")
        if self.price is not None:
            parts.append(f"price ${self.price:.2f}")
        if self.rvol is not None:
            parts.append(f"RVOL {self.rvol:.1f}x")
        if self.gap_pct is not None:
            parts.append(f"gap {self.gap_pct:+.1f}%")
        if self.session_change_pct is not None:
            parts.append(f"session {self.session_change_pct:+.1f}%")
        if self.daily_volume is not None:
            parts.append(f"vol {self.daily_volume:,}")
        if self.turnover_usd is not None:
            parts.append(f"turnover ~${self.turnover_usd:,.0f}")
        if self.is_repeat_runner:
            parts.append(f"repeat runner {'⭐' * max(1, self.stars)}")
        if self.timeframes:
            parts.append(self.timeframes.summary)
        if self.catalyst and self.catalyst.keywords:
            parts.append(f"catalyst: {', '.join(self.catalyst.keywords[:3])}")
        if self.microstructure:
            parts.append(self.microstructure.summary)
        return " | ".join(parts)


class SymbolScanner:
    def __init__(
        self,
        trading_config: TradingConfig,
        runner_history: RunnerHistoryStore,
        *,
        get_clients,
        get_last_price,
        get_latest_trade_price,
        data_provider: MarketDataProvider | None = None,
        benzinga_api_key: str = "",
        finnhub_api_key: str = "",
    ):
        self.cfg = trading_config
        self.runner_history = runner_history
        self._get_clients = get_clients
        self._get_last_price = get_last_price
        self._get_latest_trade_price = get_latest_trade_price
        self._data_provider = data_provider
        self._benzinga_api_key = benzinga_api_key
        self._finnhub_api_key = finnhub_api_key

    def scan(
        self,
        symbol: str,
        *,
        mosquito_signal: VolumeSignal | None = None,
        news_bullish: bool = False,
    ) -> ScanResult:
        symbol = symbol.upper()
        profile = get_active_profile(self.cfg.scanner_profiles)
        result = ScanResult(
            symbol=symbol,
            news_bullish=news_bullish,
            profile_name=profile.name,
            data_provider_name=self._data_provider.name if self._data_provider else "alpaca",
        )

        try:
            if self._data_provider:
                result.price = self._data_provider.get_last_price(symbol)
            else:
                result.price = self._resolve_price(symbol)
        except Exception as exc:
            result.warnings.append(f"price unavailable: {exc}")

        bars_1m: list = []
        try:
            _, data_client = self._get_clients()
            result.daily_volume = get_daily_volume(data_client, symbol)
            result.avg_volume = self._get_avg_volume(data_client, symbol)
            if result.daily_volume and result.avg_volume and result.avg_volume > 0:
                result.rvol = round(result.daily_volume / result.avg_volume, 2)

            if result.price:
                result.gap_pct, result.session_change_pct = fetch_gap_and_session_change(
                    data_client, symbol, result.price
                )
            if self._data_provider:
                bars_1m = self._data_provider.get_intraday_bars(
                    symbol, limit=self.cfg.intraday_bar_limit
                )
            else:
                from bot.trading.market_data import fetch_intraday_bars

                bars_1m = fetch_intraday_bars(data_client, symbol, limit=self.cfg.intraday_bar_limit)
            result.timeframes = analyze_multi_timeframe(
                bars_1m,
                avg_volume=float(result.avg_volume) if result.avg_volume else None,
            )
            if bars_1m:
                tf_5m = result.timeframes.snapshots.get("5m") if result.timeframes else None
                if tf_5m and tf_5m.indicators:
                    result.indicators = tf_5m.indicators
                else:
                    from bot.trading.indicators import compute_indicators

                    result.indicators = compute_indicators(
                        bars_1m[-30:],
                        avg_volume=float(result.avg_volume) if result.avg_volume else None,
                    )
        except Exception as exc:
            logger.warning("Scanner market data failed for %s: %s", symbol, exc)
            result.warnings.append("market data partially unavailable")

        if result.price and result.daily_volume:
            result.turnover_usd = result.price * result.daily_volume

        if mosquito_signal:
            result.mosquito_confirmed = True
            if mosquito_signal.float_shares:
                result.float_shares = mosquito_signal.float_shares
            if mosquito_signal.relative_volume is not None and result.rvol is None:
                result.rvol = mosquito_signal.relative_volume
            if mosquito_signal.price and result.price is None:
                result.price = mosquito_signal.price

        if self.cfg.benzinga_enabled and self._benzinga_api_key:
            result.catalyst = fetch_catalyst_sync(symbol, self._benzinga_api_key)

        if self.cfg.microstructure_enabled:
            try:
                _, data_client = self._get_clients()
                result.microstructure = analyze_microstructure(
                    data_client,
                    symbol,
                    finnhub_api_key=self._finnhub_api_key,
                )
            except Exception as exc:
                result.warnings.append(f"microstructure unavailable: {exc}")

        if result.float_shares and result.price:
            result.market_cap_usd = result.float_shares * result.price

        runner = self.runner_history.get(symbol)
        if runner:
            result.stars = runner.stars
            result.is_repeat_runner = self.runner_history.is_repeat_runner(symbol)

        if result.price and bars_1m:
            result.pullback = analyze_pullback(
                bars_1m,
                result.price,
                lookback_bars=self.cfg.pullback_lookback_bars,
                pullback_percent=self.cfg.pullback_entry_percent,
                max_chase_percent=self.cfg.pullback_max_chase_percent,
                limit_buffer_percent=self.cfg.pullback_limit_buffer_percent,
            )
            if result.pullback:
                result.suggested_limit_price = result.pullback.suggested_limit

        self._apply_profile_filters(result, profile)
        self._score(result, profile, mosquito_signal)
        if result.price is not None:
            self.runner_history.record_sighting(symbol, price=result.price)
        return result

    def _resolve_price(self, symbol: str) -> float:
        try:
            return self._get_last_price(symbol)
        except Exception:
            trade_price = self._get_latest_trade_price(symbol)
            if trade_price:
                return trade_price
            raise

    @staticmethod
    def _get_avg_volume(data_client, symbol: str) -> int:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        bars = data_client.get_stock_bars(
            StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, limit=31)
        )
        if hasattr(bars, "data"):
            series = bars.data.get(symbol, [])
        else:
            series = bars[symbol]
        if not series:
            return 0
        volumes = [int(bar.volume) for bar in series[:-1]] or [int(series[-1].volume)]
        return int(sum(volumes) / len(volumes))

    def _apply_profile_filters(self, result: ScanResult, profile: ScannerProfile) -> None:
        if result.price is not None:
            if result.price < profile.min_price or result.price > profile.max_price:
                result.warnings.append(
                    f"price ${result.price:.2f} outside {profile.name} range "
                    f"(${profile.min_price}-${profile.max_price})"
                )

        if result.gap_pct is not None:
            if result.gap_pct < profile.min_gap_pct:
                result.warnings.append(f"gap {result.gap_pct:g}% below {profile.min_gap_pct:g}%")
            elif result.gap_pct > profile.max_gap_pct:
                result.warnings.append(f"gap {result.gap_pct:g}% above {profile.max_gap_pct:g}%")

        if result.session_change_pct is not None and result.session_change_pct < profile.min_session_change_pct:
            result.warnings.append(
                f"session change {result.session_change_pct:g}% below {profile.min_session_change_pct:g}%"
            )

        if result.float_shares is not None and result.float_shares > profile.max_float_shares:
            result.warnings.append(f"float {result.float_shares:,.0f} above profile max")

        if result.market_cap_usd is not None and result.market_cap_usd > profile.max_market_cap_usd:
            result.warnings.append(f"market cap ~${result.market_cap_usd:,.0f} above profile max")

        if result.rvol is not None and result.rvol < profile.min_rvol:
            result.warnings.append(f"RVOL {result.rvol:g}x below {profile.name} min {profile.min_rvol:g}x")

        if result.daily_volume is not None and result.daily_volume < profile.min_daily_volume:
            result.warnings.append(f"daily volume below {profile.name} minimum")

        if result.turnover_usd is not None and result.turnover_usd < profile.min_turnover_usd:
            result.warnings.append(f"turnover below {profile.name} minimum")

    def _score(
        self,
        result: ScanResult,
        profile: ScannerProfile,
        mosquito_signal: VolumeSignal | None,
    ) -> None:
        score = 0
        min_score = max(self.cfg.scanner_min_alert_score, profile.min_alert_score)

        if result.news_bullish:
            score += 15
            result.reasons.append("bullish news catalyst")

        if mosquito_signal:
            score += 20
            result.reasons.append("mosquito volume/RVOL confirmed")
        elif result.mosquito_confirmed:
            score += 15
            result.reasons.append("recent mosquito signal")

        if result.rvol is not None and result.rvol >= profile.min_rvol:
            score += 12
            result.reasons.append(f"RVOL {result.rvol:g}x")

        if result.gap_pct is not None and profile.min_gap_pct <= result.gap_pct <= profile.max_gap_pct:
            score += 8
            result.reasons.append(f"gap {result.gap_pct:+.1f}%")

        if result.session_change_pct is not None and result.session_change_pct >= profile.min_session_change_pct:
            score += 8
            result.reasons.append(f"session change {result.session_change_pct:+.1f}%")

        if result.daily_volume is not None and result.daily_volume >= profile.min_daily_volume:
            score += 6
            result.reasons.append(f"daily volume {result.daily_volume:,}")

        if result.turnover_usd is not None and result.turnover_usd >= profile.min_turnover_usd:
            score += 6
            result.reasons.append(f"turnover ~${result.turnover_usd:,.0f}")

        if result.float_shares is not None and result.float_shares <= profile.max_float_shares:
            score += 4
            result.reasons.append("float within low-cap range")

        if result.is_repeat_runner:
            bonus = 8 + min(4, result.stars * 2)
            score += bonus
            result.reasons.append("repeat historical runner")

        if result.indicators:
            score += min(10, len(result.indicators.bullish_signals) * 2)
            for signal in result.indicators.bullish_signals[:3]:
                result.reasons.append(signal)
            for signal in result.indicators.bearish_signals[:2]:
                result.warnings.append(signal)

        if result.timeframes:
            if result.timeframes.consensus == "bullish":
                score += 10
                result.reasons.append("multi-timeframe bullish alignment")
            elif result.timeframes.consensus == "bearish":
                score -= 5
                result.warnings.append("multi-timeframe bearish")

        if result.pullback:
            if result.pullback.ready_to_enter and not result.pullback.is_chasing:
                score += 8
                result.reasons.append("pullback entry zone")
            elif result.pullback.is_chasing:
                score -= 8
                result.warnings.append("chasing extended move — wait for pullback")

        if result.catalyst:
            cat_score, cat_reasons, cat_warnings = score_catalyst(result.catalyst)
            score += cat_score
            result.reasons.extend(cat_reasons)
            result.warnings.extend(cat_warnings)

        if result.microstructure:
            ms_score, ms_reasons, ms_warnings = score_microstructure(result.microstructure)
            score += ms_score
            result.reasons.extend(ms_reasons)
            result.warnings.extend(ms_warnings)

        result.score = max(0, min(100, score))
        result.grade = self._grade(result.score)
        if result.score < min_score and not result.warnings:
            result.warnings.append(f"score below {profile.name} threshold ({min_score})")

    @staticmethod
    def _grade(score: int) -> str:
        if score >= 80:
            return "A"
        if score >= 65:
            return "B"
        if score >= 50:
            return "C"
        return "D"
