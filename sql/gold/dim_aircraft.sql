-- gold.dim_aircraft
-- Grain: one row per aircraft registration, plus one "unknown" row (aircraft_key '-1').
-- Key: aircraft_key = md5(aircraft_reg).

CREATE OR REPLACE TABLE gold.dim_aircraft AS
SELECT md5(aircraft_reg) AS aircraft_key,
       aircraft_reg,
       aircraft_type,
       seats_plus,
       seats_economy,
       seats_total
FROM silver.aircraft
UNION ALL
SELECT '-1', 'UNKNOWN', 'Unknown', 0, 0, 0
