"""Settings shared by every stage. Cloud settings come from the environment."""

import os
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
RATES_DIR = ROOT / "data" / "rates"
QUALITY_LOG = ROOT / "data" / "quality" / "checks.csv"
ACCEPTED_MOVES = ROOT / "data" / "quality" / "accepted_moves.csv"
DOCS_DIR = ROOT / "docs"
README = ROOT / "README.md"
SQL_DIR = ROOT / "sql"

API_URL = "https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/"

# Georgia has stayed on UTC+4 with no daylight saving since 2005.
TBILISI = timezone(timedelta(hours=4))

# Currencies the bank-facing reports depend on; a day without them is rejected.
REQUIRED_CURRENCIES = ("USD", "EUR", "GBP", "TRY", "RUB")
MIN_CURRENCIES = 40

# Day-over-day move per unit: above WARN it is logged, above FAIL the run stops.
MOVE_WARN_PCT = 5.0
MOVE_FAIL_PCT = 50.0

GCP_PROJECT = os.environ.get("GCP_PROJECT")
BQ_DATASET = os.environ.get("BQ_DATASET", "nbg_fx")
BQ_LOCATION = os.environ.get("BQ_LOCATION", "EU")
