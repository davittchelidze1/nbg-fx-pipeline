"""python -m pipeline <command>

run        fetch new rate sets, and re-check the last week for revisions (the daily job)
backfill   fetch a historical range: --start 2024-10-01 [--end 2025-01-31]
load       reload every stored row into BigQuery (rebuilds the warehouse)
report     rebuild README summary and chart from the CSVs
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

from pipeline import extract, quality, report, storage, transform
from pipeline.config import GCP_PROJECT

# The daily run re-checks the last week of rate sets, because NBG sometimes
# re-issues a set after it took effect.
LOOKBACK_DAYS = 7


def _github_output(**values) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")


def _load(rows: list[dict]) -> None:
    if not GCP_PROJECT:
        print("GCP_PROJECT not set, skipping BigQuery load")
        return
    from pipeline import warehouse  # keep the cloud client out of offline runs

    audit = warehouse.load(rows)
    print(
        f"BigQuery: {audit['rows_inserted']} inserted, {audit['rows_updated']} updated "
        f"({audit['rate_date_min']}..{audit['rate_date_max']}, {audit['bytes_billed'] or 0:,} bytes billed)"
    )


def ingest(start: date, end: date, load: bool) -> int:
    """Fetch, check and store every rate set between start and end that is new
    or that NBG has changed since we stored it. Returns how many dates changed."""
    by_date = defaultdict(list)
    for r in storage.read_rates():
        by_date[r["rate_date"]].append(r)

    accepted = storage.accepted_moves()
    fetched, revised = [], []
    for payload in extract.fetch_range(start, end):
        rows = transform.to_rows(payload)
        day = rows[0]["rate_date"]
        if day in by_date:
            if storage.load_raw(date.fromisoformat(day)) == payload:
                continue
            revised.append(day)

        earlier = [d for d in by_date if d < day]
        result = quality.check_day(rows, by_date[max(earlier)] if earlier else None, accepted)
        if not result.ok:
            print(f"{day}: FAILED quality checks, nothing written", file=sys.stderr)
            for e in result.errors:
                print(f"  - {e}", file=sys.stderr)
            sys.exit(1)
        if day in revised:
            result.warnings.append("changed by NBG since it was first stored")
        for w in result.warnings:
            print(f"{day}: warning: {w}")
        by_date[day] = rows
        fetched.append((payload, rows, result))

    if not fetched:
        print(f"No new or changed rates between {start} and {end}")
        _github_output(changed=0)
        return 0

    all_rows = []
    for payload, rows, result in sorted(fetched, key=lambda f: f[1][0]["rate_date"]):
        storage.save_raw(payload)
        storage.log_checks(result.rate_date, result.checks_clean, result.warnings)
        all_rows.extend(rows)
    storage.upsert_rates(all_rows)

    dates = sorted({r["rate_date"] for r in all_rows})
    new = [d for d in dates if d not in revised]
    print(f"Stored {len(all_rows)} rows for {len(dates)} rate date(s): {dates[0]}..{dates[-1]}")

    if load:
        _load(all_rows)
    report.build()

    parts = []
    if new:
        span = new[0] if len(new) == 1 else f"{new[0]}..{new[-1]}"
        parts.append(f"NBG rates valid {span} ({sum(r['rate_date'] in new for r in all_rows)} rows)")
    if revised:
        parts.append(f"NBG revised {', '.join(revised)}")
    _github_output(changed=len(dates), message="; ".join(parts))
    return len(dates)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--no-load", action="store_true")

    bf = sub.add_parser("backfill")
    bf.add_argument("--start", type=date.fromisoformat, required=True)
    bf.add_argument("--end", type=date.fromisoformat, default=None)
    bf.add_argument("--no-load", action="store_true")

    sub.add_parser("load")
    sub.add_parser("report")

    args = parser.parse_args(argv)

    if args.cmd == "run":
        known = storage.known_dates()
        if not known:
            sys.exit("No stored rates yet, run a backfill first")
        ingest(max(known) - timedelta(days=LOOKBACK_DAYS), extract.tomorrow_in_tbilisi(), load=not args.no_load)
    elif args.cmd == "backfill":
        ingest(args.start, args.end or extract.tomorrow_in_tbilisi(), load=not args.no_load)
    elif args.cmd == "load":
        _load(storage.read_rates())
    elif args.cmd == "report":
        report.build()


if __name__ == "__main__":
    main()
