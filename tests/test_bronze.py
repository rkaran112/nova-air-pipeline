"""Bronze: every file loaded exactly once, as text, with its schema changes logged."""

import shutil
from datetime import date

import duckdb
import pytest

from pipeline.checks import PipelineError
from pipeline.run import run_pipeline
from tests.conftest import FIXTURE_DAYS, one


def bronze_rows(settings, table):
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as con:
        return one(con, f"SELECT count(*) FROM bronze.{table}")[0]


def test_every_fixture_row_lands_in_bronze(warehouse):
    # 10 + 3 + 2 flight records; 21 + 3 + 1 bookings; 14 + 1 + 1 passengers.
    assert one(warehouse, "SELECT count(*) FROM bronze.flights")[0] == 15
    assert one(warehouse, "SELECT count(*) FROM bronze.bookings")[0] == 25
    assert one(warehouse, "SELECT count(*) FROM bronze.passengers")[0] == 16


def test_bronze_keeps_values_exactly_as_sent(warehouse):
    raw = one(warehouse, "SELECT flight_no FROM bronze.flights WHERE flight_no LIKE '%1003%'")
    assert raw[0] == " NV 1003 "


def test_reprocessing_a_day_loads_nothing_new(settings):
    run_pipeline(settings, [FIXTURE_DAYS[0]])
    before = bronze_rows(settings, "bookings")
    run_pipeline(settings, [FIXTURE_DAYS[0]])
    assert bronze_rows(settings, "bookings") == before == 21


def test_same_content_under_a_new_name_is_skipped(settings):
    run_pipeline(settings, [FIXTURE_DAYS[0]])
    folder = settings.landing_dir / "bookings"
    # Pretend the 1 July file was re-delivered as the 4 July file.
    shutil.copy(folder / "bookings_2025-07-01.csv", folder / "bookings_2025-07-04.csv")
    run_pipeline(settings, [date(2025, 7, 4)])
    assert bronze_rows(settings, "bookings") == 21


def test_new_column_is_added_and_logged(warehouse):
    change = one(warehouse, "SELECT source, column_name, change FROM meta.schema_changes "
                            "WHERE change = 'added'")
    assert change == ("bookings", "promo_code", "added")
    early = one(warehouse, "SELECT promo_code FROM bronze.bookings WHERE booking_id = 'B001'")
    assert early[0] is None


def test_file_missing_a_required_column_stops_the_run(settings):
    path = settings.landing_dir / "bookings" / "bookings_2025-07-01.csv"
    lines = path.read_text().splitlines()
    # Drop the fare_amount column (the 8th) from every line.
    path.write_text("\n".join(",".join(p for i, p in enumerate(line.split(",")) if i != 7)
                              for line in lines) + "\n")
    with pytest.raises(PipelineError, match="fare_amount"):
        run_pipeline(settings, [FIXTURE_DAYS[0]])
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as con:
        assert one(con, "SELECT count(*) FROM meta.dq_results WHERE severity = 'block' "
                        "AND check_name = 'required_column_missing'")[0] == 1
        # The failed step was rolled back: none of that day's files were kept.
        assert one(con, "SELECT count(*) FROM meta.file_log WHERE file_date IS NOT NULL")[0] == 0
