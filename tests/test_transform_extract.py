from datetime import date
from decimal import Decimal

from pipeline import extract


def test_rows_are_keyed_by_valid_date(rows_tue):
    assert {r["rate_date"] for r in rows_tue} == {"2026-10-13"}
    assert [r["currency_code"] for r in rows_tue] == sorted(r["currency_code"] for r in rows_tue)


def test_rate_per_unit_accounts_for_quantity(rows_tue):
    amd = next(r for r in rows_tue if r["currency_code"] == "AMD")
    assert amd["quantity"] == 1000
    assert amd["rate"] == Decimal("7.1731")
    assert amd["rate_per_unit"] == Decimal("0.00717310")


def test_decimals_carry_no_float_noise(rows_tue):
    aed = next(r for r in rows_tue if r["currency_code"] == "AED")
    # JSON has 7.077; the stored value keeps NBG's 4 decimals exactly.
    assert str(aed["rate"]) == "7.0770"
    assert str(aed["nbg_diff"]) == "-0.0030"


def test_fetch_range_drops_weekend_repeats(payload_fri, payload_tue, monkeypatch):
    monkeypatch.setattr(extract, "PAUSE_SECONDS", 0)
    # Sat, Sun and Mon requests all return Saturday's set; Tuesday is new.
    responses = {
        date(2026, 10, 10): payload_fri,
        date(2026, 10, 11): payload_fri,
        date(2026, 10, 12): payload_fri,
        date(2026, 10, 13): payload_tue,
        date(2026, 10, 14): payload_tue,  # tomorrow's set not published yet
    }
    got = list(extract.fetch_range(date(2026, 10, 10), date(2026, 10, 14), fetch=responses.get))
    assert [extract.valid_date(p) for p in got] == [date(2026, 10, 10), date(2026, 10, 13)]
