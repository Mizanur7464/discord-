"""HTML pages for the Benzinga news reader."""

from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.news.benzinga import BenzingaArticle
from bot.utils.config import DEFAULT_BOT_NAME

_ET = ZoneInfo("America/New_York")


def _format_published_et(published: str) -> str:
    if not published:
        return ""
    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        return dt.astimezone(_ET).strftime("%b %d, %Y %I:%M %p ET").lstrip("0")
    except (TypeError, ValueError):
        return published


def _article_body_html(article: BenzingaArticle) -> str:
    body = str(article.body or "").strip()
    if body:
        return body
    return f"<p>{html.escape(article.title)}</p>"


def render_article_page(article: BenzingaArticle, *, brand_name: str = "") -> str:
    title = html.escape(article.title)
    published = html.escape(_format_published_et(article.published))
    brand = html.escape(brand_name or DEFAULT_BOT_NAME)
    symbols = " ".join(
        f'<a class="ticker" href="https://www.benzinga.com/quote/{html.escape(symbol)}">{html.escape(symbol)}</a>'
        for symbol in article.symbols[:8]
    )
    body = _article_body_html(article)
    source_url = html.escape(article.url or "https://www.benzinga.com")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #11131a;
      --panel: #1a1d27;
      --text: #f3f4f6;
      --muted: #9ca3af;
      --accent: #60a5fa;
      --border: #2a2f3d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .wrap {{
      max-width: 760px;
      margin: 0 auto;
      padding: 24px 16px 48px;
    }}
    .brand {{
      margin-bottom: 14px;
      color: var(--accent);
      font-size: 0.95rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 24px;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 1.65rem;
      line-height: 1.25;
    }}
    .meta {{
      color: var(--muted);
      font-size: 0.92rem;
      margin-bottom: 18px;
    }}
    .tickers {{ margin-top: 8px; }}
    .ticker {{
      display: inline-block;
      margin: 0 8px 8px 0;
      padding: 4px 10px;
      border-radius: 999px;
      background: #0f172a;
      border: 1px solid var(--border);
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
      font-size: 0.85rem;
    }}
    .content p {{ margin: 0 0 1rem; }}
    .content a {{ color: var(--accent); }}
    .footer {{
      margin-top: 24px;
      color: var(--muted);
      font-size: 0.85rem;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="brand">{brand}</div>
    <article class="card">
      <h1>{title}</h1>
      <div class="meta">
        {f"<div>{published}</div>" if published else ""}
        {f'<div class="tickers">{symbols}</div>' if symbols else ""}
      </div>
      <div class="content">{body}</div>
      <div class="footer">
        {brand} news reader.
        <a href="{source_url}" rel="noopener noreferrer">Original source</a>
      </div>
    </article>
  </div>
</body>
</html>"""


def _num(value, *, prefix: str = "", suffix: str = "") -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return html.escape(str(value))
    av = abs(v)
    if av >= 1_000_000_000:
        text = f"{v / 1_000_000_000:.2f}B"
    elif av >= 1_000_000:
        text = f"{v / 1_000_000:.2f}M"
    elif av >= 1_000:
        text = f"{v / 1_000:.1f}K"
    elif isinstance(value, float) and not float(value).is_integer():
        text = f"{v:.2f}"
    else:
        text = f"{v:,.0f}"
    return f"{prefix}{text}{suffix}"


def _pct(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "—"


def _rows_html(rows: list[tuple[str, str]]) -> str:
    return "".join(
        f'<tr><td class="k">{html.escape(label)}</td><td class="v">{value}</td></tr>'
        for label, value in rows
    )


def render_scan_page(scan, *, brand_name: str = "") -> str:
    """Render full scanner details for a symbol as a paywall-free HTML page."""
    brand = html.escape(brand_name or DEFAULT_BOT_NAME)
    symbol = html.escape(str(getattr(scan, "symbol", "") or ""))
    grade = html.escape(str(getattr(scan, "grade", "") or "—"))
    score = int(getattr(scan, "score", 0) or 0)
    structure = getattr(scan, "structure", None)

    market_rows = _rows_html(
        [
            ("Price", _num(getattr(scan, "price", None), prefix="$")),
            ("Float", _num(getattr(scan, "float_shares", None))),
            ("RVOL", _num(getattr(scan, "rvol", None), suffix="x")),
            ("Volume", _num(getattr(scan, "daily_volume", None))),
            ("Gap", _pct(getattr(scan, "gap_pct", None))),
            ("Session", _pct(getattr(scan, "session_change_pct", None))),
            ("Turnover", _num(getattr(scan, "turnover_usd", None), prefix="$")),
            ("Market cap", _num(getattr(scan, "market_cap_usd", None), prefix="$")),
        ]
    )
    extra_rows = _rows_html(
        [
            ("Liquidity rank", f"#{scan.liquidity_rank}" if getattr(scan, "liquidity_rank", None) else "—"),
            ("Current RVOL", _num(getattr(scan, "current_rvol", None), suffix="x")),
            ("From HOD", _pct(structure.distance_from_hod_pct) if structure else "—"),
            ("Catalyst", html.escape(str(getattr(scan, "catalyst_label", "") or "—"))),
            ("Market structure", html.escape(str(getattr(scan, "market_structure_state", "") or "—").title())),
            ("Watchlist activity", html.escape(str(getattr(scan, "watchlist_activity", "") or "None"))),
        ]
    )

    reasons = getattr(scan, "reasons", None) or []
    warnings = getattr(scan, "warnings", None) or []
    checks = "".join(f"<li>{html.escape(str(r))}</li>" for r in reasons[:8])
    warns = "".join(f"<li>{html.escape(str(w))}</li>" for w in warnings[:8])
    checks_html = f'<h2>Checks</h2><ul class="checks">{checks}</ul>' if checks else ""
    warns_html = f'<h2>Warnings</h2><ul class="warns">{warns}</ul>' if warns else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{symbol} · Scan details</title>
  <style>
    :root {{ color-scheme: dark; --bg:#11131a; --panel:#1a1d27; --text:#f3f4f6; --muted:#9ca3af; --accent:#60a5fa; --border:#2a2f3d; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    .wrap {{ max-width:760px; margin:0 auto; padding:24px 16px 48px; }}
    .brand {{ margin-bottom:14px; color:var(--accent); font-weight:700; letter-spacing:.04em; text-transform:uppercase; font-size:.95rem; }}
    .card {{ background:var(--panel); border:1px solid var(--border); border-radius:14px; padding:24px; }}
    h1 {{ margin:0 0 6px; font-size:1.6rem; }}
    .score {{ color:var(--accent); font-weight:700; margin-bottom:16px; }}
    h2 {{ font-size:1rem; margin:20px 0 8px; color:var(--muted); text-transform:uppercase; letter-spacing:.03em; }}
    table {{ width:100%; border-collapse:collapse; }}
    td {{ padding:7px 0; border-bottom:1px solid var(--border); }}
    td.k {{ color:var(--muted); }}
    td.v {{ text-align:right; font-weight:600; }}
    ul {{ margin:0; padding-left:18px; }}
    .footer {{ margin-top:24px; color:var(--muted); font-size:.85rem; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="brand">{brand}</div>
    <div class="card">
      <h1>{symbol}</h1>
      <div class="score">Trading Score {grade} · {score}/100</div>
      <h2>Market</h2>
      <table>{market_rows}</table>
      <h2>Parameters</h2>
      <table>{extra_rows}</table>
      {checks_html}
      {warns_html}
      <div class="footer">{brand} scanner.</div>
    </div>
  </div>
</body>
</html>"""


def render_not_found_page(article_id: str, *, brand_name: str = "") -> str:
    safe_id = html.escape(article_id)
    brand = html.escape(brand_name or DEFAULT_BOT_NAME)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Article not found</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #11131a;
      color: #f3f4f6;
      font: 16px/1.5 sans-serif;
    }}
    .box {{
      max-width: 420px;
      padding: 24px;
      border: 1px solid #2a2f3d;
      border-radius: 12px;
      background: #1a1d27;
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="box">
    <div style="color:#60a5fa;font-weight:700;margin-bottom:12px;">{brand}</div>
    <h1>Article not found</h1>
    <p>We could not load article <code>{safe_id}</code>. It may be older than our cache window.</p>
  </div>
</body>
</html>"""
