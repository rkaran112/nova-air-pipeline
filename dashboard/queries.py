"""Every query the dashboard runs. They read only the exported gold and meta Parquet
files (data/exports), never the warehouse, so the dashboard holds no lock on it and
can only see what the pipeline chose to publish: no raw personal data.

Ratios are always sum(numerator) / sum(denominator) over the filtered rows.
"""

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

EXPORT_DIR = Path(os.environ.get("NOVA_EXPORT_DIR",
                                  Path(__file__).resolve().parent.parent / "data" / "exports"))
GOLD_TABLES = ("dim_date", "dim_airport", "dim_route", "dim_aircraft", "dim_delay_reason",
               "fact_flight", "fact_booking", "mart_flight_daily", "mart_booking_daily")
META_TABLES = ("pipeline_runs", "reconciliation", "dq_results", "file_log", "layer_counts",
               "quarantine_summary")


@dataclass(frozen=True)
class Filters:
    start: date
    end: date
    routes: tuple  # empty means all routes
    cabin: str     # "ALL", "ECONOMY" or "PLUS"

    def params(self):
        return {"start": self.start, "end": self.end, "routes": list(self.routes),
                "cabin": self.cabin}


# Shared WHERE clauses. They expect dim_date as d and dim_route as r in the query.
DATE_AND_ROUTE = ("d.calendar_date BETWEEN $start AND $end "
                  "AND (len($routes) = 0 OR list_contains($routes, r.route_code))")
CABIN = "($cabin = 'ALL' OR m.cabin = $cabin)"


def connect(export_dir=EXPORT_DIR):
    """An in-memory DuckDB with one view per exported file."""
    con = duckdb.connect()
    for folder, tables in (("gold", GOLD_TABLES), ("meta", META_TABLES)):
        for table in tables:
            path = (Path(export_dir) / folder / f"{table}.parquet").as_posix()
            con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{path}')")
    return con


def run(con, sql, filters=None):
    params = filters.params() if filters else {}
    used = {name: value for name, value in params.items() if f"${name}" in sql}
    return con.execute(sql, used).df()


def date_bounds(con):
    return con.execute("SELECT min(calendar_date), max(calendar_date) FROM dim_date "
                       "WHERE date_key > 0").fetchone()


def route_codes(con):
    return [row[0] for row in con.execute(
        "SELECT route_code FROM dim_route WHERE route_key <> '-1' ORDER BY 1").fetchall()]


def headline_kpis(con, filters):
    booking = run(con, f"""
        SELECT sum(m.total_revenue_inr)                          AS revenue,
               sum(m.passengers_flown)                           AS passengers,
               sum(m.passengers_flown) / nullif(sum(m.seats_offered), 0) AS load_factor
        FROM mart_booking_daily AS m
        JOIN dim_date AS d USING (date_key) JOIN dim_route AS r USING (route_key)
        WHERE {DATE_AND_ROUTE} AND {CABIN}""", filters)
    flight = run(con, f"""
        SELECT sum(m.flights_on_time) / nullif(sum(m.flights_measured), 0)    AS on_time,
               sum(m.flights_cancelled) / nullif(sum(m.flights_scheduled), 0) AS cancellation
        FROM mart_flight_daily AS m
        JOIN dim_date AS d USING (date_key) JOIN dim_route AS r USING (route_key)
        WHERE {DATE_AND_ROUTE}""", filters)
    return {**booking.iloc[0].to_dict(), **flight.iloc[0].to_dict()}


def monthly_trends(con, filters):
    return run(con, f"""
        WITH booking AS (
            SELECT d.year, d.month, any_value(d.month_label) AS month_label,
                   sum(m.total_revenue_inr) AS revenue,
                   sum(m.passengers_flown) / nullif(sum(m.seats_offered), 0) AS load_factor
            FROM mart_booking_daily AS m
            JOIN dim_date AS d USING (date_key) JOIN dim_route AS r USING (route_key)
            WHERE {DATE_AND_ROUTE} AND {CABIN}
            GROUP BY d.year, d.month
        ),
        flight AS (
            SELECT d.year, d.month,
                   sum(m.flights_on_time) / nullif(sum(m.flights_measured), 0) AS on_time
            FROM mart_flight_daily AS m
            JOIN dim_date AS d USING (date_key) JOIN dim_route AS r USING (route_key)
            WHERE {DATE_AND_ROUTE}
            GROUP BY d.year, d.month
        )
        SELECT * FROM booking JOIN flight USING (year, month) ORDER BY year, month""",
               filters)


def weekly_revenue(con, filters):
    return run(con, f"""
        SELECT date_trunc('week', d.calendar_date) AS week_start,
               sum(m.total_revenue_inr)            AS revenue
        FROM mart_booking_daily AS m
        JOIN dim_date AS d USING (date_key) JOIN dim_route AS r USING (route_key)
        WHERE {DATE_AND_ROUTE} AND {CABIN}
        GROUP BY ALL
        -- Only whole weeks: a 3-day week at the edge would look like a slump.
        HAVING count(DISTINCT d.calendar_date) = 7
        ORDER BY 1""", filters)


