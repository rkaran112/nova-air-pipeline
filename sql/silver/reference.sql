-- Reference data is small and curated, so silver simply rebuilds each table from
-- the most recently loaded version of its file, with proper types.

CREATE OR REPLACE TABLE silver.airports AS
SELECT upper(trim(airport_code)) AS airport_code,
       airport_name,
       city,
       state,
       CAST(latitude AS DOUBLE)  AS latitude,
       CAST(longitude AS DOUBLE) AS longitude
FROM bronze.airports
WHERE _batch_id = (SELECT max_by(batch_id, loaded_at) FROM meta.file_log
                   WHERE source = 'airports');

CREATE OR REPLACE TABLE silver.aircraft AS
SELECT upper(trim(aircraft_reg))      AS aircraft_reg,
       aircraft_type,
       CAST(seats_plus AS INTEGER)    AS seats_plus,
       CAST(seats_economy AS INTEGER) AS seats_economy,
       CAST(seats_total AS INTEGER)   AS seats_total
FROM bronze.aircraft
WHERE _batch_id = (SELECT max_by(batch_id, loaded_at) FROM meta.file_log
                   WHERE source = 'aircraft');

CREATE OR REPLACE TABLE silver.delay_codes AS
SELECT trim(delay_code) AS delay_code,
       description,
       category
FROM bronze.delay_codes
WHERE _batch_id = (SELECT max_by(batch_id, loaded_at) FROM meta.file_log
                   WHERE source = 'delay_codes');

CREATE OR REPLACE TABLE silver.fx_rates AS
SELECT CAST(rate_date AS DATE) AS rate_date,
       upper(from_currency)    AS from_currency,
       upper(to_currency)      AS to_currency,
       CAST(rate AS DOUBLE)    AS rate
FROM bronze.fx_rates
WHERE _batch_id = (SELECT max_by(batch_id, loaded_at) FROM meta.file_log
                   WHERE source = 'fx_rates')
