"""SDS §5.1 Crowd Attention Score (0–100) from available live context."""

from __future__ import annotations

from bot.news.news_intelligence import SymbolNewsContext


def compute_crowd_attention_score(
    *,
    impact_level: str,
    context: SymbolNewsContext | None,
    is_fresh: bool = True,
    repeated_pr: bool = False,
) -> int:
    score = 0.0
    ctx = context

    if is_fresh and not repeated_pr:
        score += 25
    elif repeated_pr:
        score += 5

    if impact_level == "high":
        score += 30
    elif impact_level == "medium":
        score += 20
    elif impact_level == "low":
        score += 10

    if ctx:
        if ctx.rvol is not None and ctx.rvol >= 5:
            score += min(20, ctx.rvol)
        if ctx.session_turnover_usd and ctx.session_turnover_usd >= 300_000:
            score += 15
        elif ctx.premarket_turnover_usd and ctx.premarket_turnover_usd >= 300_000:
            score += 15
        if ctx.is_runner:
            score += 10
        if ctx.session_change_pct is not None and abs(ctx.session_change_pct) >= 10:
            score += 10

    return int(min(100, max(0, round(score))))
