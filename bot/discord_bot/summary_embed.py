"""Summary channel embeds (Phase 5)."""

from __future__ import annotations

import discord

from bot.trading.scanner import ScanResult


def _compact_number(value: float | None, *, prefix: str = "", suffix: str = "") -> str:
    if value is None:
        return "—"
    if abs(value) >= 1_000_000:
        text = f"{value / 1_000_000:.2f}M"
    elif abs(value) >= 1_000:
        text = f"{value / 1_000:.1f}K"
    else:
        text = f"{value:.2f}" if isinstance(value, float) else str(value)
    return f"{prefix}{text}{suffix}"


def _rank_lines(scans: list[ScanResult], fmt) -> str:
    if not scans:
        return "—"
    lines = [fmt(scan, idx + 1) for idx, scan in enumerate(scans[:10])]
    return "\n".join(lines)[:1024]


def build_summary_embed(scans: list[ScanResult]) -> discord.Embed:
    embed = discord.Embed(
        title="📊 Market Summary",
        description="Relative rankings from the latest scanner cycle.",
        color=discord.Color.from_rgb(88, 101, 242),
    )

    by_liquidity = sorted(
        scans,
        key=lambda s: (s.liquidity_percentile or 0, s.turnover_usd or 0),
        reverse=True,
    )
    embed.add_field(
        name="Relative Liquidity Ranking",
        value=_rank_lines(
            by_liquidity,
            lambda s, r: f"`{r}` **{s.symbol}** · turnover {_compact_number(s.turnover_usd, prefix='$')} · rank #{s.liquidity_rank or '—'}",
        ),
        inline=False,
    )

    by_peak = sorted(scans, key=lambda s: s.peak_rvol or 0, reverse=True)
    embed.add_field(
        name="Peak RVOL Ranking",
        value=_rank_lines(
            by_peak,
            lambda s, r: f"`{r}` **{s.symbol}** · peak {_compact_number(s.peak_rvol, suffix='x')} @ {s.peak_rvol_at or '—'}",
        ),
        inline=False,
    )

    by_turnover_accel = sorted(
        scans,
        key=lambda s: (s.expansion.turnover_expansion_pct if s.expansion else None) or -999,
        reverse=True,
    )
    embed.add_field(
        name="Turnover Acceleration",
        value=_rank_lines(
            by_turnover_accel,
            lambda s, r: (
                f"`{r}` **{s.symbol}** · "
                f"{(s.expansion.turnover_expansion_pct if s.expansion else None) or 0:+.1f}%"
            ),
        ),
        inline=False,
    )

    by_structure = sorted(
        scans,
        key=lambda s: s.structure.quality_score if s.structure else 0,
        reverse=True,
    )
    embed.add_field(
        name="Market Structure Quality",
        value=_rank_lines(
            by_structure,
            lambda s, r: (
                f"`{r}` **{s.symbol}** · {s.structure.quality_score if s.structure else 0}/100 · "
                f"{s.market_structure_state.title()}"
            ),
        ),
        inline=False,
    )

    by_runner = sorted(scans, key=lambda s: s.historical_runner_score, reverse=True)
    embed.add_field(
        name="Historical Runner Score",
        value=_rank_lines(
            by_runner,
            lambda s, r: f"`{r}` **{s.symbol}** · {s.historical_runner_score}/100",
        ),
        inline=False,
    )

    by_persistence = sorted(scans, key=lambda s: s.liquidity_persistence_score or 0, reverse=True)
    embed.add_field(
        name="Liquidity Persistence Score",
        value=_rank_lines(
            by_persistence,
            lambda s, r: f"`{r}` **{s.symbol}** · {s.liquidity_persistence_score or 0}/100",
        ),
        inline=False,
    )

    embed.set_footer(text=f"Symbols scanned: {len(scans)}")
    return embed
