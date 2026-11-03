-- gold.mart_booking_daily
-- Grain: one row per date, route and cabin.
-- Holds only totals; rates are sum / sum after filtering:
--   load factor     = passengers_flown / seats_offered
--   yield           = fare_revenue_inr / rpk          (passenger revenue per RPK)
--   RASK            = total_revenue_inr / ask         (all revenue per seat km)
--   ancillary share = ancillary_revenue_inr / total_revenue_inr
-- Seats are counted per cabin, so filtering on one cabin gives that cabin's
-- load factor. Flight counts live in mart_flight_daily instead, because putting
-- them here would count every flight once per cabin.

CREATE OR REPLACE TABLE gold.mart_booking_daily AS
WITH cabin_seats AS (
    -- Every operated flight offers seats in both cabins, even if nobody booked one.
    SELECT f.date_key,
           f.route_key,
           cabins.cabin,
           CASE cabins.cabin WHEN 'PLUS' THEN a.seats_plus ELSE a.seats_economy END AS seats,
           f.distance_km
    FROM gold.fact_flight AS f
    JOIN gold.dim_aircraft AS a ON a.aircraft_key = f.aircraft_key
    CROSS JOIN (VALUES ('ECONOMY'), ('PLUS')) AS cabins(cabin)
    WHERE f.is_operated
),

seats_by_day AS (
    SELECT date_key, route_key, cabin,
           sum(seats)               AS seats_offered,
           sum(seats * distance_km) AS ask
    FROM cabin_seats
    GROUP BY ALL
),

bookings_by_day AS (
    SELECT date_key, route_key, cabin,
           count(*)                                          AS bookings,
           count(*) FILTER (WHERE is_flown)                  AS passengers_flown,
           sum(fare_revenue_inr)                             AS fare_revenue_inr,
           sum(ancillary_revenue_inr)                        AS ancillary_revenue_inr,
           sum(rpk)                                          AS rpk,
           count(*) FILTER (WHERE is_fare_outlier)           AS fare_outlier_bookings
    FROM gold.fact_booking
    GROUP BY ALL
)

SELECT date_key,
       route_key,
       cabin,
       coalesce(s.seats_offered, 0)          AS seats_offered,
       coalesce(s.ask, 0)                    AS ask,
       coalesce(b.bookings, 0)               AS bookings,
       coalesce(b.passengers_flown, 0)       AS passengers_flown,
       coalesce(b.fare_revenue_inr, 0)       AS fare_revenue_inr,
       coalesce(b.ancillary_revenue_inr, 0)  AS ancillary_revenue_inr,
       coalesce(b.fare_revenue_inr, 0) + coalesce(b.ancillary_revenue_inr, 0)
                                             AS total_revenue_inr,
       coalesce(b.rpk, 0)                    AS rpk,
       coalesce(b.fare_outlier_bookings, 0)  AS fare_outlier_bookings
FROM seats_by_day AS s
FULL OUTER JOIN bookings_by_day AS b USING (date_key, route_key, cabin)
