"""Reconciliation: every row in is accounted for, and the run stops when it is not."""

import duckdb
import pytest

from pipeline import silver
from pipeline.checks import PipelineError
from pipeline.run import run_pipeline
from tests.conftest import FIXTURE_DAYS, make_settings, one


def test_every_batch_balances(warehouse):
    unbalanced = one(warehouse, "SELECT count(*) FROM meta.reconciliation WHERE NOT balanced")
    assert unbalanced[0] == 0
    assert one(warehouse, "SELECT count(*) FROM meta.reconciliation")[0] == 9


def test_day_one_bookings_add_up_by_hand(warehouse):
    # 21 rows: 1 exact copy of B001, 1 older B003, 7 quarantined (5 rejected:
    # B007 B008 B009 blank-id B019; 2 waiting: B012 B013), and 12 loaded.
    row = one(warehouse, """
        SELECT rows_in, rows_exact_duplicate, rows_older_version, rows_quarantined, rows_loaded
        FROM meta.reconciliation WHERE source = 'bookings' AND file_date = '2025-07-01'""")
    assert row == (21, 1, 1, 7, 12)


def test_stale_resend_counts_as_an_older_version(warehouse):
    row = one(warehouse, """
        SELECT rows_in, rows_older_version, rows_loaded
        FROM meta.reconciliation WHERE source = 'bookings' AND file_date = '2025-07-02'""")
    assert row == (3, 1, 2)


def test_broken_reconciliation_stops_the_run_and_changes_nothing(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    real_counts = silver.batch_counts

    def counts_that_lose_a_row(con):
        counts = real_counts(con)
        counts["rows_loaded"] -= 1  # simulate a row that silently went missing
        return counts

    monkeypatch.setattr(silver, "batch_counts", counts_that_lose_a_row)
    with pytest.raises(PipelineError, match="accounted for"):
        run_pipeline(settings, [FIXTURE_DAYS[0]])
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as con:
        assert one(con, "SELECT count(*) FROM meta.dq_results WHERE severity = 'block' "
                        "AND check_name = 'reconciliation_mismatch'")[0] == 1
        assert one(con, "SELECT count(*) FROM meta.reconciliation")[0] == 0
        assert one(con, "SELECT count(*) FROM meta.pipeline_runs WHERE status = 'failed'")[0] == 1


def test_too_many_rejected_rows_stop_the_run(tmp_path):
    # With the real 20% limit, day one's bookings (5 of 21 rejected) are too broken.
    settings = make_settings(tmp_path)
    settings.config["thresholds"]["quarantine_block_rate"] = 0.20
    with pytest.raises(PipelineError, match="rejected"):
        run_pipeline(settings, [FIXTURE_DAYS[0]])
