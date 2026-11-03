-- Silver, passengers, step 1 of 2: mask personal data, then check one bronze batch.
-- Output: temp table checked_rows (see flights_check.sql for the shape).

CREATE OR REPLACE TEMP TABLE checked_rows AS
WITH masked_rows AS (
    -- Personal data is masked first, before anything else reads it, so neither
    -- silver.passengers nor the quarantine ever holds a raw value:
    --   passenger_id, email, phone -> keyed tokens (they still join and match)
    --   full_name                  -> dropped (no analysis needs it)
    --   date_of_birth              -> age band
    SELECT * EXCLUDE (_source_file, _ingested_at, _batch_id, full_name, date_of_birth)
             REPLACE (pii_token(passenger_id) AS passenger_id,
                      pii_token(lower(trim(email))) AS email,
                      pii_token(regexp_replace(phone, '[^0-9]', '', 'g')) AS phone),
           age_band(date_of_birth, $file_date) AS age_band
    FROM bronze.passengers
    WHERE _batch_id = $batch_id
),

with_record AS (
    SELECT *, row_json(struct_pack(*COLUMNS(* EXCLUDE (_row_number)))) AS record_json
    FROM masked_rows
),

numbered_copies AS (
    SELECT *,
           row_number() OVER (PARTITION BY record_json ORDER BY _row_number) AS copy_number
    FROM with_record
)

SELECT 'batch'                                   AS row_origin,
       _row_number,
       copy_number,
       record_json,
       NULL::VARCHAR                             AS flight_no,
       NULL::DATE                                AS flight_date,
       passenger_id                              AS passenger_token,
       email                                     AS email_token,
       phone                                     AS phone_token,
       age_band,
       coalesce(upper(trim(loyalty_tier)), 'NONE') AS loyalty_tier,
       parse_utc(updated_at)                     AS updated_at_utc,
       CASE
           WHEN passenger_id IS NULL OR updated_at IS NULL THEN 'MISSING_REQUIRED_FIELD'
           WHEN parse_utc(updated_at) IS NULL THEN 'BAD_TIMESTAMP'
       END                                       AS reject_reason
FROM numbered_copies
