-- gold.fact_booking
-- Grain: one row per booking, which is one passenger on one flight.
-- Key: booking_key = md5(booking_id).
-- Joins: flight_key -> fact_flight; date_key, route_key, passenger_key -> dimensions.

CREATE OR REPLACE TABLE gold.fact_booking AS
WITH bookings_with_flight AS (
    SELECT b.*,
           f.flight_key,
           f.date_key,
           f.route_key,
           f.is_operated,
           f.distance_km,
           coalesce(p.passenger_key, '-1') AS passenger_key
    FROM silver.bookings AS b
    JOIN gold.fact_flight AS f ON f.flight_key = md5(b.flight_no || '|' || b.flight_date)
    LEFT JOIN gold.dim_passenger AS p ON p.passenger_key = md5(b.passenger_token)
),

route_cabin_fare_range AS (
    -- What a normal fare looks like on each route and cabin: the middle half of
    -- fares lies between q1 and q3. A route-level range, not one global range,
    -- because a normal Delhi-Chennai fare would look extreme on Bengaluru-Kochi.
    SELECT route_key,
           cabin,
           quantile_cont(fare_inr, 0.25) AS q1,
           quantile_cont(fare_inr, 0.75) AS q3
    FROM bookings_with_flight
    GROUP BY route_key, cabin
),

classified AS (
    SELECT b.*,
           -- Passengers carried: confirmed bookings on flights that operated.
           b.status = 'CONFIRMED' AND b.is_operated                AS is_flown,
           -- Revenue kept: confirmed and no-show bookings on operated flights.
           -- Cancelled bookings, and every booking on a cancelled flight, are refunded.
           b.status IN ('CONFIRMED', 'NO_SHOW') AND b.is_operated  AS is_revenue,
           b.fare_inr < r.q1 - $fare_outlier_iqr_multiplier * (r.q3 - r.q1)
               OR b.fare_inr > r.q3 + $fare_outlier_iqr_multiplier * (r.q3 - r.q1)
                                                                   AS is_fare_outlier
    FROM bookings_with_flight AS b
    JOIN route_cabin_fare_range AS r USING (route_key, cabin)
)

SELECT md5(booking_id)                                         AS booking_key,
       flight_key,
       date_key,
       route_key,
       passenger_key,
       booking_id,
       cabin,
       channel,
       status,
       promo_code,
       currency                                                AS original_currency,
       fare_inr,
       ancillary_inr,
       is_flown,
       is_revenue,
       CASE WHEN is_revenue THEN fare_inr ELSE 0 END           AS fare_revenue_inr,
       CASE WHEN is_revenue THEN ancillary_inr ELSE 0 END      AS ancillary_revenue_inr,
       -- RPK (revenue passenger kilometres): each carried passenger times distance.
       CASE WHEN is_flown THEN distance_km ELSE 0 END          AS rpk,
       is_fare_outlier,
       to_ist(booked_at_utc)                                   AS booked_at_ist,
       date_diff('day', CAST(to_ist(booked_at_utc) AS DATE), flight_date) AS lead_time_days
FROM classified
