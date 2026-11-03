# SQL patterns used here (and in most analytics work)

Each pattern has a tiny worked example you can paste into DuckDB, then a pointer to
where the project uses it. To try them, start Python in the repo folder and run:

```python
import duckdb
con = duckdb.connect()
print(con.sql("""<paste a query here>"""))
```

## 1. CTEs: name each step

A **CTE** (common table expression, the `WITH name AS (...)` block) is a named
intermediate result. Writing one CTE per step, named after what it does, turns a long
query into a readable recipe.

```sql
WITH raw_fares AS (
    SELECT * FROM (VALUES ('B1', '3000'), ('B2', 'abc'), ('B3', '-5')) t(booking_id, fare)
),
parsed_fares AS (
    SELECT booking_id, try_cast(fare AS DECIMAL(10, 2)) AS fare FROM raw_fares
),
valid_fares AS (
    SELECT * FROM parsed_fares WHERE fare > 0
)
SELECT * FROM valid_fares;
-- B1 | 3000.00
```

**Used in:** every file in `sql/silver` and `sql/gold`.

## 2. Dedupe with ROW_NUMBER

`row_number() OVER (PARTITION BY key ORDER BY something)` numbers the rows inside each
group. Keep number 1 and you keep exactly one row per key: the "best" one by your order.

```sql
WITH bookings AS (
    SELECT * FROM (VALUES
        ('B003', 'CONFIRMED', TIMESTAMP '2025-06-20 04:30'),
        ('B003', 'NO_SHOW',   TIMESTAMP '2025-07-01 02:30'),
        ('B004', 'CONFIRMED', TIMESTAMP '2025-06-20 04:30')
    ) t(booking_id, status, updated_at)
),
latest_booking_version AS (
    SELECT *, row_number() OVER (PARTITION BY booking_id ORDER BY updated_at DESC) AS version_rank
    FROM bookings
)
SELECT booking_id, status FROM latest_booking_version WHERE version_rank = 1;
-- B003 | NO_SHOW
-- B004 | CONFIRMED
```

For *exact* duplicates, partition by the whole row (here, its JSON fingerprint):
`row_number() OVER (PARTITION BY record_json ORDER BY _row_number)`.

**Used in:** `numbered_copies` and `latest_*_version` in every `sql/silver/*_check.sql` and
`*_merge.sql`.

## 3. Upsert with MERGE

`MERGE` matches incoming rows to existing rows on a key, then updates the matches and
inserts the rest, in one statement.

```sql
CREATE TABLE bookings (booking_id VARCHAR PRIMARY KEY, status VARCHAR, updated_at TIMESTAMP);
INSERT INTO bookings VALUES ('B003', 'NO_SHOW', TIMESTAMP '2025-07-01 02:30');

MERGE INTO bookings AS target
USING (SELECT * FROM (VALUES
          ('B003', 'CONFIRMED', TIMESTAMP '2025-06-25 04:30'),   -- stale resend
          ('B020', 'CONFIRMED', TIMESTAMP '2025-06-21 04:30'))   -- new booking
       t(booking_id, status, updated_at)) AS incoming
ON target.booking_id = incoming.booking_id
WHEN MATCHED AND incoming.updated_at >= target.updated_at THEN UPDATE
WHEN NOT MATCHED THEN INSERT;

SELECT * FROM bookings ORDER BY 1;
-- B003 | NO_SHOW   (the older version did not overwrite it)
-- B020 | CONFIRMED
```

Without `MERGE`, the classic two-step form is `UPDATE ... FROM incoming` then
`INSERT ... WHERE NOT EXISTS (...)`. Postgres has `INSERT ... ON CONFLICT DO UPDATE`.

**Used in:** `sql/silver/flights_merge.sql`, `passengers_merge.sql`, `bookings_merge.sql`.

## 4. Window functions beyond dedupe

A **window function** computes something for each row from a group of related rows,
without collapsing them like `GROUP BY` does.

```sql
WITH legs AS (
    SELECT * FROM (VALUES
        ('VT-NAA', DATE '2025-07-01', TIMESTAMP '2025-07-01 00:30'),
        ('VT-NAA', DATE '2025-07-01', TIMESTAMP '2025-07-01 03:15'),
        ('VT-NAB', DATE '2025-07-01', TIMESTAMP '2025-07-01 00:40')
    ) t(aircraft_reg, flight_date, sched_dep)
)
SELECT *,
       row_number() OVER (PARTITION BY aircraft_reg, flight_date ORDER BY sched_dep) AS leg,
       lag(sched_dep) OVER (PARTITION BY aircraft_reg, flight_date ORDER BY sched_dep) AS previous_departure
FROM legs;
```

