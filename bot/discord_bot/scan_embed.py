"""Discord embed formatting for realtime scanner / watchlist alerts."""

from __future__ import annotations

import discord

from bot.trading.scanner import ScanResult


def _compact_number(value: float | None, *, prefix: str = "", suffix: str = "") -> str:
    if value is None:
        return "—"
    abs_val = abs(value)
    if abs_val >= 1_000_000_000:
        text = f"{value / 1_000_000_000:.2f}B"
    elif abs_val >= 1_000_000:
        text = f"{value / 1_000_000:.2f}M"
    elif abs_val >= 1_000:
        text = f"{value / 1_000:.1f}K"
    else:
        text = f"{value:,.2f}" if isinstance(value, float) and not value.is_integer() else f"{value:,.0f}"
    return f"{prefix}{text}{suffix}"


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.1f}%"


def _grade_color(grade: str, *, actionable: bool) -> discord.Color:
    if actionable:
        return discord.Color.from_rgb(87, 242, 135)
    palette = {
        "A": discord.Color.from_rgb(87, 242, 135),
        "B": discord.Color.from_rgb(59, 165, 93),
        "C": discord.Color.from_rgb(254, 231, 92),
        "D": discord.Color.from_rgb(250, 166, 26),
    }
    return palette.get(grade.upper(), discord.Color.from_rgb(237, 66, 69))


def _table(rows: list[tuple[str, str]]) -> str:
    label_w = max(len(label) for label, _ in rows)
    lines = [f"{'':<{label_w}}  {'─' * 8}", *[f"{label:<{label_w}}  {value}" for label, value in rows]]
    return "```\n" + "\n".join(lines) + "\n```"


def _additional_parameters_table(scan: ScanResult) -> str:
    exp = scan.expansion
    peak_recorder = (
        f"session max {_compact_number(scan.peak_rvol, suffix='x')}"
        if scan.peak_rvol is not None
        else "—"
    )
    peak_rank = f"#{scan.peak_rvol_rank}" if scan.peak_rvol_rank else "—"
    return _table(
        [
            (
                "Peak RVOL + Time",
                f"{_compact_number(scan.peak_rvol, suffix='x')} @ {scan.peak_rvol_at or '—'}",
            ),
            ("Peak RVOL Recorder", peak_recorder),
            ("Peak RVOL Ranking", peak_rank),
            ("Current RVOL", _compact_number(scan.current_rvol, suffix="x") if scan.current_rvol else "—"),
            ("RVOL expansion", _pct(exp.rvol_expansion_pct) if exp else "—"),
            ("Volume expansion", _pct(exp.volume_expansion_pct) if exp else "—"),
            ("Turnover expansion", _pct(exp.turnover_expansion_pct) if exp else "—"),
            ("Short-term price acceleration", _pct(exp.price_acceleration_pct) if exp else "—"),
            (
                "Liquidity expansion",
                f"{scan.liquidity_expansion}/100" if scan.liquidity_expansion is not None else "—",
            ),
            ("Liquidity persistence", f"{scan.liquidity_persistence_score}/100"),
            ("Turnover acceleration", _pct(scan.turnover_acceleration_pct)),
            ("Watchlist activity", scan.watchlist_activity or "None"),
            ("Catalyst detection", scan.catalyst_label),
            ("Market structure state", scan.market_structure_state.title()),
        ]
    )


def _resolve_min_score(scan: ScanResult, default_min: int, profiles: dict) -> int:
    if scan.profile_name and profiles:
        profile = profiles.get(scan.profile_name)
        if profile:
            return profile.min_alert_score
    return default_min


def build_scan_embed(
    scan: ScanResult,
    *,
    min_score: int,
    title_prefix: str = "Realtime Scanner",
) -> discord.Embed:
    actionable = scan.score >= min_score
    status = "✅ Actionable setup" if actionable else f"⏸ Below threshold ({min_score})"
    color = _grade_color(scan.grade, actionable=actionable)

    embed = discord.Embed(
        title=f"🔎 {title_prefix} · {scan.symbol}",
        description=f"**Trading Score {scan.grade} · {scan.score}/100**\n{status}",
        color=color,
    )

    embed.add_field(
        name="📊 Analysis · Market",
        value=_table(
            [
                ("Price", _compact_number(scan.price, prefix="$")),
                ("Float", _compact_number(scan.float_shares)),
                ("RVOL", _compact_number(scan.rvol, suffix="x") if scan.rvol is not None else "—"),
                ("Volume", f"{scan.daily_volume:,}" if scan.daily_volume is not None else "—"),
                ("Gap", _pct(scan.gap_pct)),
                ("Session", _pct(scan.session_change_pct)),
                ("Turnover", _compact_number(scan.turnover_usd, prefix="$")),
                ("MCap", _compact_number(scan.market_cap_usd, prefix="$")),
            ]
        ),
        inline=False,
    )

    embed.add_field(
        name="📋 Additional Parameters",
        value=_additional_parameters_table(scan),
        inline=False,
    )

    embed.add_field(
        name="💧 Liquidity Ranking",
        value=_table(
            [
                ("Rank", f"#{scan.liquidity_rank}" if scan.liquidity_rank else "—"),
                ("Percentile", f"{scan.liquidity_percentile}%" if scan.liquidity_percentile is not None else "—"),
                ("Liq Score", f"{scan.liquidity_score}/100" if scan.liquidity_score is not None else "—"),
                ("Runner Score", f"{scan.historical_runner_score}/100"),
            ]
        ),
        inline=True,
    )

    structure = scan.structure
    embed.add_field(
        name="🏗 Structure Quality",
        value=_table(
            [
                ("Quality", f"{structure.quality_score}/100" if structure else "—"),
                ("HOD Break", "Yes" if structure and structure.hod_break else "No"),
                ("From HOD", _pct(structure.distance_from_hod_pct) if structure else "—"),
            ]
        ),
        inline=True,
    )

    if scan.timeframes and scan.timeframes.summary:
        embed.add_field(name="⏱ Timeframes", value=scan.timeframes.summary[:1024], inline=False)

    if scan.reasons:
        embed.add_field(
            name="✅ Checks",
            value="\n".join(f"• {reason}" for reason in scan.reasons[:6])[:1024],
            inline=True,
        )
    if scan.warnings:
        embed.add_field(
            name="⚠️ Warnings",
            value="\n".join(f"• {warning}" for warning in scan.warnings[:6])[:1024],
            inline=True,
        )

    entry_lines: list[str] = []
    if scan.pullback:
        entry_lines.append(scan.pullback.summary)
    if scan.suggested_limit_price:
        entry_lines.append(f"Suggested limit: **{_compact_number(scan.suggested_limit_price, prefix='$')}**")
    if actionable:
        entry_lines.append(f"Manual confirm: `/buy {scan.symbol}`")
    if entry_lines:
        embed.add_field(name="🎯 Entry", value="\n".join(entry_lines)[:1024], inline=False)

    tags = ["Real-Time Scanner", "Watchlists", "Alert System"]
    if scan.is_repeat_runner:
        tags.append("Runner Intelligence")
    embed.set_footer(text=" · ".join(tags))

    return embed


def format_scan_summary(scan: ScanResult, *, min_score: int) -> str:
    actionable = scan.score >= min_score
    action = f"Confirm `/buy {scan.symbol}`" if actionable else "No auto action"
    return (
        f"Score {scan.grade} ({scan.score}/100) — {action}. "
        f"Catalyst: {scan.catalyst_label} · Structure: {scan.market_structure_state}"
    )
