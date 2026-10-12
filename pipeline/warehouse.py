"""Load rows into BigQuery: stage the batch, then MERGE it into daily_rates.

Staging + MERGE (rather than appending) keeps the table free of duplicates no
matter how many times a day is loaded, which is what makes backfills and
retried runs safe.
"""

import os
from datetime import UTC, datetime

from google.cloud import bigquery

from pipeline.config import BQ_DATASET, BQ_LOCATION, GCP_PROJECT, SQL_DIR

STAGING_SCHEMA = [
    bigquery.SchemaField("rate_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("currency_code", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("currency_name", "STRING"),
    bigquery.SchemaField("quantity", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("rate", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("rate_per_unit", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("nbg_diff", "NUMERIC"),
    bigquery.SchemaField("published_at", "TIMESTAMP"),
]


def _sql(name: str) -> str:
    text = (SQL_DIR / "bigquery" / name).read_text(encoding="utf-8")
    return text.replace("{project}", GCP_PROJECT).replace("{dataset}", BQ_DATASET)


def _to_json(row: dict) -> dict:
    return {
        **row,
        "rate": str(row["rate"]),
        "rate_per_unit": str(row["rate_per_unit"]),
        "nbg_diff": str(row["nbg_diff"]),
        # NBG sends "2026-10-12T17:01:08.293Z"; BigQuery JSON loads want a space.
        "published_at": row["published_at"].replace("T", " ").replace("Z", "+00:00"),
    }


def _client() -> bigquery.Client:
    if not GCP_PROJECT:
        raise RuntimeError("GCP_PROJECT is not set")
    return bigquery.Client(project=GCP_PROJECT, location=BQ_LOCATION)


def ensure_tables(client: bigquery.Client | None = None) -> None:
    """Create or refresh tables and the view. Run at the start of every daily
    run, so broken credentials fail the run even on days with no new rates."""
    (client or _client()).query(_sql("tables.sql")).result()


def load(rows: list[dict]) -> dict:
    client = _client()
    ensure_tables(client)

    staging = f"{GCP_PROJECT}.{BQ_DATASET}._stg_daily_rates"
    client.load_table_from_json(
        [_to_json(r) for r in rows],
        staging,
        job_config=bigquery.LoadJobConfig(schema=STAGING_SCHEMA, write_disposition="WRITE_TRUNCATE"),
    ).result()

    dates = sorted(r["rate_date"] for r in rows)
    merge = client.query(
        _sql("merge_daily_rates.sql"),
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("min_date", "DATE", dates[0]),
                bigquery.ScalarQueryParameter("max_date", "DATE", dates[-1]),
            ]
        ),
    )
    merge.result()
    stats = merge.dml_stats

    audit = {
        "loaded_at": datetime.now(UTC).isoformat(sep=" "),
        "job_id": merge.job_id,
        "rate_date_min": dates[0],
        "rate_date_max": dates[-1],
        "rows_in_batch": len(rows),
        "rows_inserted": stats.inserted_row_count,
        "rows_updated": stats.updated_row_count,
        "git_sha": os.environ.get("GITHUB_SHA", "local"),
    }
    audit_table = client.get_table(f"{GCP_PROJECT}.{BQ_DATASET}.load_audit")
    client.load_table_from_json(
        [audit],
        audit_table,
        job_config=bigquery.LoadJobConfig(schema=audit_table.schema, write_disposition="WRITE_APPEND"),
    ).result()

    return {**audit, "bytes_billed": merge.total_bytes_billed}