Other useful ones: `lag/lead` (previous/next row), `sum(...) OVER (ORDER BY day)` for a
running total, `rank()` for top-N per group, `avg(...) OVER (... ROWS BETWEEN 6 PRECEDING
AND CURRENT ROW)` for a 7-day moving average.

**Used in:** `aircraft_leg_number` in `sql/gold/fact_flight.sql`.

## 5. Ratios: sum over sum, after filtering

```sql
WITH flights AS (
    SELECT * FROM (VALUES (180, 180), (2, 20)) t(passengers, seats)
)
SELECT avg(passengers / seats)        AS wrong_average_of_percentages,  -- 0.55
       sum(passengers) / sum(seats)   AS right_load_factor              -- 0.91
FROM flights;
```

The average of percentages treats the 20-seat flight as equal to the 180-seat one. The
real load factor is 182 people in 200 seats. Store totals in marts; divide last.

**Used in:** `sql/gold/mart_*.sql` store totals; `dashboard/queries.py` divides.

## 6. Conditional aggregation with FILTER

Count or sum only some rows inside one `GROUP BY`:

```sql
SELECT route,
       count(*)                              AS flights,
       count(*) FILTER (WHERE cancelled)     AS cancelled,
       sum(delay) FILTER (WHERE delay > 15)  AS late_minutes
FROM (VALUES ('BLR-BOM', false, 5), ('BLR-BOM', true, NULL), ('BLR-BOM', false, 40))
     t(route, cancelled, delay)
GROUP BY route;
-- BLR-BOM | 3 | 1 | 40
```

Other databases: `sum(CASE WHEN cancelled THEN 1 ELSE 0 END)`.

**Used in:** `sql/gold/mart_flight_daily.sql`.

## 7. Dates and time zones

```sql
SELECT
    try_strptime('01/07/2025 23:30', '%d/%m/%Y %H:%M')                 AS parsed,          -- 2025-07-01 23:30
    try_strptime('garbage', '%d/%m/%Y %H:%M')                          AS bad,             -- NULL, no error
    TIMESTAMP '2025-07-01 18:00' + INTERVAL 330 MINUTE                 AS utc_to_ist,      -- 23:30
    DATE '2025-07-01' + 1                                              AS next_day,        -- 2025-07-02
    DATE '2025-07-02' + TIME '02:05'                                   AS date_plus_time,  -- 2025-07-02 02:05
    date_diff('minute', TIMESTAMP '2025-07-01 18:00', TIMESTAMP '2025-07-01 20:35') AS minutes,  -- 155
    date_trunc('week', DATE '2025-10-22')                              AS week_start,      -- 2025-10-20
    strftime(DATE '2025-07-01', '%Y%m%d')                              AS key_text;        -- 20250701
```

Rules that keep you safe: store UTC; convert for display only; use `try_` functions so
one bad value becomes NULL (and then a reject reason) instead of crashing the job.

**Used in:** `sql/silver/00_macros.sql` (`parse_utc`, `arrival_utc`, `to_ist`).

## 8. Anti-join: rows with no match

"Bookings whose flight does not exist" or "facts with no dimension row":

```sql
SELECT b.*
FROM bookings AS b
LEFT JOIN flights AS f ON f.flight_no = b.flight_no AND f.flight_date = b.flight_date
WHERE f.flight_no IS NULL;
```

**Used in:** `flight_found` in `bookings_check.sql`; `count_orphans()` in `pipeline/gold.py`.

## 9. Quantiles per group (outliers)

```sql
SELECT route, cabin,
       quantile_cont(fare, 0.25) AS q1,
       quantile_cont(fare, 0.75) AS q3
FROM fares GROUP BY route, cabin;
-- outlier if fare > q3 + 3 * (q3 - q1) or fare < q1 - 3 * (q3 - q1)
```

Other databases: `percentile_cont(0.25) WITHIN GROUP (ORDER BY fare)`.

**Used in:** `route_cabin_fare_range` in `sql/gold/fact_booking.sql`.

## 10. Joining a fact to a dimension by a hashed key

```sql
SELECT b.booking_id, r.route_code
FROM gold.fact_booking AS b
JOIN gold.dim_route AS r ON r.route_key = b.route_key;
```

and building that key in the first place: `md5(origin || '-' || destination)`.

**Used in:** every `sql/gold/fact_*.sql`.
