"""Gold: rebuild the star schema and KPI marts from silver, check them, export them.

Gold is rebuilt in full on every run. At this size that takes a couple of seconds,
and a full rebuild can never leave stale rows behind. docs/SCALING.md explains
what replaces it when the data is too big.
"""

from pipeline.checks import block, check_unique
from pipeline.db import run_sql_file, scalar
from pipeline.logs import log_event
from pipeline.settings import rule_params

# Dimensions first, because the facts look up their keys; marts last.
GOLD_TABLES = (
    "dim_date", "dim_airport", "dim_route", "dim_aircraft", "dim_passenger",
    "dim_delay_reason", "fact_flight", "fact_booking", "mart_flight_daily",
    "mart_booking_daily",
)

# (table, key column) for every table whose key must be unique.
TABLE_KEYS = (
    ("gold.dim_date", "date_key"), ("gold.dim_airport", "airport_key"),
    ("gold.dim_route", "route_key"), ("gold.dim_aircraft", "aircraft_key"),
    ("gold.dim_passenger", "passenger_key"), ("gold.dim_delay_reason", "delay_reason_key"),
    ("gold.fact_flight", "flight_key"), ("gold.fact_booking", "booking_key"),
)

# (fact table, foreign key column, dimension table, dimension key column)
FOREIGN_KEYS = (
    ("gold.fact_flight", "date_key", "gold.dim_date", "date_key"),
    ("gold.fact_flight", "route_key", "gold.dim_route", "route_key"),
    ("gold.fact_flight", "origin_airport_key", "gold.dim_airport", "airport_key"),
    ("gold.fact_flight", "destination_airport_key", "gold.dim_airport", "airport_key"),
    ("gold.fact_flight", "aircraft_key", "gold.dim_aircraft", "aircraft_key"),
    ("gold.fact_flight", "delay_reason_key", "gold.dim_delay_reason", "delay_reason_key"),
    ("gold.fact_booking", "flight_key", "gold.fact_flight", "flight_key"),
    ("gold.fact_booking", "date_key", "gold.dim_date", "date_key"),
    ("gold.fact_booking", "route_key", "gold.dim_route", "route_key"),
    ("gold.fact_booking", "passenger_key", "gold.dim_passenger", "passenger_key"),
    ("gold.mart_flight_daily", "route_key", "gold.dim_route", "route_key"),
    ("gold.mart_booking_daily", "route_key", "gold.dim_route", "route_key"),
)

META_EXPORTS = ("pipeline_runs", "reconciliation", "dq_results", "schema_changes",
                "file_log", "layer_counts", "quarantine_summary")


def build_gold(con, settings, run_id):
    """Gold step: rebuild every gold table, in dependency order."""
    run_sql_file(con, "silver/00_macros.sql")
    params = rule_params(settings.config)
    for table in GOLD_TABLES:
        run_sql_file(con, f"gold/{table}.sql", params)
    rows = scalar(con, "SELECT count(*) FROM gold.fact_booking")
    log_event("gold_built", tables=len(GOLD_TABLES), fact_booking_rows=rows)
    return {"rows_in": rows, "rows_out": rows}


def count_orphans(con, fact, column, dimension, key):
    """Fact rows whose key has no matching dimension row."""
    return scalar(con, f"""
        SELECT count(*) FROM {fact} AS f
        LEFT JOIN {dimension} AS d ON d.{key} = f.{column}
        WHERE d.{key} IS NULL""")


def check_gold(con, settings, run_id):
    """Blocking checks: unique keys, no orphans, no impossible load factor."""
    for table, key in TABLE_KEYS:
        check_unique(con, run_id, table, [key], "gold")
    for fact, column, dimension, key in FOREIGN_KEYS:
        orphans = count_orphans(con, fact, column, dimension, key)
        if orphans:
            block(con, run_id, None, "gold", f"orphan_key:{fact}.{column}", orphans,
                  f"{orphans} rows in {fact} have a {column} missing from {dimension}")
    # Checked per flight and cabin: a daily total could hide one overfull flight
    # behind an emptier one on the same route.
    overfull = scalar(con, """
        SELECT count(*) FROM (
            SELECT b.flight_key, b.cabin, count(*) AS flown,
                   any_value(CASE b.cabin WHEN 'PLUS' THEN a.seats_plus
                                          ELSE a.seats_economy END) AS seats
            FROM gold.fact_booking AS b
            JOIN gold.fact_flight AS f USING (flight_key)
            JOIN gold.dim_aircraft AS a USING (aircraft_key)
            WHERE b.is_flown
            GROUP BY b.flight_key, b.cabin)
        WHERE flown > seats""")
    if overfull:
        block(con, run_id, None, "gold", "load_factor_above_100_percent", overfull,
              f"{overfull} flight cabins carried more passengers than seats")
    log_event("gold_checks_passed", keys=len(TABLE_KEYS), foreign_keys=len(FOREIGN_KEYS))
    return {}


def copy_to(con, table, path, file_format):
    path.parent.mkdir(parents=True, exist_ok=True)
    options = "FORMAT parquet" if file_format == "parquet" else "FORMAT csv, HEADER true"
    con.execute(f"COPY (SELECT * FROM {table}) TO '{path.as_posix()}' ({options})")


def export(con, settings, run_id):
    """Export gold (Parquet and CSV) and the meta summaries (Parquet) for the
    dashboard and Power BI. The dashboard never opens the DuckDB file."""
    run_sql_file(con, "meta/health_snapshot.sql")
    gold_dir = settings.export_dir / "gold"
    for table in GOLD_TABLES:
        copy_to(con, f"gold.{table}", gold_dir / f"{table}.parquet", "parquet")
        copy_to(con, f"gold.{table}", gold_dir / f"{table}.csv", "csv")
    for table in META_EXPORTS:
        copy_to(con, f"meta.{table}", settings.export_dir / "meta" / f"{table}.parquet",
                "parquet")
    log_event("exported", folder=settings.export_dir.as_posix(),
              files=2 * len(GOLD_TABLES) + len(META_EXPORTS))
    return {}
