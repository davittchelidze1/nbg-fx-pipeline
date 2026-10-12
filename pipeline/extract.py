"""Pull official GEL exchange rates from the National Bank of Georgia API.

NBG sets rates once per business day (around 17:00 Tbilisi) for the next day.
Asking for a date with no new rates (a weekend, a holiday, or tomorrow before
publication) returns the latest earlier set, so every response is keyed by
the date NBG says the rates are valid for, not by the date we asked for.
"""

import time
from datetime import date, datetime, timedelta

import requests

from pipeline.config import API_URL, TBILISI


def fetch_day(day: date, retries: int = 3) -> dict:
    """Return NBG's response for `day`: {"date": ..., "currencies": [...]}."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(API_URL, params={"date": day.isoformat()}, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, list) or len(payload) != 1:
                raise ValueError(f"unexpected payload shape for {day}: {str(payload)[:200]}")
            return payload[0]
        except (requests.RequestException, ValueError):
            if attempt == retries:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def valid_date(payload: dict) -> date:
    return date.fromisoformat(payload["date"][:10])


def tomorrow_in_tbilisi() -> date:
    return datetime.now(TBILISI).date() + timedelta(days=1)


PAUSE_SECONDS = 0.2  # be polite to the API during backfills


def fetch_range(start: date, end: date, fetch=None):
    """Yield one payload per distinct rate date found between `start` and `end`.

    Weekend and holiday requests return the previous set again; those repeats
    are dropped here. Whether a set is new, unchanged or revised is decided by
    the caller against what is already stored.
    """
    fetch = fetch or fetch_day
    seen = set()
    day = start
    while day <= end:
        payload = fetch(day)
        rate_date = valid_date(payload)
        if rate_date not in seen:
            seen.add(rate_date)
            yield payload
        day += timedelta(days=1)
        if PAUSE_SECONDS:
            time.sleep(PAUSE_SECONDS)
