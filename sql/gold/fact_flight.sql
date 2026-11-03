-- gold.fact_flight
-- Grain: one row per scheduled flight leg (flight_no + flight_date), operated or not.
-- Key: flight_key = md5(flight_no || '|' || flight_date).
-- Joins: date_key, route_key, origin/destination_airport_key, aircraft_key and
-- delay_reason_key point at the dimensions. A missing match uses the '-1' row,
-- so no flight ever disappears from a join.

CREATE OR REPLACE TABLE gold.fact_flight AS
WITH flights_with_leg_number AS (
    -- Which leg of its day each aircraft is flying (1 = its first flight that day).
    SELECT *,
           row_number() OVER (PARTITION BY aircraft_reg, flight_date
                              ORDER BY sched_dep_utc) AS aircraft_leg_number
    FROM silver.flights
),

flights_with_keys AS (
    SELECT f.*,
           coalesce(route.route_key, '-1')          AS route_key,
           coalesce(route.origin_airport_key, '-1') AS origin_airport_key,
           coalesce(route.destination_airport_key, '-1') AS destination_airport_key,
           coalesce(aircraft.aircraft_key, '-1')    AS aircraft_key,
           CASE WHEN f.delay_code IS NULL THEN md5('NONE')
                ELSE coalesce(reason.delay_reason_key, '-1') END AS delay_reason_key,
           coalesce(aircraft.seats_total, 0)        AS aircraft_seats,
           route.distance_km
    FROM flights_with_leg_number AS f
    LEFT JOIN gold.dim_route AS route
           ON route.route_key = md5(f.origin || '-' || f.destination)
    LEFT JOIN gold.dim_aircraft AS aircraft ON aircraft.aircraft_key = md5(f.aircraft_reg)
    LEFT JOIN gold.dim_delay_reason AS reason ON reason.delay_reason_key = md5(f.delay_code)
)

SELECT md5(flight_no || '|' || flight_date)               AS flight_key,
       CAST(strftime(flight_date, '%Y%m%d') AS INTEGER)    AS date_key,
       route_key,
       origin_airport_key,
       destination_airport_key,
       aircraft_key,
       delay_reason_key,
       flight_no,
       flight_date,
       status,
       status = 'OPERATED'                                 AS is_operated,
       status = 'CANCELLED'                                AS is_cancelled,
       sched_dep_utc,
       to_ist(sched_dep_utc)                               AS sched_dep_ist,
       hour(to_ist(sched_dep_utc))                         AS sched_dep_hour_ist,
       sched_arr_utc,
       actual_dep_utc,
       actual_arr_utc,
       minutes_between(sched_dep_utc, sched_arr_utc)       AS scheduled_block_minutes,
       minutes_between(sched_dep_utc, actual_dep_utc)      AS departure_delay_minutes,
       minutes_between(sched_arr_utc, actual_arr_utc)      AS arrival_delay_minutes,
       -- On time = arrived no more than 15 minutes after schedule. NULL when it
       -- cannot be measured (cancelled, or the feed sent no arrival time).
       CASE WHEN status = 'OPERATED' AND actual_arr_utc IS NOT NULL
            THEN minutes_between(sched_arr_utc, actual_arr_utc) <= $on_time_threshold_minutes
       END                                                 AS is_on_time,
       actuals_missing,
       actuals_cleared,
       aircraft_leg_number,
       CASE WHEN status = 'OPERATED' THEN aircraft_seats ELSE 0 END  AS seats_offered,
       distance_km,
       -- ASK (available seat kilometres): seats flown times distance flown.
       CASE WHEN status = 'OPERATED' THEN aircraft_seats * distance_km ELSE 0 END AS ask
FROM flights_with_keys
