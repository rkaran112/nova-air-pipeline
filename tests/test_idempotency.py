"""Idempotency: running the same thing again changes nothing, however it is run."""

import duckdb

from pipeline.run import run_pipeline
from tests.conftest import FIXTURE_DAYS, fingerprint, make_settings, one


def snapshot(settings):
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as con:
        return fingerprint(con)


def test_second_run_of_the_same_days_changes_nothing(settings):
    run_pipeline(settings, list(FIXTURE_DAYS))
    first = snapshot(settings)
    run_pipeline(settings, list(FIXTURE_DAYS))
    assert snapshot(settings) == first


def test_two_runs_in_one_process_do_not_accumulate_state(settings):
    # The old pipeline kept rejected rows in a module-level list, so a second run in
    # the same Python process reported them twice. Nothing here may carry over.
    run_pipeline(settings, list(FIXTURE_DAYS))
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as con:
        quarantined = one(con, "SELECT count(*) FROM silver.quarantine")[0]
    run_pipeline(settings, list(FIXTURE_DAYS))
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as con:
        assert one(con, "SELECT count(*) FROM silver.quarantine")[0] == quarantined
        assert one(con, "SELECT count(DISTINCT run_id) FROM meta.pipeline_runs")[0] == 2


def test_day_by_day_runs_equal_one_backfill(tmp_path):
    daily = make_settings(tmp_path / "daily")
    for day in FIXTURE_DAYS:
        run_pipeline(daily, [day])
    backfill = make_settings(tmp_path / "backfill")
    run_pipeline(backfill, list(FIXTURE_DAYS))
    assert snapshot(daily) == snapshot(backfill)


def test_full_refresh_rebuilds_exactly_the_same_warehouse(settings):
    run_pipeline(settings, list(FIXTURE_DAYS))
    first = snapshot(settings)
    run_pipeline(settings, [], full_refresh=True)
    assert snapshot(settings) == first
