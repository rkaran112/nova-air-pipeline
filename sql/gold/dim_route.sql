-- gold.dim_route
-- Grain: one row per direction flown (BLR-BOM and BOM-BLR are two routes),
-- plus one "unknown" row (route_key '-1').
-- Key: route_key = md5('ORIGIN-DESTINATION').

CREATE OR REPLACE TABLE gold.dim_route AS
WITH routes_flown AS (
    SELECT DISTINCT origin, destination FROM silver.flights
),

route_distance AS (
    -- Great-circle distance: the shortest path over the Earth's surface (radius 6371 km).
    SELECT r.origin,
           r.destination,
           round(2 * 6371 * asin(sqrt(
               pow(sin(radians(d.latitude - o.latitude) / 2), 2)
               + cos(radians(o.latitude)) * cos(radians(d.latitude))
                 * pow(sin(radians(d.longitude - o.longitude) / 2), 2)))) AS distance_km
    FROM routes_flown AS r
    JOIN silver.airports AS o ON o.airport_code = r.origin
    JOIN silver.airports AS d ON d.airport_code = r.destination
)

SELECT md5(origin || '-' || destination) AS route_key,
       origin || '-' || destination      AS route_code,
       origin,
       destination,
       md5(origin)                        AS origin_airport_key,
       md5(destination)                   AS destination_airport_key,
       distance_km
FROM route_distance
UNION ALL
SELECT '-1', 'UNKNOWN', 'UNK', 'UNK', '-1', '-1', NULL
