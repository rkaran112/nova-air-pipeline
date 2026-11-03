-- gold.dim_airport
-- Grain: one row per airport, plus one "unknown" row (airport_key '-1').
-- Key: airport_key = md5(airport_code), so it never changes between rebuilds.

CREATE OR REPLACE TABLE gold.dim_airport AS
SELECT md5(airport_code) AS airport_key,
       airport_code,
       airport_name,
       city,
       state,
       latitude,
       longitude
FROM silver.airports
UNION ALL
SELECT '-1', 'UNK', 'Unknown airport', 'Unknown', 'Unknown', NULL, NULL
