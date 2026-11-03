"""Run the pipeline.

    python -m pipeline.run --date 2025-07-01
    python -m pipeline.run --start 2025-07-01 --end 2025-12-31     # backfill
    python -m pipeline.run --full-refresh                          # rebuild silver from bronze

Exit codes: 0 success, 1 a step failed or a blocking check stopped the run,
2 the configuration is unusable (for example, the PII key is missing).
"""

import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone

from pipeline import bronze, db, gold, pii, silver
from pipeline.checks import PipelineError, record_check
from pipeline.logs import configure_logging, log_event, record_step
from pipeline.settings import MissingPiiKeyError, load_settings

# Steps run once for each day, in this order. Each names the steps it depends on.
DAILY_STEPS = (
    ("ingest_bronze", bronze.ingest_day, ()),
    ("load_silver", silver.load_silver, ("ingest_bronze",)),
)

# Steps run once at the end of the run: gold is rebuilt once, not once per day.
FINAL_STEPS = (
    ("build_gold", gold.build_gold, ("load_silver",)),
    ("check_gold", gold.check_gold, ("build_gold",)),
    ("export", gold.export, ("check_gold",)),
)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Run the Nova Air pipeline.")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--full-refresh", action="store_true",
                        help="rebuild silver and gold from everything already in bronze")
    parser.add_argument("--data-dir", help="defaults to data/ in the repo")
    args = parser.parse_args(argv)
    if args.date and (args.start or args.end):
        parser.error("use --date, or --start with --end, not both")
    if bool(args.start) != bool(args.end):
        parser.error("--start and --end go together")
    if args.start and args.start > args.end:
        parser.error("--start must not be after --end")
    if not (args.date or args.start or args.full_refresh):
        parser.error("give --date, --start/--end, or --full-refresh")
    return args


def days_between(start, end):
    days = []
    while start <= end:
        days.append(start)
        start += timedelta(days=1)
    return days


def new_run_id():
    return datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S%fZ")


def run_step(con, run_id, name, target, function, *args):
    """Run one step inside one transaction, so a failed step changes nothing.
    Time it, log it, record it in meta.pipeline_runs, and re-raise any failure."""
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    clock = time.perf_counter()
    log_event("step_started", step=name, target=target)
    con.begin()
    try:
        counts = function(*args) or {}
        seconds = time.perf_counter() - clock
        record_step(con, run_id, name, target, "succeeded", started_at, seconds, counts)
        con.commit()
    except Exception as error:
        con.rollback()
        # Recorded after the rollback, so the failure itself is kept.
        if isinstance(error, PipelineError):
            record_check(con, run_id, error.batch_id, error.source, error.check_name, "block",
                         error.row_count)
        record_step(con, run_id, name, target, "failed", started_at,
                    time.perf_counter() - clock, {}, str(error))
        log_event("step_failed", step=name, target=target, error=str(error))
        raise
    log_event("step_finished", step=name, target=target, seconds=round(seconds, 2),
              **{k: v for k, v in counts.items() if k.startswith("rows")})
    return counts


def days_in_bronze(con):
    rows = con.execute("SELECT DISTINCT file_date FROM meta.file_log "
                       "WHERE file_date IS NOT NULL").fetchall()
    return [row[0] for row in rows]


def check_dependencies(name, depends_on, finished):
    missing = [step for step in depends_on if step not in finished]
    if missing:
        raise RuntimeError(f"step {name} needs {missing} to have run first")


def run_pipeline(settings, days, full_refresh=False):
    """Run every step for the given days, then the final steps. Returns the run id."""
    run_id = new_run_id()
    con = db.connect(settings.warehouse_path)
    try:
        db.run_sql_file(con, "meta/create_tables.sql")
        pii.register_pii_function(con, settings.pii_key)
        log_event("run_started", run_id=run_id, days=len(days), full_refresh=full_refresh)
        finished = set()
        if full_refresh:
            run_step(con, run_id, "reset_silver", "all", silver.reset_silver, con, settings,
                     run_id)
            # Replay every day bronze already holds, one day per transaction, exactly
            # as the original daily runs did.
            days = sorted(set(days) | set(days_in_bronze(con)))
        for day in days or [None]:
            target = day.isoformat() if day else "reference"
            for name, function, depends_on in DAILY_STEPS:
                check_dependencies(name, depends_on, finished)
                run_step(con, run_id, name, target, function, con, settings, run_id, day)
                finished.add(name)
        for name, function, depends_on in FINAL_STEPS:
            check_dependencies(name, depends_on, finished)
            run_step(con, run_id, name, "all", function, con, settings, run_id)
            finished.add(name)
        log_event("run_finished", run_id=run_id)
        return run_id
    finally:
        con.close()


def main(argv=None):
    configure_logging()
    args = parse_args(argv)
    try:
        settings = load_settings(args.data_dir)
    except MissingPiiKeyError as error:
        log_event("config_error", error=str(error))
        return 2
    if args.date:
        days = [args.date]
    elif args.start:
        days = days_between(args.start, args.end)
    else:
        days = []
    try:
        run_pipeline(settings, days, args.full_refresh)
    except Exception as error:
        log_event("run_failed", error=f"{type(error).__name__}: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
