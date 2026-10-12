"""Rebuild the README summary and the chart from the repo's CSVs with DuckDB.

Runs entirely offline, so the report keeps working without BigQuery.
"""

from datetime import date, timedelta

import duckdb

from pipeline.config import DOCS_DIR, QUALITY_LOG, RATES_DIR, README

START, END = "<!-- report:start -->", "<!-- report:end -->"

HEADLINE = [("USD", "🇺🇸"), ("EUR", "🇪🇺"), ("GBP", "🇬🇧"), ("TRY", "🇹🇷"), ("RUB", "🇷🇺"), ("AZN", "🇦🇿"), ("AMD", "🇦🇲")]

CSV_COLUMNS = (
    "{'rate_date': 'DATE', 'currency_code': 'VARCHAR', 'currency_name': 'VARCHAR', "
    "'quantity': 'INTEGER', 'rate': 'DECIMAL(18,4)', 'rate_per_unit': 'DECIMAL(18,8)', "
    "'nbg_diff': 'DECIMAL(18,4)', 'published_at': 'VARCHAR'}"
)

# Same logic as the BigQuery view v_rate_changes, in DuckDB's dialect.
CHANGES_SQL = """
WITH base AS (
  SELECT
    rate_date, currency_code, currency_name, quantity, rate, rate_per_unit,
    lag(rate_per_unit) OVER (PARTITION BY currency_code ORDER BY rate_date) AS prev_rate,
    first_value(rate_per_unit) OVER (
      PARTITION BY currency_code ORDER BY rate_date
      RANGE BETWEEN INTERVAL 30 DAYS PRECEDING AND CURRENT ROW
    ) AS rate_30d_ago
  FROM rates
)
SELECT
  *,
  (rate_per_unit / prev_rate - 1) * 100    AS pct_1d,
  (rate_per_unit / rate_30d_ago - 1) * 100 AS pct_30d
FROM base
"""


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    glob = (RATES_DIR / "*.csv").as_posix()
    con.execute(f"CREATE VIEW rates AS SELECT * FROM read_csv('{glob}', header = true, columns = {CSV_COLUMNS})")
    con.execute(f"CREATE VIEW changes AS {CHANGES_SQL}")
    return con


def _arrow(pct) -> str:
    if pct is None:
        return "–"
    if abs(pct) < 0.005:
        return "0.00%"
    return f"{'▲' if pct > 0 else '▼'} {abs(pct):.2f}%"


