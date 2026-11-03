"""Data quality checks. Every result is written to meta.dq_results with a severity:

- block: continuing would publish wrong or unsafe numbers, so the run stops.
- warn:  the numbers are still right, but someone should look.
- info:  a count worth keeping, such as rows fixed by a documented rule.
"""

from pipeline.db import scalar


class PipelineError(Exception):
    """A blocking check failed. The runner records it, stops, and exits non-zero.

    It is recorded by the runner rather than here, because the batch's transaction
    is rolled back first and would take the record with it.
    """

    def __init__(self, message, source, batch_id, check_name, row_count):
        super().__init__(message)
        self.source = source
        self.batch_id = batch_id
        self.check_name = check_name
        self.row_count = row_count


def record_check(con, run_id, batch_id, source, check_name, severity, row_count):
    con.execute("INSERT INTO meta.dq_results VALUES ($run_id, $batch_id, $source, $check, "
                "$severity, $row_count)",
                {"run_id": run_id, "batch_id": batch_id, "source": source,
                 "check": check_name, "severity": severity, "row_count": int(row_count)})


def block(con, run_id, batch_id, source, check_name, row_count, message):
    """Stop the run. The runner writes the failure to meta.dq_results."""
    raise PipelineError(message, source, batch_id, check_name, row_count)


def check_reconciliation(con, run_id, batch_id, source, counts):
    """rows in = loaded + exact duplicates + older versions + quarantined, or the run stops."""
    accounted = (counts["rows_loaded"] + counts["rows_exact_duplicate"]
                 + counts["rows_older_version"] + counts["rows_quarantined"])
    balanced = accounted == counts["rows_in"]
    con.execute(
        """INSERT INTO meta.reconciliation VALUES ($batch_id, $source, $file_date, $rows_in,
           $rows_loaded, $rows_exact_duplicate, $rows_older_version, $rows_quarantined,
           $balanced, $run_id)""",
        {"batch_id": batch_id, "source": source, "file_date": counts.get("file_date"),
         "rows_in": counts["rows_in"], "rows_loaded": counts["rows_loaded"],
         "rows_exact_duplicate": counts["rows_exact_duplicate"],
         "rows_older_version": counts["rows_older_version"],
         "rows_quarantined": counts["rows_quarantined"], "balanced": balanced,
         "run_id": run_id})
    if not balanced:
        block(con, run_id, batch_id, source, "reconciliation_mismatch",
              counts["rows_in"] - accounted,
              f"{batch_id}: {counts['rows_in']} rows in but {accounted} accounted for")


def check_quarantine_rate(con, run_id, batch_id, source, rows_in, rows_rejected, thresholds):
    """Rejected rows (not bookings waiting for a flight) as a share of the batch."""
    if rows_in == 0:
        return
    rate = rows_rejected / rows_in
    if rate > thresholds["quarantine_block_rate"]:
        block(con, run_id, batch_id, source, "quarantine_rate_too_high", rows_rejected,
              f"{batch_id}: {rate:.1%} of rows rejected, above the "
              f"{thresholds['quarantine_block_rate']:.0%} limit; the file is probably broken")
    if rate > thresholds["quarantine_warn_rate"]:
        record_check(con, run_id, batch_id, source, "quarantine_rate_high", "warn",
                     rows_rejected)


def check_unique(con, run_id, table, key_columns, source):
    """A business or surrogate key must identify exactly one row."""
    keys = ", ".join(key_columns)
    duplicates = scalar(con, f"""
        SELECT count(*) FROM (SELECT {keys} FROM {table} GROUP BY {keys} HAVING count(*) > 1)""")
    if duplicates:
        block(con, run_id, None, source, f"duplicate_key:{table}", duplicates,
              f"{table} has {duplicates} keys that appear more than once")
