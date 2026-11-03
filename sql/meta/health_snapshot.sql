-- Small summary tables for the dashboard's Data Health page. The dashboard only
-- reads exports, and these hold counts, never records, so no PII can leak through.

CREATE OR REPLACE TABLE meta.layer_counts AS
SELECT 'bronze' AS layer, 'flights' AS table_name, count(*) AS row_count FROM bronze.flights
UNION ALL SELECT 'bronze', 'bookings', count(*) FROM bronze.bookings
UNION ALL SELECT 'bronze', 'passengers', count(*) FROM bronze.passengers
UNION ALL SELECT 'silver', 'flights', count(*) FROM silver.flights
UNION ALL SELECT 'silver', 'bookings', count(*) FROM silver.bookings
UNION ALL SELECT 'silver', 'passengers', count(*) FROM silver.passengers
UNION ALL SELECT 'silver', 'quarantine', count(*) FROM silver.quarantine
UNION ALL SELECT 'gold', 'fact_flight', count(*) FROM gold.fact_flight
UNION ALL SELECT 'gold', 'fact_booking', count(*) FROM gold.fact_booking
UNION ALL SELECT 'gold', 'dim_passenger', count(*) FROM gold.dim_passenger;

CREATE OR REPLACE TABLE meta.quarantine_summary AS
SELECT source,
       reason_code,
       status,
       count(*)       AS row_count,
       min(file_date) AS first_file_date,
       max(file_date) AS last_file_date
FROM silver.quarantine
GROUP BY ALL
