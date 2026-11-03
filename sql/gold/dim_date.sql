-- gold.dim_date
-- Grain: one row per calendar day from the first to the last flight date,
-- plus one "unknown" row (date_key -1).
-- Key: date_key = YYYYMMDD as an integer, a readable convention for date keys.

CREATE OR REPLACE TABLE gold.dim_date AS
WITH calendar_days AS (
    SELECT CAST(day AS DATE) AS calendar_date
    FROM range((SELECT min(flight_date) FROM silver.flights),
               (SELECT max(flight_date) FROM silver.flights) + INTERVAL 1 DAY,
               INTERVAL 1 DAY) AS days(day)
)
SELECT CAST(strftime(calendar_date, '%Y%m%d') AS INTEGER) AS date_key,
       calendar_date,
       year(calendar_date)                                 AS year,
       month(calendar_date)                                AS month,
       strftime(calendar_date, '%b %Y')                    AS month_label,
       quarter(calendar_date)                              AS quarter,
       weekofyear(calendar_date)                           AS week_of_year,
       isodow(calendar_date)                               AS day_of_week,  -- 1 = Monday
       dayname(calendar_date)                              AS day_name,
       isodow(calendar_date) IN (6, 7)                     AS is_weekend
FROM calendar_days
UNION ALL
SELECT -1, NULL, NULL, NULL, 'Unknown', NULL, NULL, NULL, 'Unknown', NULL
