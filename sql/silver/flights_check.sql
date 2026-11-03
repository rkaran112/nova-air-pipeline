-- Silver, flights, step 1 of 2: check one bronze batch.
-- Output: temp table checked_rows, one row per bronze row. reject_reason is NULL
-- when the row passed every rule. Rules are checked in order and the first one a
-- row fails becomes its reason.

CREATE OR REPLACE TEMP TABLE checked_rows AS
WITH batch_rows AS (
    SELECT * EXCLUDE (_source_file, _ingested_at, _batch_id)
    FROM bronze.flights
    WHERE _batch_id = $batch_id
),

with_record AS (
    -- The whole source row as JSON: it identifies exact duplicates, and it is what
    -- the quarantine keeps if the row is rejected.
    SELECT *, row_json(struct_pack(*COLUMNS(* EXCLUDE (_row_number)))) AS record_json
    FROM batch_rows
),

numbered_copies AS (
    SELECT *,
           row_number() OVER (PARTITION BY record_json ORDER BY _row_number) AS copy_number
    FROM with_record
),

parsed AS (
    SELECT 'batch'                          AS row_origin,
           _row_number,
           copy_number,
           record_json,
           standard_flight_no(flight_no)    AS flight_no,
           standard_flight_no(flight_no) <> flight_no AS flight_no_was_standardised,
           try_cast(flight_date AS DATE)    AS flight_date,
           upper(trim(origin))              AS origin,
           upper(trim(destination))         AS destination,
           sched_dep                        AS sched_dep_text,
           sched_arr                        AS sched_arr_text,
           actual_dep                       AS actual_dep_text,
           actual_arr                       AS actual_arr_text,
           parse_utc(sched_dep)             AS sched_dep_utc,
           parse_utc(actual_dep)            AS actual_dep_utc,
           upper(trim(aircraft_reg))        AS aircraft_reg,
           upper(trim(status))              AS status,
           nullif(trim(delay_code), '')     AS delay_code,
           updated_at                       AS updated_at_text,
           parse_utc(updated_at)            AS updated_at_utc
    FROM numbered_copies
),

with_arrivals AS (
    -- Arrivals may be time-only; arrival_utc() rolls them past midnight when needed.
    SELECT *,
           arrival_utc(sched_arr_text, sched_dep_utc) AS sched_arr_utc,
           arrival_utc(actual_arr_text, coalesce(actual_dep_utc, sched_dep_utc))
               AS actual_arr_utc,
           is_time_only(sched_arr_text) AND sched_arr_text IS NOT NULL AS arrival_was_time_only
    FROM parsed
)

SELECT *,
       CASE
           WHEN flight_no IS NULL OR flight_date IS NULL OR origin IS NULL
                OR destination IS NULL OR sched_dep_text IS NULL OR sched_arr_text IS NULL
                OR status IS NULL OR updated_at_text IS NULL
               THEN 'MISSING_REQUIRED_FIELD'
           WHEN NOT regexp_full_match(flight_no, $flight_no_pattern)
               THEN 'INVALID_FLIGHT_NO'
           WHEN sched_dep_utc IS NULL OR sched_arr_utc IS NULL OR updated_at_utc IS NULL
                OR (actual_dep_text IS NOT NULL AND actual_dep_utc IS NULL)
                OR (actual_arr_text IS NOT NULL AND actual_arr_utc IS NULL)
               THEN 'BAD_TIMESTAMP'
           WHEN NOT list_contains($valid_flight_statuses, status)
               THEN 'INVALID_STATUS'
           WHEN origin = destination
                OR origin NOT IN (SELECT airport_code FROM silver.airports)
                OR destination NOT IN (SELECT airport_code FROM silver.airports)
               THEN 'UNKNOWN_ROUTE'
           WHEN minutes_between(sched_dep_utc, sched_arr_utc)
                NOT BETWEEN $min_block_minutes AND $max_block_minutes
               THEN 'IMPOSSIBLE_DURATION'
           WHEN status = 'OPERATED' AND actual_dep_utc IS NOT NULL AND actual_arr_utc IS NOT NULL
                AND (actual_arr_utc <= actual_dep_utc
                     OR minutes_between(actual_dep_utc, actual_arr_utc)
                        > $max_actual_block_ratio * minutes_between(sched_dep_utc, sched_arr_utc))
               THEN 'IMPOSSIBLE_DURATION'
       END AS reject_reason
FROM with_arrivals
