-- Silver, bookings, step 1 of 2: check one bronze batch, together with any bookings
-- still waiting in quarantine for their flight to arrive.
-- Output: temp table checked_rows (see flights_check.sql for the shape), with
-- row_origin = 'batch' for this file's rows and 'retry' for the waiting ones.

CREATE OR REPLACE TEMP TABLE checked_rows AS
WITH batch_rows AS (
    -- Mask the identifiers first, so the quarantine never holds a raw value.
    SELECT * EXCLUDE (_source_file, _ingested_at, _batch_id)
             REPLACE (pii_token(passenger_id) AS passenger_id, pii_token(pnr) AS pnr)
    FROM bronze.bookings
    WHERE _batch_id = $batch_id
),

with_record AS (
    SELECT *, row_json(struct_pack(*COLUMNS(* EXCLUDE (_row_number)))) AS record_json
    FROM batch_rows
),

numbered_copies AS (
    SELECT *,
           row_number() OVER (PARTITION BY record_json ORDER BY _row_number) AS copy_number
    FROM with_record
),

all_candidates AS (
    SELECT 'batch' AS row_origin, NULL::VARCHAR AS quarantine_id, _row_number, copy_number,
           record_json
    FROM numbered_copies
    UNION ALL
    SELECT 'retry', quarantine_id, row_number, 1, record
    FROM silver.quarantine
    WHERE source = 'bookings' AND status = 'waiting'
),

parsed AS (
    -- Fields are read from the JSON record, so new rows and retried rows go through
    -- exactly the same code, and a column that only some files have (promo_code)
    -- simply reads as NULL where it is absent.
    SELECT row_origin,
           quarantine_id,
           _row_number,
           copy_number,
           record_json,
           record_json ->> 'booking_id'                              AS booking_id,
           record_json ->> 'pnr'                                     AS pnr_token,
           record_json ->> 'passenger_id'                            AS passenger_token,
           standard_flight_no(record_json ->> 'flight_no')           AS flight_no,
           standard_flight_no(record_json ->> 'flight_no')
               <> (record_json ->> 'flight_no')                      AS flight_no_was_standardised,
           record_json ->> 'flight_date'                             AS flight_date_text,
           try_cast(record_json ->> 'flight_date' AS DATE)           AS flight_date,
           upper(trim(record_json ->> 'cabin'))                      AS cabin,
           record_json ->> 'fare_amount'                             AS fare_text,
           try_cast(record_json ->> 'fare_amount' AS DECIMAL(12, 2)) AS fare_amount,
           upper(trim(record_json ->> 'currency'))                   AS currency,
           record_json ->> 'ancillary_amount'                        AS ancillary_text,
           -- Optional field rule: no ancillary amount means nothing extra was bought.
           coalesce(try_cast(record_json ->> 'ancillary_amount' AS DECIMAL(12, 2)), 0)
                                                                     AS ancillary_amount,
           -- Optional field rule: an unknown sales channel is labelled, not rejected.
           coalesce(upper(trim(record_json ->> 'channel')), 'UNKNOWN') AS channel,
           upper(trim(record_json ->> 'status'))                     AS status,
           nullif(trim(record_json ->> 'promo_code'), '')            AS promo_code,
           record_json ->> 'booked_at'                               AS booked_at_text,
           parse_utc(record_json ->> 'booked_at')                    AS booked_at_utc,
           record_json ->> 'updated_at'                              AS updated_at_text,
           parse_utc(record_json ->> 'updated_at')                   AS updated_at_utc
    FROM all_candidates
),

with_fx_and_flight AS (
    SELECT parsed.*,
           -- USD fares are converted at the rate for the day the booking was made.
           CASE WHEN parsed.currency = 'INR' THEN 1.0 ELSE fx.rate END AS fx_rate,
           flight.flight_no IS NOT NULL                              AS flight_found
    FROM parsed
    LEFT JOIN silver.fx_rates AS fx
           ON fx.from_currency = parsed.currency
          AND fx.rate_date = CAST(to_ist(parsed.booked_at_utc) AS DATE)
    LEFT JOIN silver.flights AS flight
           ON flight.flight_no = parsed.flight_no
          AND flight.flight_date = parsed.flight_date
)

SELECT *,
       round(fare_amount * fx_rate, 2)      AS fare_inr,
       round(ancillary_amount * fx_rate, 2) AS ancillary_inr,
       CASE
           WHEN booking_id IS NULL OR passenger_token IS NULL OR flight_no IS NULL
                OR flight_date_text IS NULL OR cabin IS NULL OR fare_text IS NULL
                OR currency IS NULL OR status IS NULL OR updated_at_text IS NULL
               THEN 'MISSING_REQUIRED_FIELD'
           WHEN NOT regexp_full_match(flight_no, $flight_no_pattern)
               THEN 'INVALID_FLIGHT_NO'
           WHEN updated_at_utc IS NULL OR (booked_at_text IS NOT NULL AND booked_at_utc IS NULL)
               THEN 'BAD_TIMESTAMP'
           WHEN flight_date IS NULL OR fare_amount IS NULL
                OR (ancillary_text IS NOT NULL
                    AND try_cast(ancillary_text AS DECIMAL(12, 2)) IS NULL)
               THEN 'BAD_NUMBER'
           WHEN NOT list_contains($valid_cabins, cabin)
                OR NOT list_contains($valid_booking_statuses, status)
               THEN 'INVALID_VALUE'
           WHEN NOT list_contains($valid_currencies, currency) OR fx_rate IS NULL
               THEN 'UNKNOWN_CURRENCY'
           WHEN fare_amount <= 0
               THEN 'NON_POSITIVE_FARE'
           -- Late-arriving data: the booking is fine but its flight is not in silver
           -- yet. It waits and is retried on every run, until the grace period ends.
           WHEN NOT flight_found AND flight_date + $late_flight_grace_days < $file_date
               THEN 'NO_VALID_FLIGHT'
           WHEN NOT flight_found
               THEN 'WAITING_FOR_FLIGHT'
       END AS reject_reason
FROM with_fx_and_flight
