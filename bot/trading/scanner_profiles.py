"""Session-based scanner profiles for pre-market, regular, and after-hours."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from bot.trading.schedule import ET, REGULAR_CLOSE, REGULAR_OPEN

PREMARKET_START = time(4, 0)
AFTERHOURS_START = time(16, 0)
AFTERHOURS_END = time(20, 0)


@dataclass(frozen=True)
class ScannerProfile:
    name: str
    min_price: float
    max_price: float
    min_rvol: float
    min_gap_pct: float
    max_gap_pct: float
    min_session_change_pct: float
    max_float_shares: float
    max_market_cap_usd: float
    min_turnover_usd: float
    min_daily_volume: int
    min_alert_score: int


DEFAULT_PROFILES: dict[str, ScannerProfile] = {
    "premarket": ScannerProfile(
        name="premarket",
        min_price=0.5,
        max_price=15.0,
        min_rvol=1.5,
        min_gap_pct=3.0,
        max_gap_pct=80.0,
        min_session_change_pct=2.0,
        max_float_shares=50_000_000,
        max_market_cap_usd=500_000_000,
        min_turnover_usd=500_000,
        min_daily_volume=300_000,
        min_alert_score=45,
    ),
    "regular": ScannerProfile(
        name="regular",
        min_price=0.5,
        max_price=20.0,
        min_rvol=2.0,
        min_gap_pct=5.0,
        max_gap_pct=100.0,
        min_session_change_pct=3.0,
        max_float_shares=80_000_000,
        max_market_cap_usd=1_000_000_000,
        min_turnover_usd=1_000_000,
        min_daily_volume=500_000,
        min_alert_score=50,
    ),
    "afterhours": ScannerProfile(
        name="afterhours",
        min_price=0.5,
        max_price=15.0,
        min_rvol=1.8,
        min_gap_pct=0.0,
        max_gap_pct=120.0,
        min_session_change_pct=1.0,
        max_float_shares=50_000_000,
        max_market_cap_usd=500_000_000,
        min_turnover_usd=750_000,
        min_daily_volume=400_000,
        min_alert_score=48,
    ),
}


def get_market_session(now: datetime | None = None) -> str:
    current = now or datetime.now(ET)
    if current.tzinfo is None:
        current = current.replace(tzinfo=ET)
    else:
        current = current.astimezone(ET)
    if current.weekday() >= 5:
        return "premarket"
    t = current.time()
    if PREMARKET_START <= t < REGULAR_OPEN:
        return "premarket"
    if REGULAR_OPEN <= t < REGULAR_CLOSE:
        return "regular"
    if AFTERHOURS_START <= t < AFTERHOURS_END:
        return "afterhours"
    return "premarket"


def get_active_profile(
    profiles: dict[str, ScannerProfile] | None = None,
    now: datetime | None = None,
) -> ScannerProfile:
    session = get_market_session(now)
    source = profiles or DEFAULT_PROFILES
    return source.get(session, source["regular"])


def load_profiles_from_config(raw: dict | None) -> dict[str, ScannerProfile]:
    if not raw:
        return dict(DEFAULT_PROFILES)
    profiles: dict[str, ScannerProfile] = {}
    for name, defaults in DEFAULT_PROFILES.items():
        overrides = raw.get(name, {}) if isinstance(raw, dict) else {}
        if not isinstance(overrides, dict):
            overrides = {}
        profiles[name] = ScannerProfile(
            name=name,
            min_price=float(overrides.get("min_price", defaults.min_price)),
            max_price=float(overrides.get("max_price", defaults.max_price)),
            min_rvol=float(overrides.get("min_rvol", defaults.min_rvol)),
            min_gap_pct=float(overrides.get("min_gap_pct", defaults.min_gap_pct)),
            max_gap_pct=float(overrides.get("max_gap_pct", defaults.max_gap_pct)),
            min_session_change_pct=float(
                overrides.get("min_session_change_pct", defaults.min_session_change_pct)
            ),
            max_float_shares=float(overrides.get("max_float_shares", defaults.max_float_shares)),
            max_market_cap_usd=float(overrides.get("max_market_cap_usd", defaults.max_market_cap_usd)),
            min_turnover_usd=float(overrides.get("min_turnover_usd", defaults.min_turnover_usd)),
            min_daily_volume=int(overrides.get("min_daily_volume", defaults.min_daily_volume)),
            min_alert_score=int(overrides.get("min_alert_score", defaults.min_alert_score)),
        )
    return profiles
