"""Silver: turn each bronze batch into clean, typed, de-duplicated rows.

For every batch not yet processed, in date order:
  1. <source>_check.sql      parse each row and give it a reject reason (or none)
  2. quarantine_rejects.sql  move failed rows to silver.quarantine
  3. <source>_merge.sql      keep the latest version per key and upsert it
  4. reconcile               every row in must be accounted for, or the run stops
The runner wraps the whole step in one transaction, so if any batch fails, silver
is left exactly as it was before the step.
"""

from pipeline.checks import check_quarantine_rate, check_reconciliation, record_check
from pipeline.db import run_sql_file, scalar
from pipeline.logs import log_event
from pipeline.settings import rule_params


def prepare(con):
    run_sql_file(con, "silver/00_macros.sql")
    run_sql_file(con, "silver/create_tables.sql")
    run_sql_file(con, "silver/reference.sql")


def pending_batches(con, source_order, up_to_day):
    """Daily batches in bronze that silver has not processed yet, oldest first,
    up to and including the given day (all of them if no day is given)."""
    return con.execute("""
        SELECT f.batch_id, f.source, f.file_date
        FROM meta.file_log AS f
        LEFT JOIN meta.reconciliation AS r ON r.batch_id = f.batch_id
        WHERE r.batch_id IS NULL AND f.file_date IS NOT NULL
          AND ($up_to_day IS NULL OR f.file_date <= $up_to_day)
        ORDER BY f.file_date, list_position($order, f.source), f.batch_id""",
                       {"order": list(source_order), "up_to_day": up_to_day}).fetchall()


def batch_counts(con):
    """Count where every row of this batch went. Retried bookings are counted
    separately, because they belong to the batch they first arrived in."""
    counts = {}
    queries = {
        "rows_in": "SELECT count(*) FROM checked_rows WHERE row_origin = 'batch'",
        "rows_exact_duplicate":
            "SELECT count(*) FROM checked_rows WHERE row_origin = 'batch' AND copy_number > 1",
        "rows_quarantined": """SELECT count(*) FROM checked_rows WHERE row_origin = 'batch'
                               AND copy_number = 1 AND reject_reason IS NOT NULL""",
        "rows_waiting": """SELECT count(*) FROM checked_rows WHERE row_origin = 'batch'
                           AND copy_number = 1 AND reject_reason = 'WAITING_FOR_FLIGHT'""",
        "rows_older_version": """SELECT count(*) FROM incoming_rows WHERE row_origin = 'batch'
                                 AND (version_rank > 1 OR older_than_silver)""",
        "rows_loaded": """SELECT count(*) FROM incoming_rows WHERE row_origin = 'batch'
                          AND version_rank = 1 AND NOT older_than_silver""",
        "rows_released": """SELECT count(*) FROM checked_rows
                            WHERE row_origin = 'retry' AND reject_reason IS NULL""",
        "rows_given_up": """SELECT count(*) FROM checked_rows
                            WHERE row_origin = 'retry' AND reject_reason = 'NO_VALID_FLIGHT'""",
    }
    for name, sql in queries.items():
        counts[name] = scalar(con, sql)
    return counts


def record_batch_details(con, run_id, batch_id, source, counts):
    """Write the defect counts for this batch to meta.dq_results."""
    reasons = con.execute("""
        SELECT reject_reason, count(*) FROM checked_rows
        WHERE row_origin = 'batch' AND copy_number = 1 AND reject_reason IS NOT NULL
        GROUP BY ALL""").fetchall()
    for reason, count in reasons:
        severity = "warn" if reason == "WAITING_FOR_FLIGHT" else "info"
        record_check(con, run_id, batch_id, source, f"quarantined:{reason}", severity, count)
    details = {
        "exact_duplicate_removed": ("info", counts["rows_exact_duplicate"]),
        "older_version_ignored": ("info", counts["rows_older_version"]),
        "late_booking_released": ("info", counts["rows_released"]),
        "late_booking_given_up": ("warn", counts["rows_given_up"]),
    }
    if source in ("flights", "bookings"):
        details["flight_no_standardised"] = ("info", scalar(con, """
            SELECT count(*) FROM checked_rows
            WHERE row_origin = 'batch' AND flight_no_was_standardised"""))
    if source == "flights":
        details["arrival_time_only_resolved"] = ("info", scalar(con, """
            SELECT count(*) FROM checked_rows WHERE copy_number = 1
            AND reject_reason IS NULL AND arrival_was_time_only"""))
        loaded = "version_rank = 1 AND NOT older_than_silver"
        details["cancelled_actual_times_cleared"] = ("warn", scalar(
            con, f"SELECT count(*) FROM incoming_rows WHERE actuals_cleared AND {loaded}"))
        details["operated_without_actual_times"] = ("warn", scalar(
            con, f"SELECT count(*) FROM incoming_rows WHERE actuals_missing AND {loaded}"))
    if source == "bookings":
        # Includes retried bookings, which are converted when they are finally loaded.
        details["usd_fare_converted"] = ("info", scalar(con, """
            SELECT count(*) FROM checked_rows WHERE copy_number = 1
            AND reject_reason IS NULL AND currency = 'USD'"""))
    for name, (severity, count) in details.items():
        if count:
            record_check(con, run_id, batch_id, source, name, severity, count)


def process_batch(con, settings, run_id, batch_id, source, file_date):
    params = {**rule_params(settings.config), "batch_id": batch_id, "source": source,
              "file_date": file_date}
    run_sql_file(con, f"silver/{source}_check.sql", params)
    run_sql_file(con, "silver/quarantine_rejects.sql", params)
    run_sql_file(con, f"silver/{source}_merge.sql", params)
    counts = batch_counts(con)
    counts["file_date"] = file_date
    record_batch_details(con, run_id, batch_id, source, counts)
    check_reconciliation(con, run_id, batch_id, source, counts)
    check_quarantine_rate(con, run_id, batch_id, source, counts["rows_in"],
                          counts["rows_quarantined"] - counts["rows_waiting"],
                          settings.config["thresholds"])
    log_event("batch_loaded", batch_id=batch_id,
              **{k: v for k, v in counts.items() if k.startswith("rows")})
    return counts


def load_silver(con, settings, run_id, day=None):
    """Silver step: process every pending batch up to this day, oldest first.
    Stopping at the day keeps a replay identical to the original daily runs: a
    booking is checked against the flights known on its day, not on later days."""
    prepare(con)
    totals = {"rows_in": 0, "rows_out": 0, "rows_quarantined": 0}
    for batch_id, source, file_date in pending_batches(con, settings.config["sources"], day):
        counts = process_batch(con, settings, run_id, batch_id, source, file_date)
        totals["rows_in"] += counts["rows_in"]
        totals["rows_out"] += counts["rows_loaded"]
        totals["rows_quarantined"] += counts["rows_quarantined"]
    return totals


def reset_silver(con, settings, run_id):
    """Full refresh: empty silver, so the next load replays every bronze batch."""
    run_sql_file(con, "silver/reset.sql")
    log_event("silver_reset", run_id=run_id)
    return {}
