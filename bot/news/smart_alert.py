"""SDS §5.1 Smart Alert — News + Liquidity + Momentum alignment."""

from __future__ import annotations

from bot.news.news_intelligence import IMPACT_GRAY, IMPACT_HIGH, IMPACT_MEDIUM, NewsImpact, SymbolNewsContext


def evaluate_smart_alert(
    impact: NewsImpact,
    context: SymbolNewsContext | None,
    *,
    crowd_score: int = 0,
    repeated_pr: bool = False,
    min_rvol: float = 3.0,
    min_turnover_usd: float = 300_000,
) -> bool:
    if repeated_pr or impact.level == IMPACT_GRAY:
        return False
    if impact.level not in {IMPACT_HIGH, IMPACT_MEDIUM}:
        return False
    if crowd_score < 45:
        return False
    ctx = context
    if not ctx:
        return impact.level == IMPACT_HIGH and crowd_score >= 55
    liquidity_ok = (
        (ctx.rvol is not None and ctx.rvol >= min_rvol)
        or (ctx.session_turnover_usd is not None and ctx.session_turnover_usd >= min_turnover_usd)
        or (ctx.premarket_turnover_usd is not None and ctx.premarket_turnover_usd >= min_turnover_usd)
        or (ctx.session_change_pct is not None and abs(ctx.session_change_pct) >= 8)
    )
    momentum_ok = ctx.is_runner or (ctx.rvol is not None and ctx.rvol >= min_rvol)
    return liquidity_ok and momentum_ok
