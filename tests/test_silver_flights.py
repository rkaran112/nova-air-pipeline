"""Silver flights: each flight defect from the fixtures is handled as documented."""

from datetime import datetime

from tests.conftest import one, rows_as_dicts


def flight(con, flight_no, flight_date="2025-07-01"):
    return rows_as_dicts(con, "SELECT * FROM silver.flights WHERE flight_no = $no "
                              "AND flight_date = $d", {"no": flight_no, "d": flight_date})


def quarantine_reason(con, source, text):
    return one(con, "SELECT reason_code FROM silver.quarantine WHERE source = $s "
                    "AND record LIKE $t", {"s": source, "t": f"%{text}%"})


def test_overnight_flight_survives_with_correct_duration(warehouse):
    # " NV 1003 " leaves at 23:30 IST and arrives "02:05": the arrival is next day.
    rows = flight(warehouse, "NV1003")
    assert len(rows) == 1
    departs, arrives = rows[0]["sched_dep_utc"], rows[0]["sched_arr_utc"]
    assert (arrives - departs).total_seconds() / 60 == 155
    assert arrives == datetime(2025, 7, 1, 20, 35)  # 02:05 IST on 2 July, in UTC
    assert quarantine_reason(warehouse, "flights", "1003") is None


def test_timestamp_formats_all_become_utc(warehouse):
    # NV1002 was sent in UTC ("Z"), NV1003 day-first with no zone (IST), NV1001 with +05:30.
    assert flight(warehouse, "NV1002")[0]["sched_dep_utc"] == datetime(2025, 7, 1, 3, 0)
    assert flight(warehouse, "NV1003")[0]["sched_dep_utc"] == datetime(2025, 7, 1, 18, 0)
    assert flight(warehouse, "NV1001")[0]["sched_dep_utc"] == datetime(2025, 7, 1, 0, 30)


def test_flight_number_variants_are_standardised(warehouse):
    numbers = {row[0] for row in warehouse.execute(
        "SELECT flight_no FROM silver.flights").fetchall()}
    assert {"NV1002", "NV1003"} <= numbers
    assert all(n == n.strip().upper() and "-" not in n for n in numbers)


def test_exact_duplicate_and_older_version_leave_one_row(warehouse):
    nv1002 = flight(warehouse, "NV1002")
    assert len(nv1002) == 1
    assert nv1002[0]["actual_arr_utc"] is not None  # the newer version, with actual times


def test_corrupted_flight_number_is_quarantined(warehouse):
    assert quarantine_reason(warehouse, "flights", "N?1006") == ("INVALID_FLIGHT_NO",)


def test_arrival_before_departure_is_quarantined(warehouse):
    assert quarantine_reason(warehouse, "flights", "NV1007") == ("IMPOSSIBLE_DURATION",)
    assert flight(warehouse, "NV1007") == []


def test_unreadable_timestamp_is_quarantined(warehouse):
    assert quarantine_reason(warehouse, "flights", "not-a-time") == ("BAD_TIMESTAMP",)


def test_cancelled_flight_loses_its_actual_times(warehouse):
    row = flight(warehouse, "NV1004")[0]
    assert row["status"] == "CANCELLED"
    assert row["actual_dep_utc"] is None and row["actual_arr_utc"] is None
    assert row["actuals_cleared"]


def test_operated_flight_without_arrival_is_kept_and_flagged(warehouse):
    row = flight(warehouse, "NV1005")[0]
    assert row["actuals_missing"]


def test_correction_a_day_later_updates_without_duplicating(warehouse):
    rows = flight(warehouse, "NV1001")
    assert len(rows) == 1
    # Corrected to 08:05 IST in the 2 July file; the stale 07:50 resend on 3 July
    # is older, so it must not win.
    assert rows[0]["actual_arr_utc"] == datetime(2025, 7, 1, 2, 35)


def test_all_eight_scheduled_flights_reach_silver(warehouse):
    assert one(warehouse, "SELECT count(*) FROM silver.flights")[0] == 8
