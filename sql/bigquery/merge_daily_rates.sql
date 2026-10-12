-- Upsert the staged batch. Re-loading the same dates changes nothing; a
-- corrected rate from NBG updates the row in place.
-- The date range on the target lets BigQuery prune to the batch's months
-- instead of scanning the whole table.

MERGE `{project}.{dataset}.daily_rates` AS t
USING (
  SELECT *
  FROM `{project}.{dataset}._stg_daily_rates`
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY rate_date, currency_code ORDER BY published_at DESC) = 1
) AS s
ON t.rate_date = s.rate_date
   AND t.currency_code = s.currency_code
   AND t.rate_date BETWEEN @min_date AND @max_date
WHEN MATCHED AND (
     t.rate != s.rate
  OR t.quantity != s.quantity
  OR t.nbg_diff IS DISTINCT FROM s.nbg_diff
  OR t.currency_name IS DISTINCT FROM s.currency_name
) THEN UPDATE SET
  currency_name = s.currency_name,
  quantity      = s.quantity,
  rate          = s.rate,
  rate_per_unit = s.rate_per_unit,
  nbg_diff      = s.nbg_diff,
  published_at  = s.published_at,
  loaded_at     = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT
  (rate_date, currency_code, currency_name, quantity, rate, rate_per_unit, nbg_diff, published_at, loaded_at)
VALUES
  (s.rate_date, s.currency_code, s.currency_name, s.quantity, s.rate, s.rate_per_unit, s.nbg_diff, s.published_at, CURRENT_TIMESTAMP());
