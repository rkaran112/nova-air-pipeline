-- gold.dim_passenger
-- Grain: one row per passenger (their current profile: SCD Type 1), plus one
-- "unknown" row (passenger_key '-1') for bookings whose profile was quarantined.
-- Key: passenger_key = md5(passenger_token). No raw personal data reaches gold:
-- only tokens, an age band, and whether contact details exist.

CREATE OR REPLACE TABLE gold.dim_passenger AS
SELECT md5(passenger_token)  AS passenger_key,
       passenger_token,
       age_band,
       loyalty_tier,
       email_token IS NOT NULL AS has_email,
       phone_token IS NOT NULL AS has_phone
FROM silver.passengers
UNION ALL
SELECT '-1', NULL, 'UNKNOWN', 'UNKNOWN', false, false