def _fetch_dicts(con, sql: str, params=None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def build_markdown(con) -> str:
    latest = con.execute("SELECT max(rate_date) FROM rates").fetchone()[0]
    today = {r["currency_code"]: r for r in _fetch_dicts(con, "SELECT * FROM changes WHERE rate_date = ?", [latest])}

    lines = [
        f"**Rates valid for {latest:%A, %d %B %Y}**",
        "",
        "| Currency | GEL | 1 day | 30 days |",
        "|---|---:|---:|---:|",
    ]
    for code, flag in HEADLINE:
        r = today.get(code)
        if r:
            lines.append(
                f"| {flag} {r['quantity']:,} {code} | {r['rate']:.4f} | {_arrow(r['pct_1d'])} | {_arrow(r['pct_30d'])} |"
            )

    movers = sorted(
        (r for r in today.values() if r["pct_30d"] is not None),
        key=lambda r: abs(r["pct_30d"]),
        reverse=True,
    )[:3]
    if movers:
        moves = ", ".join(f"**{r['currency_code']}** {r['pct_30d']:+.1f}%" for r in movers)
        lines += ["", f"Biggest moves against the lari over 30 days: {moves}."]

    days, rows, first = con.execute("SELECT count(DISTINCT rate_date), count(*), min(rate_date) FROM rates").fetchone()
    warnings = 0
    if QUALITY_LOG.exists():
        since = latest - timedelta(days=30)
        warnings = con.execute(
            f"SELECT coalesce(sum(warnings), 0) FROM read_csv('{QUALITY_LOG.as_posix()}', header = true) "
            "WHERE rate_date > ?",
            [since],
        ).fetchone()[0]
    lines += [
        "",
        f"<sub>{days:,} rate dates · {rows:,} rows · history from {first:%d %b %Y} · "
        f"{warnings} quality warning{'s' if warnings != 1 else ''} in the last 30 days "
        "([log](data/quality/checks.csv))</sub>",
    ]
    return "\n".join(lines)


def build_chart(con, days: int = 365) -> str:
    """Hand-drawn-ish SVG of GEL per USD and per EUR. No plotting library needed."""
    latest = con.execute("SELECT max(rate_date) FROM rates").fetchone()[0]
    since = latest - timedelta(days=days)
    series = {}
    for code in ("USD", "EUR"):
        pts = con.execute(
            "SELECT rate_date, rate_per_unit FROM rates WHERE currency_code = ? AND rate_date > ? ORDER BY rate_date",
            [code, since],
        ).fetchall()
        series[code] = [(d, float(v)) for d, v in pts]

    W, H, L, R, T, B = 820, 300, 56, 92, 46, 40
    values = [v for pts in series.values() for _, v in pts]
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.08 or 0.05
    lo, hi = lo - pad, hi + pad
    x0, x1 = since.toordinal(), latest.toordinal()

    def x(d: date) -> float:
        return L + (d.toordinal() - x0) / (x1 - x0) * (W - L - R)

    def y(v: float) -> float:
        return T + (hi - v) / (hi - lo) * (H - T - B)

    colors = {"USD": "#2f6df6", "EUR": "#ff5a8a"}
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Segoe UI, Helvetica, Arial, sans-serif">',
        f'<rect width="{W}" height="{H}" rx="18" fill="#fff8ec"/>',
        f'<text x="{L}" y="28" font-size="16" font-weight="700" fill="#2b2140">How many lari for one dollar and one euro</text>',
        f'<text x="{W - R + 84}" y="28" font-size="12" fill="#7a6f8f" text-anchor="end">last {days} days · source: NBG</text>',
    ]

    step = 0.05 if hi - lo < 0.6 else 0.1
    tick = round(lo / step + 0.5) * step
    while tick < hi:
        out.append(
            f'<line x1="{L}" x2="{W - R}" y1="{y(tick):.1f}" y2="{y(tick):.1f}" stroke="#eadfcc" stroke-dasharray="3 5"/>'
        )
        out.append(
            f'<text x="{L - 8}" y="{y(tick) + 4:.1f}" font-size="11" fill="#7a6f8f" text-anchor="end">{tick:.2f}</text>'
        )
        tick += step

    month = date(since.year, since.month, 1)
    while month <= latest:
        if month > since:
            out.append(
                f'<text x="{x(month):.1f}" y="{H - 16}" font-size="11" fill="#7a6f8f" text-anchor="middle">{month:%b}</text>'
            )
        month = date(month.year + month.month // 12, month.month % 12 + 1, 1)

    for code, pts in series.items():
        if not pts:
            continue
        path = " ".join(f"{'M' if i == 0 else 'L'}{x(d):.1f},{y(v):.1f}" for i, (d, v) in enumerate(pts))
        c = colors[code]
        d_last, v_last = pts[-1]
        out += [
            f'<path d="{path}" fill="none" stroke="{c}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>',
            f'<circle cx="{x(d_last):.1f}" cy="{y(v_last):.1f}" r="5.5" fill="{c}" stroke="#fff8ec" stroke-width="2"/>',
            f'<text x="{x(d_last) + 10:.1f}" y="{y(v_last) + 4:.1f}" font-size="13" font-weight="700" fill="{c}">{code} {v_last:.4f}</text>',
        ]
    out.append("</svg>")
    return "\n".join(out) + "\n"


def update_readme(markdown: str) -> None:
    text = README.read_text(encoding="utf-8")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    README.write_text(f"{head}{START}\n{markdown}\n{END}{tail}", encoding="utf-8", newline="\n")


def build() -> None:
    con = _connect()
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "usd_eur.svg").write_text(build_chart(con), encoding="utf-8", newline="\n")
    update_readme(build_markdown(con))
