-- Silver, passengers, step 2 of 2: keep the latest version of each profile and
-- upsert it. A changed loyalty tier simply overwrites the old one (SCD Type 1).

CREATE OR REPLACE TEMP TABLE incoming_rows AS
WITH valid_rows AS (
    SELECT * FROM checked_rows WHERE copy_number = 1 AND reject_reason IS NULL
),

latest_passenger_version AS (
    SELECT *,
           row_number() OVER (PARTITION BY passenger_token
                              ORDER BY updated_at_utc DESC, _row_number DESC) AS version_rank
    FROM valid_rows
)

SELECT incoming.row_origin,
       incoming.version_rank,
       coalesce(incoming.updated_at_utc < existing.updated_at_utc, false) AS older_than_silver,
       incoming.passenger_token,
       incoming.email_token,
       incoming.phone_token,
       incoming.age_band,
       incoming.loyalty_tier,
       incoming.updated_at_utc,
       $batch_id AS batch_id
FROM latest_passenger_version AS incoming
LEFT JOIN silver.passengers AS existing
       ON existing.passenger_token = incoming.passenger_token;

MERGE INTO silver.passengers AS target
USING (
    SELECT passenger_token, email_token, phone_token, age_band, loyalty_tier, updated_at_utc,
           batch_id
    FROM incoming_rows
    WHERE version_rank = 1 AND NOT older_than_silver
) AS incoming
ON target.passenger_token = incoming.passenger_token
WHEN MATCHED AND incoming.updated_at_utc >= target.updated_at_utc THEN UPDATE
WHEN NOT MATCHED THEN INSERT
