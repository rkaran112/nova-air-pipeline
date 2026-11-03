-- Silver, bookings, step 2 of 2: settle the retried bookings, keep the latest
-- version of each booking, and upsert into silver.bookings.

-- Waiting bookings whose flight has now arrived are released...
UPDATE silver.quarantine AS q
SET status = 'released', resolved_batch_id = $batch_id
FROM checked_rows AS c
WHERE c.quarantine_id = q.quarantine_id AND c.reject_reason IS NULL;

-- ...and those still without a flight after the grace period are rejected for good.
UPDATE silver.quarantine AS q
SET status = 'rejected', reason_code = c.reject_reason, resolved_batch_id = $batch_id
FROM checked_rows AS c
WHERE c.quarantine_id = q.quarantine_id AND c.reject_reason = 'NO_VALID_FLIGHT';

CREATE OR REPLACE TEMP TABLE incoming_rows AS
WITH valid_rows AS (
    SELECT * FROM checked_rows WHERE copy_number = 1 AND reject_reason IS NULL
),

latest_booking_version AS (
    SELECT *,
           row_number() OVER (PARTITION BY booking_id
                              ORDER BY updated_at_utc DESC, row_origin, _row_number DESC)
               AS version_rank
    FROM valid_rows
)

SELECT incoming.row_origin,
       incoming.version_rank,
       coalesce(incoming.updated_at_utc < existing.updated_at_utc, false) AS older_than_silver,
       incoming.booking_id,
       incoming.pnr_token,
       incoming.passenger_token,
       incoming.flight_no,
       incoming.flight_date,
       incoming.cabin,
       incoming.fare_amount,
       incoming.currency,
       incoming.fx_rate,
       incoming.fare_inr,
       incoming.ancillary_inr,
       incoming.channel,
       incoming.status,
       incoming.promo_code,
       incoming.booked_at_utc,
       incoming.updated_at_utc,
       $batch_id AS batch_id
FROM latest_booking_version AS incoming
LEFT JOIN silver.bookings AS existing ON existing.booking_id = incoming.booking_id;

MERGE INTO silver.bookings AS target
USING (
    SELECT booking_id, pnr_token, passenger_token, flight_no, flight_date, cabin, fare_amount,
           currency, fx_rate, fare_inr, ancillary_inr, channel, status, promo_code,
           booked_at_utc, updated_at_utc, batch_id
    FROM incoming_rows
    WHERE version_rank = 1 AND NOT older_than_silver
) AS incoming
ON target.booking_id = incoming.booking_id
WHEN MATCHED AND incoming.updated_at_utc >= target.updated_at_utc THEN UPDATE
WHEN NOT MATCHED THEN INSERT
