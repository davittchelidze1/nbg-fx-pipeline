from decimal import Decimal

from pipeline.quality import check_day


def _edit(rows, code, **changes):
    return [{**r, **changes} if r["currency_code"] == code else r for r in rows]


def test_real_consecutive_days_pass_clean(rows_fri, rows_tue):
    res = check_day(rows_tue, rows_fri)
    assert res.ok
    assert res.warnings == []
    assert res.checks == res.checks_clean == 8


def test_first_day_skips_comparisons(rows_tue):
    res = check_day(rows_tue, None)
    assert res.ok and res.checks == 5


def test_missing_required_currency_fails(rows_fri, rows_tue):
    res = check_day([r for r in rows_tue if r["currency_code"] != "USD"], rows_fri)
    assert not res.ok
    assert any("USD" in e for e in res.errors)


def test_duplicate_currency_fails(rows_fri, rows_tue):
    res = check_day(rows_tue + rows_tue[:1], rows_fri)
    assert any("duplicate" in e for e in res.errors)


def test_too_few_currencies_fails(rows_fri, rows_tue):
    keep = {"USD", "EUR", "GBP", "TRY", "RUB"}
    res = check_day([r for r in rows_tue if r["currency_code"] in keep], rows_fri)
    assert any("only 5 currencies" in e for e in res.errors)


def test_large_move_warns_and_huge_move_fails(rows_fri, rows_tue):
    usd_prev = next(r for r in rows_fri if r["currency_code"] == "USD")["rate_per_unit"]

    warned = check_day(_edit(rows_tue, "USD", rate_per_unit=usd_prev * Decimal("1.06")), rows_fri)
    assert warned.ok
    assert any("USD moved +6.00%" in w for w in warned.warnings)

    failed = check_day(_edit(rows_tue, "USD", rate_per_unit=usd_prev * 2), rows_fri)
    assert not failed.ok


def test_reviewed_huge_move_is_accepted(rows_fri, rows_tue):
    # Seen for real: IRR -96% on 2026-01-27 when NBG switched which rial rate it publishes.
    irr_prev = next(r for r in rows_fri if r["currency_code"] == "IRR")["rate_per_unit"]
    rows = _edit(rows_tue, "IRR", rate_per_unit=irr_prev / 25)
    accepted = {("2026-10-13", "IRR"): "reviewed"}

    assert not check_day(rows, rows_fri).ok
    res = check_day(rows, rows_fri, accepted)
    assert res.ok
    assert any("IRR moved -96.00%" in w and "accepted" in w for w in res.warnings)


def test_diff_that_disagrees_with_nbg_is_flagged(rows_fri, rows_tue):
    res = check_day(_edit(rows_tue, "EUR", nbg_diff=Decimal("0.0500")), rows_fri)
    assert res.ok
    assert any(w.startswith("diff mismatch: EUR") for w in res.warnings)


def test_set_reissued_after_its_valid_date_warns(rows_fri, rows_tue):
    # Seen for real: the set valid 2025-10-04 carries a publish time of 2025-10-06.
    reissued = [{**r, "published_at": "2026-10-15T17:01:06.251Z"} for r in rows_tue]
    res = check_day(reissued, rows_fri)
    assert res.ok
    assert any("re-issued by NBG on 2026-10-15" in w for w in res.warnings)


def test_changed_currency_list_warns(rows_fri, rows_tue):
    res = check_day([r for r in rows_tue if r["currency_code"] != "ZAR"], rows_fri)
    assert res.ok
    assert "currencies dropped: ZAR" in res.warnings
