"""Gold: the star schema joins cleanly, keys are stable, and outliers are judged per route."""

import duckdb
import pytest

from pipeline.checks import PipelineError
from pipeline.gold import FOREIGN_KEYS, TABLE_KEYS, check_gold, count_orphans
from pipeline.run import run_pipeline
from tests.conftest import FIXTURE_DAYS, one


def test_facts_have_the_expected_rows(warehouse):
    assert one(warehouse, "SELECT count(*) FROM gold.fact_flight")[0] == 8
    assert one(warehouse, "SELECT count(*) FROM gold.fact_booking")[0] == 16


def test_no_orphan_keys_in_any_fact_or_mart(warehouse):
    for fact, column, dimension, key in FOREIGN_KEYS:
        assert count_orphans(warehouse, fact, column, dimension, key) == 0, (fact, column)


def test_facts_really_join_to_dimensions_through_surrogate_keys(warehouse):
    # Every booking reaches its route code and passenger tier through keys alone.
    joined = one(warehouse, """
        SELECT count(*) FROM gold.fact_booking AS b
        JOIN gold.fact_flight AS f ON f.flight_key = b.flight_key
        JOIN gold.dim_route AS r ON r.route_key = b.route_key
        JOIN gold.dim_passenger AS p ON p.passenger_key = b.passenger_key
        JOIN gold.dim_date AS d ON d.date_key = b.date_key""")
    assert joined[0] == 16


def test_every_key_is_unique(warehouse):
    for table, key in TABLE_KEYS:
        dupes = one(warehouse, f"SELECT count(*) - count(DISTINCT {key}) FROM {table}")
        assert dupes[0] == 0, table


def test_surrogate_keys_survive_a_full_rebuild(settings):
    run_pipeline(settings, list(FIXTURE_DAYS))
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as con:
        before = con.execute("SELECT flight_key FROM gold.fact_flight ORDER BY 1").fetchall()
    run_pipeline(settings, [], full_refresh=True)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as con:
        after = con.execute("SELECT flight_key FROM gold.fact_flight ORDER BY 1").fetchall()
    assert before == after


def test_fare_outliers_use_route_and_cabin_thresholds(warehouse):
    flagged = warehouse.execute("""
        SELECT booking_id FROM gold.fact_booking WHERE is_fare_outlier""").fetchall()
    # 20,000 is wildly high for Bengaluru-Mumbai (B006) but normal for
    # Bengaluru-Delhi (B015). A single global threshold could not tell them apart.
    assert flagged == [("B006",)]


def test_outlier_flag_is_used_downstream(warehouse):
    total = one(warehouse, "SELECT sum(fare_outlier_bookings) FROM gold.mart_booking_daily")
    assert total[0] == 1


def test_unknown_members_exist_in_every_dimension(warehouse):
    for table, key in TABLE_KEYS:
        if table.startswith("gold.dim_"):
            unknown = "-1" if key != "date_key" else -1
            assert one(warehouse, f"SELECT count(*) FROM {table} WHERE {key} = $k",
                       {"k": unknown})[0] == 1, table


def test_more_passengers_than_seats_stops_the_run(settings):
    run_pipeline(settings, list(FIXTURE_DAYS))
    with duckdb.connect(str(settings.warehouse_path)) as con:
        # Shrink VT-TAA's economy cabin to 2 seats: NV1001 on 1 July flew 4 economy passengers.
        con.execute("UPDATE gold.dim_aircraft SET seats_economy = 2 WHERE aircraft_reg = 'VT-TAA'")
        with pytest.raises(PipelineError, match="more passengers than seats"):
            check_gold(con, settings, "test-run")
