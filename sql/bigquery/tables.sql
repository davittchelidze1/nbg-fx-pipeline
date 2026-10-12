-- Run on every load. DDL is free in BigQuery and IF NOT EXISTS makes it a no-op.

CREATE TABLE IF NOT EXISTS `{project}.{dataset}.daily_rates` (
  rate_date      DATE      NOT NULL OPTIONS (description = 'Date the rates are valid for (NBG validFromDate)'),
  currency_code  STRING    NOT NULL,
  currency_name  STRING,
  quantity       INT64     NOT NULL OPTIONS (description = 'Units the rate is quoted per, e.g. 1000 for AMD'),
  rate           NUMERIC   NOT NULL OPTIONS (description = 'GEL per `quantity` units, as published'),
  rate_per_unit  NUMERIC   NOT NULL OPTIONS (description = 'GEL per one unit; comparable across currencies'),
  nbg_diff       NUMERIC            OPTIONS (description = 'NBG change vs its previous rate set'),
  published_at   TIMESTAMP,
  loaded_at      TIMESTAMP NOT NULL
)
-- ~42 rows a day. Daily partitions would hold 42 rows each, far too small to
-- be worth pruning, so partition by month and cluster by currency instead.
PARTITION BY DATE_TRUNC(rate_date, MONTH)
CLUSTER BY currency_code
OPTIONS (description = 'Official National Bank of Georgia exchange rates, one row per currency per rate date');

CREATE TABLE IF NOT EXISTS `{project}.{dataset}.load_audit` (
  loaded_at      TIMESTAMP NOT NULL,
  job_id         STRING,
  rate_date_min  DATE,
  rate_date_max  DATE,
  rows_in_batch  INT64,
  rows_inserted  INT64,
  rows_updated   INT64,
  git_sha        STRING
)
OPTIONS (description = 'One row per pipeline load: what came in and what the MERGE changed');

CREATE OR REPLACE VIEW `{project}.{dataset}.v_rate_changes`
OPTIONS (description = 'Day-over-day and 30-day moves per currency, with a z-score against the previous 60 moves')
AS
WITH base AS (
  SELECT
    rate_date,
    currency_code,
    rate_per_unit,
    LAG(rate_per_unit) OVER (PARTITION BY currency_code ORDER BY rate_date) AS prev_rate,
    FIRST_VALUE(rate_per_unit) OVER (
      PARTITION BY currency_code ORDER BY UNIX_DATE(rate_date)
      RANGE BETWEEN 30 PRECEDING AND CURRENT ROW
    ) AS rate_30d_ago
  FROM `{project}.{dataset}.daily_rates`
),
moves AS (
  SELECT
    *,
    CAST(SAFE_DIVIDE(rate_per_unit - prev_rate, prev_rate) * 100 AS FLOAT64) AS pct_1d,
    CAST(SAFE_DIVIDE(rate_per_unit - rate_30d_ago, rate_30d_ago) * 100 AS FLOAT64) AS pct_30d
  FROM base
)
SELECT
  *,
  SAFE_DIVIDE(
    pct_1d - AVG(pct_1d) OVER prior_60,
    STDDEV(pct_1d) OVER prior_60
  ) AS z_score_1d
FROM moves
WINDOW prior_60 AS (PARTITION BY currency_code ORDER BY rate_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING);