def route_performance(con, filters):
    return run(con, f"""
        SELECT r.route_code,
               sum(m.passengers_flown)                                   AS passengers,
               sum(m.total_revenue_inr)                                  AS revenue,
               sum(m.passengers_flown) / nullif(sum(m.seats_offered), 0) AS load_factor,
               sum(m.total_revenue_inr) / nullif(sum(m.ask), 0)          AS rask,
               sum(m.fare_revenue_inr) / nullif(sum(m.rpk), 0)           AS yield_per_rpk,
               sum(m.ask)                                                AS ask
        FROM mart_booking_daily AS m
        JOIN dim_date AS d USING (date_key) JOIN dim_route AS r USING (route_key)
        WHERE {DATE_AND_ROUTE} AND {CABIN}
        GROUP BY r.route_code
        HAVING sum(m.seats_offered) > 0
        ORDER BY rask DESC""", filters)


DELAYED_FLIGHTS = f"""
    FROM fact_flight AS f
    JOIN dim_date AS d USING (date_key)
    JOIN dim_route AS r USING (route_key)
    WHERE {DATE_AND_ROUTE} AND f.is_operated AND f.departure_delay_minutes IS NOT NULL"""


def delay_causes(con, filters):
    return run(con, f"""
        SELECT dr.category,
               sum(greatest(f.departure_delay_minutes, 0)) AS delay_minutes,
               count(*)                                    AS flights
        FROM fact_flight AS f
        JOIN dim_date AS d USING (date_key)
        JOIN dim_route AS r USING (route_key)
        JOIN dim_delay_reason AS dr USING (delay_reason_key)
        WHERE {DATE_AND_ROUTE} AND f.is_operated AND dr.category <> 'No delay'
        GROUP BY dr.category ORDER BY delay_minutes DESC""", filters)


def delay_by_airport_hour(con, filters):
    return run(con, f"""
        SELECT r.origin AS airport,
               f.sched_dep_hour_ist AS hour,
               avg(greatest(f.departure_delay_minutes, 0)) AS avg_delay,
               count(*) AS flights
        {DELAYED_FLIGHTS}
        GROUP BY ALL ORDER BY airport, hour""", filters)


def delay_by_airport_month(con, filters):
    return run(con, f"""
        SELECT r.origin AS airport,
               d.month,
               any_value(d.month_label) AS month_label,
               avg(greatest(f.departure_delay_minutes, 0)) AS avg_delay
        {DELAYED_FLIGHTS}
        GROUP BY r.origin, d.month ORDER BY airport, d.month""", filters)


def delay_by_leg(con, filters):
    return run(con, f"""
        SELECT f.aircraft_leg_number AS leg,
               avg(greatest(f.departure_delay_minutes, 0)) AS avg_delay,
               avg(CAST(f.is_on_time AS INTEGER))          AS on_time,
               count(*)                                    AS flights
        {DELAYED_FLIGHTS}
        GROUP BY ALL ORDER BY leg""", filters)


def last_run(con):
    return run(con, """
        SELECT run_id, step, target, status, duration_seconds, rows_in, rows_out,
               rows_quarantined, message
        FROM pipeline_runs
        WHERE run_id = (SELECT max_by(run_id, started_at) FROM pipeline_runs)
        ORDER BY started_at""")


def freshness(con):
    return con.execute("""
        SELECT (SELECT max(calendar_date) FROM dim_date)         AS latest_flight_date,
               (SELECT max(file_date) FROM file_log)             AS latest_file_date,
               (SELECT max(loaded_at) FROM file_log)             AS last_loaded_at""").fetchone()


def reconciliation_summary(con):
    return run(con, """
        SELECT source,
               count(*)                           AS batches,
               count(*) FILTER (WHERE balanced)   AS balanced_batches,
               sum(rows_in)                       AS rows_in,
               sum(rows_loaded)                   AS loaded,
               sum(rows_exact_duplicate)          AS exact_duplicates,
               sum(rows_older_version)            AS older_versions,
               sum(rows_quarantined)              AS quarantined
        FROM reconciliation GROUP BY source ORDER BY source""")


def layer_counts(con):
    return run(con, "SELECT layer, table_name, row_count FROM layer_counts")


def quarantine_reasons(con):
    return run(con, """
        SELECT source, reason_code, status, row_count FROM quarantine_summary
        ORDER BY row_count DESC""")


def check_results(con):
    return run(con, """
        WITH checks AS (
            SELECT severity,
                   regexp_replace(check_name, ':.*', '') AS check_type,
                   batch_id,
                   row_count
            FROM dq_results
        )
        SELECT severity, check_type, count(DISTINCT batch_id) AS batches, sum(row_count) AS rows
        FROM checks
        GROUP BY severity, check_type
        ORDER BY list_position(['block', 'warn', 'info'], severity), rows DESC""")


def fare_outliers(con, filters):
    return run(con, f"""
        SELECT sum(m.fare_outlier_bookings) AS outliers, sum(m.bookings) AS bookings
        FROM mart_booking_daily AS m
        JOIN dim_date AS d USING (date_key) JOIN dim_route AS r USING (route_key)
        WHERE {DATE_AND_ROUTE} AND {CABIN}""", filters).iloc[0].to_dict()
