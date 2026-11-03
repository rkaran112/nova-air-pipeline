-- Silver, flights, step 2 of 2: keep the latest version of each flight, apply the
-- status rule, then update or insert ("upsert") into silver.flights.

CREATE OR REPLACE TEMP TABLE incoming_rows AS
WITH valid_rows AS (
    SELECT * FROM checked_rows WHERE copy_number = 1 AND reject_reason IS NULL
),

latest_flight_version AS (
    SELECT *,
           row_number() OVER (PARTITION BY flight_no, flight_date
                              ORDER BY updated_at_utc DESC, _row_number DESC) AS version_rank
    FROM valid_rows
)

SELECT incoming.row_origin,
       incoming.version_rank,
       -- A version older than the one already in silver must never overwrite it.
       coalesce(incoming.updated_at_utc < existing.updated_at_utc, false) AS older_than_silver,
       incoming.flight_no,
       incoming.flight_date,
       incoming.origin,
       incoming.destination,
       incoming.sched_dep_utc,
       incoming.sched_arr_utc,
       -- Status rule: a cancelled flight has no actual times, whatever the feed says.
       CASE WHEN incoming.status = 'CANCELLED' THEN NULL ELSE incoming.actual_dep_utc END
           AS actual_dep_utc,
       CASE WHEN incoming.status = 'CANCELLED' THEN NULL ELSE incoming.actual_arr_utc END
           AS actual_arr_utc,
       incoming.aircraft_reg,
       incoming.status,
       incoming.delay_code,
       incoming.status = 'CANCELLED'
           AND (incoming.actual_dep_utc IS NOT NULL OR incoming.actual_arr_utc IS NOT NULL)
           AS actuals_cleared,
       incoming.status = 'OPERATED'
           AND (incoming.actual_dep_utc IS NULL OR incoming.actual_arr_utc IS NULL)
           AS actuals_missing,
       incoming.updated_at_utc,
       $batch_id AS batch_id
FROM latest_flight_version AS incoming
LEFT JOIN silver.flights AS existing
       ON existing.flight_no = incoming.flight_no
      AND existing.flight_date = incoming.flight_date;

MERGE INTO silver.flights AS target
USING (
    SELECT flight_no, flight_date, origin, destination, sched_dep_utc, sched_arr_utc,
           actual_dep_utc, actual_arr_utc, aircraft_reg, status, delay_code, actuals_cleared,
           actuals_missing, updated_at_utc, batch_id
    FROM incoming_rows
    WHERE version_rank = 1 AND NOT older_than_silver
) AS incoming
ON target.flight_no = incoming.flight_no AND target.flight_date = incoming.flight_date
WHEN MATCHED AND incoming.updated_at_utc >= target.updated_at_utc THEN UPDATE
WHEN NOT MATCHED THEN INSERT
