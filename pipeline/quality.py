"""Checks run on each day's rows before anything is written.

An error stops the run, so a bad day never reaches the CSVs or BigQuery and the
GitHub Actions run goes red. A warning is recorded in data/quality/checks.csv
and the day is kept.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from pipeline.config import MIN_CURRENCIES, MOVE_FAIL_PCT, MOVE_WARN_PCT, REQUIRED_CURRENCIES


@dataclass
class Result:
    rate_date: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: int = 0
    checks_clean: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def check_day(rows: list[dict], prev_rows: list[dict] | None, accepted: dict | None = None) -> Result:
    """`accepted` maps (rate_date, currency_code) to a reason for moves a person
    has reviewed (data/quality/accepted_moves.csv); those warn instead of fail."""
    accepted = accepted or {}
    res = Result(rate_date=rows[0]["rate_date"] if rows else "?")

    def check(errors: list[str], warnings: list[str] = ()) -> None:
        res.checks += 1
        res.errors.extend(errors)
        res.warnings.extend(warnings)
        if not errors and not warnings:
            res.checks_clean += 1

    codes = [r["currency_code"] for r in rows]

    check([f"only {len(rows)} currencies, expected >= {MIN_CURRENCIES}"] if len(rows) < MIN_CURRENCIES else [])

    missing = sorted(set(REQUIRED_CURRENCIES) - set(codes))
    check([f"missing required currencies: {', '.join(missing)}"] if missing else [])

    dupes = sorted({c for c in codes if codes.count(c) > 1})
    check([f"duplicate currency codes: {', '.join(dupes)}"] if dupes else [])

    bad = [r["currency_code"] for r in rows if r["rate"] <= 0 or r["quantity"] <= 0]
    check([f"non-positive rate or quantity: {', '.join(bad)}"] if bad else [])

    # NBG occasionally re-issues a set after it took effect (rates valid
    # 2025-10-04 carry a publish time of 2025-10-06). Keep it, but flag it.
    late = sorted({r["published_at"][:10] for r in rows if r["published_at"][:10] > r["rate_date"]})
    check([], [f"re-issued by NBG on {', '.join(late)}, after the date it is valid for"] if late else [])

    if not prev_rows:
        return res

    prev = {r["currency_code"]: r for r in prev_rows}
    added, dropped = sorted(set(codes) - set(prev)), sorted(set(prev) - set(codes))
    check(
        [],
        ([f"new currencies: {', '.join(added)}"] if added else [])
        + ([f"currencies dropped: {', '.join(dropped)}"] if dropped else []),
    )

    move_errors, move_warnings = [], []
    for r in rows:
        p = prev.get(r["currency_code"])
        if not p:
            continue
        pct = (r["rate_per_unit"] - p["rate_per_unit"]) / p["rate_per_unit"] * 100
        msg = f"{r['currency_code']} moved {pct:+.2f}% vs {p['rate_date']}"
        if abs(pct) > MOVE_FAIL_PCT and (r["rate_date"], r["currency_code"]) in accepted:
            move_warnings.append(f"{msg} (reviewed and accepted)")
        elif abs(pct) > MOVE_FAIL_PCT:
            move_errors.append(f"{msg}; if this is real, add it to data/quality/accepted_moves.csv")
        elif abs(pct) > MOVE_WARN_PCT:
            move_warnings.append(msg)
    check(move_errors, move_warnings)

    # Reconcile against the source: NBG publishes its own day-over-day diff.
    # Our diff should match it to the 4th decimal when the quantity is unchanged.
    mismatched = [
        f"{r['currency_code']} ours {r['rate'] - p['rate']:+} vs NBG {r['nbg_diff']:+}"
        for r in rows
        if (p := prev.get(r["currency_code"]))
        and p["quantity"] == r["quantity"]
        and abs((r["rate"] - p["rate"]) - r["nbg_diff"]) > Decimal("0.00005")
    ]
    check([], [f"diff mismatch: {', '.join(mismatched)}"] if mismatched else [])

    return res
