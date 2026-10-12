"""The repo is the source of truth.

data/raw/YYYY/MM/DD.json   the API response exactly as NBG sent it
data/rates/YYYY-MM.csv     cleaned rows, one file per month, keyed by
                           (rate_date, currency_code)

Writes are upserts, so a re-run or a backfill over existing dates rewrites the
same bytes and git sees no change. BigQuery can be rebuilt from these files.
"""

import csv
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal

from pipeline.config import ACCEPTED_MOVES, QUALITY_LOG, RATES_DIR, RAW_DIR
from pipeline.extract import valid_date
from pipeline.transform import COLUMNS

QUALITY_COLUMNS = ["rate_date", "checks_passed", "warnings", "detail"]


def raw_path(day: date):
    return RAW_DIR / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}.json"


def load_raw(day: date) -> dict | None:
    path = raw_path(day)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save_raw(payload: dict) -> None:
    path = raw_path(valid_date(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _parse(row: dict) -> dict:
    return {
        **row,
        "quantity": int(row["quantity"]),
        "rate": Decimal(row["rate"]),
        "rate_per_unit": Decimal(row["rate_per_unit"]),
        "nbg_diff": Decimal(row["nbg_diff"]),
    }


def _read_month(path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [_parse(r) for r in csv.DictReader(f)]


def read_rates() -> list[dict]:
    rows = []
    for path in sorted(RATES_DIR.glob("*.csv")):
        rows.extend(_read_month(path))
    return rows


def known_dates() -> set[date]:
    return {date.fromisoformat(r["rate_date"]) for r in read_rates()}


def upsert_rates(rows: list[dict]) -> None:
    by_month = defaultdict(list)
    for r in rows:
        by_month[r["rate_date"][:7]].append(r)

    RATES_DIR.mkdir(parents=True, exist_ok=True)
    for month, new_rows in by_month.items():
        path = RATES_DIR / f"{month}.csv"
        merged = {(r["rate_date"], r["currency_code"]): r for r in _read_month(path)}
        merged.update({(r["rate_date"], r["currency_code"]): r for r in new_rows})
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            for key in sorted(merged):
                writer.writerow(merged[key])


def accepted_moves() -> dict[tuple[str, str], str]:
    """Moves a person reviewed and accepted: (rate_date, currency_code) -> reason."""
    if not ACCEPTED_MOVES.exists():
        return {}
    with ACCEPTED_MOVES.open(newline="", encoding="utf-8") as f:
        return {(r["rate_date"], r["currency_code"]): r["reason"] for r in csv.DictReader(f)}


def log_checks(rate_date: str, passed: int, warnings: list[str]) -> None:
    """Append one line per rate date that made it through the checks."""
    QUALITY_LOG.parent.mkdir(parents=True, exist_ok=True)
    new_file = not QUALITY_LOG.exists()
    with QUALITY_LOG.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=QUALITY_COLUMNS, lineterminator="\n")
        if new_file:
            writer.writeheader()
        writer.writerow(
            {
                "rate_date": rate_date,
                "checks_passed": passed,
                "warnings": len(warnings),
                "detail": "; ".join(warnings),
            }
        )
