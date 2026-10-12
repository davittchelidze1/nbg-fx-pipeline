import json
from datetime import date
from decimal import Decimal

import pytest

from pipeline import report, storage


@pytest.fixture
def repo(tmp_path, monkeypatch):
    rates = tmp_path / "data" / "rates"
    quality = tmp_path / "data" / "quality" / "checks.csv"
    readme = tmp_path / "README.md"
    readme.write_text(f"# title\n\nintro\n\n{report.START}\nold\n{report.END}\n\n## after\n", encoding="utf-8")
    monkeypatch.setattr(storage, "RATES_DIR", rates)
    monkeypatch.setattr(storage, "RAW_DIR", tmp_path / "data" / "raw")
    monkeypatch.setattr(storage, "QUALITY_LOG", quality)
    monkeypatch.setattr(storage, "ACCEPTED_MOVES", tmp_path / "data" / "quality" / "accepted_moves.csv")
    monkeypatch.setattr(report, "RATES_DIR", rates)
    monkeypatch.setattr(report, "QUALITY_LOG", quality)
    monkeypatch.setattr(report, "README", readme)
    monkeypatch.setattr(report, "DOCS_DIR", tmp_path / "docs")
    return tmp_path


def test_upsert_is_idempotent(repo, rows_fri, rows_tue):
    storage.upsert_rates(rows_fri + rows_tue)
    path = repo / "data" / "rates" / "2026-10.csv"
    first = path.read_bytes()

    storage.upsert_rates(rows_tue)
    assert path.read_bytes() == first
    assert b"\r\n" not in first
    assert storage.known_dates() == {date(2026, 10, 10), date(2026, 10, 13)}


def test_upsert_replaces_a_corrected_rate(repo, rows_tue):
    storage.upsert_rates(rows_tue)
    fixed = [{**r, "rate": Decimal("9.9999")} if r["currency_code"] == "USD" else r for r in rows_tue]
    storage.upsert_rates(fixed)

    stored = storage.read_rates()
    assert len(stored) == len(rows_tue)
    assert next(r for r in stored if r["currency_code"] == "USD")["rate"] == Decimal("9.9999")


def test_ingest_stores_new_skips_unchanged_and_picks_up_revisions(repo, payload_fri, payload_tue, monkeypatch):
    from pipeline import __main__ as cli
    from pipeline import extract

    monkeypatch.setattr(extract, "PAUSE_SECONDS", 0)
    served = {date(2026, 10, 10): payload_fri, date(2026, 10, 13): payload_tue}
    monkeypatch.setattr(extract, "fetch_day", lambda d: served[max(k for k in served if k <= d)])
    window = (date(2026, 10, 10), date(2026, 10, 14))

    assert cli.ingest(*window, load=False) == 2
    csv_before = (repo / "data" / "rates" / "2026-10.csv").read_bytes()

    assert cli.ingest(*window, load=False) == 0  # nothing new, nothing changed
    assert (repo / "data" / "rates" / "2026-10.csv").read_bytes() == csv_before

    # NBG re-issues Saturday's set with a corrected USD rate.
    fixed = json.loads(json.dumps(payload_fri))
    usd = next(c for c in fixed["currencies"] if c["code"] == "USD")
    usd["rate"] = round(usd["rate"] + 0.0010, 4)
    served[date(2026, 10, 10)] = fixed

    assert cli.ingest(*window, load=False) == 1
    stored = {(r["rate_date"], r["currency_code"]): r for r in storage.read_rates()}
    assert stored[("2026-10-10", "USD")]["rate"] == Decimal(str(usd["rate"])).quantize(Decimal("0.0001"))
    log = (repo / "data" / "quality" / "checks.csv").read_text(encoding="utf-8")
    assert "changed by NBG since it was first stored" in log


def test_report_rewrites_only_the_marked_block(repo, rows_fri, rows_tue):
    storage.upsert_rates(rows_fri + rows_tue)
    report.build()

    readme = (repo / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# title\n\nintro\n\n")
    assert readme.endswith("\n\n## after\n")
    assert "old" not in readme
    assert "Rates valid for Tuesday, 13 October 2026" in readme
    assert "| 🇺🇸 1 USD |" in readme

    svg = (repo / "docs" / "usd_eur.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg") and "USD" in svg and "EUR" in svg
