"""Flatten an NBG response into one row per currency.

NBG quotes some currencies per 10, 100 or 1000 units (AMD per 1000, JPY per
100), so `rate` alone can't be compared across currencies or across a change
in quantity. `rate_per_unit` is the comparable number: GEL for one unit.
"""

from decimal import ROUND_HALF_UP, Decimal

from pipeline.extract import valid_date

COLUMNS = [
    "rate_date",
    "currency_code",
    "currency_name",
    "quantity",
    "rate",
    "rate_per_unit",
    "nbg_diff",
    "published_at",
]

FOUR_DP = Decimal("0.0001")
EIGHT_DP = Decimal("0.00000001")


def _dec(value, places: Decimal) -> Decimal:
    # str() first: Decimal(2.6005) would carry the float's binary noise.
    return Decimal(str(value)).quantize(places, rounding=ROUND_HALF_UP)


def to_rows(payload: dict) -> list[dict]:
    rate_date = valid_date(payload).isoformat()
    rows = []
    for c in payload["currencies"]:
        quantity = int(c["quantity"])
        rate = _dec(c["rate"], FOUR_DP)
        rows.append(
            {
                "rate_date": rate_date,
                "currency_code": c["code"],
                "currency_name": c["name"],
                "quantity": quantity,
                "rate": rate,
                "rate_per_unit": (rate / quantity).quantize(EIGHT_DP, rounding=ROUND_HALF_UP),
                "nbg_diff": _dec(c["diff"], FOUR_DP),
                "published_at": c["date"],
            }
        )
    return sorted(rows, key=lambda r: r["currency_code"])
