-- gold.mart_flight_daily
-- Grain: one row per date and route.
-- Holds only totals. Every rate is calculated later, after filtering, as
-- sum(numerator) / sum(denominator), never as an average of daily percentages.
--   on-time performance = flights_on_time / flights_measured
--   cancellation rate   = flights_cancelled / flights_scheduled
--   average arrival delay, all measured flights (early counts as 0)
--                       = arrival_delay_minutes_total / flights_measured
--   average delay of delayed flights only (more than 15 minutes late)
--                       = delayed_minutes_total / flights_delayed

CREATE OR REPLACE TABLE gold.mart_flight_daily AS
SELECT date_key,
       route_key,
       count(*)                                                 AS flights_scheduled,
       count(*) FILTER (WHERE is_operated)                      AS flights_operated,
       count(*) FILTER (WHERE is_cancelled)                     AS flights_cancelled,
       count(*) FILTER (WHERE is_on_time IS NOT NULL)           AS flights_measured,
       count(*) FILTER (WHERE is_on_time)                       AS flights_on_time,
       coalesce(sum(greatest(arrival_delay_minutes, 0))
                FILTER (WHERE is_on_time IS NOT NULL), 0)       AS arrival_delay_minutes_total,
       count(*) FILTER (WHERE NOT is_on_time)                   AS flights_delayed,
       coalesce(sum(arrival_delay_minutes) FILTER (WHERE NOT is_on_time), 0)
                                                                AS delayed_minutes_total,
       sum(seats_offered)                                       AS seats_offered,
       sum(ask)                                                 AS ask
FROM gold.fact_flight
GROUP BY date_key, route_key
