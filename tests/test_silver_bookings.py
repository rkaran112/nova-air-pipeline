"""Silver bookings and passengers: each defect from the fixtures is handled as documented."""

from datetime import date
from decimal import Decimal

import duckdb

from pipeline.run import run_pipeline
from tests.conftest import FIXTURE_DAYS, fixture_config, make_settings, one, rows_as_dicts


def booking(con, booking_id):
    rows = rows_as_dicts(con, "SELECT * FROM silver.bookings WHERE booking_id = $id",
                         {"id": booking_id})
    return rows[0] if rows else None


def quarantined(con, booking_id):
    return one(con, "SELECT reason_code, status FROM silver.quarantine WHERE source = "
                    "'bookings' AND record LIKE $t", {"t": f'%"{booking_id}"%'})


def test_sixteen_bookings_reach_silver(warehouse):
    assert one(warehouse, "SELECT count(*) FROM silver.bookings")[0] == 16


def test_latest_version_wins_and_stale_resend_is_ignored(warehouse):
    # B003: CONFIRMED, then NO_SHOW (same file), then a stale CONFIRMED resent on 2 July.
    assert booking(warehouse, "B003")["status"] == "NO_SHOW"


def test_flight_number_variant_is_standardised(warehouse):
    assert booking(warehouse, "B004")["flight_no"] == "NV1001"


def test_missing_optional_fields_get_documented_defaults(warehouse):
    assert booking(warehouse, "B004")["channel"] == "UNKNOWN"
    assert booking(warehouse, "B005")["ancillary_inr"] == 0


def test_zero_and_negative_fares_are_quarantined(warehouse):
    assert quarantined(warehouse, "B008") == ("NON_POSITIVE_FARE", "rejected")
    assert quarantined(warehouse, "B009") == ("NON_POSITIVE_FARE", "rejected")


def test_usd_fare_is_converted_at_the_booking_day_rate(warehouse):
    row = booking(warehouse, "B010")
    assert row["currency"] == "USD"
    assert row["fare_inr"] == Decimal("4250.00")      # 50 USD x 85.0 on 20 June
    assert row["ancillary_inr"] == Decimal("850.00")  # 10 USD x 85.0


def test_unknown_currency_and_missing_id_and_bad_flight_are_quarantined(warehouse):
    assert quarantined(warehouse, "B019") == ("UNKNOWN_CURRENCY", "rejected")
    assert quarantined(warehouse, "B007") == ("INVALID_FLIGHT_NO", "rejected")
    assert quarantined(warehouse, "PNR") is None  # the PNR was tokenised, not kept
    missing_id = one(warehouse, "SELECT count(*) FROM silver.quarantine "
                                "WHERE reason_code = 'MISSING_REQUIRED_FIELD'")
    assert missing_id[0] == 2  # one booking, one passenger


def test_late_booking_is_released_once_its_flight_arrives(warehouse):
    # B012 is for NV1009, whose flight record only arrived in the 2 July file.
    assert quarantined(warehouse, "B012") == ("WAITING_FOR_FLIGHT", "released")
    assert booking(warehouse, "B012")["flight_no"] == "NV1009"


def test_booking_for_a_flight_that_never_exists_keeps_waiting(warehouse):
    assert quarantined(warehouse, "B013") == ("WAITING_FOR_FLIGHT", "waiting")
    assert booking(warehouse, "B013") is None


def test_waiting_booking_is_rejected_after_the_grace_period(tmp_path):
    config = fixture_config()
    config["rules"]["late_flight_grace_days"] = 1
    settings = make_settings(tmp_path, config)
    run_pipeline(settings, list(FIXTURE_DAYS))
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as con:
        assert quarantined(con, "B013") == ("NO_VALID_FLIGHT", "rejected")


def test_promo_code_appears_without_breaking_older_rows(warehouse):
    assert booking(warehouse, "B020")["promo_code"] == "NOVA10"
    assert booking(warehouse, "B001")["promo_code"] is None


def test_passenger_versions_and_missing_values(warehouse):
    assert one(warehouse, "SELECT count(*) FROM silver.passengers")[0] == 12
    tiers = dict(warehouse.execute(
        "SELECT age_band, loyalty_tier FROM silver.passengers WHERE loyalty_tier = 'GOLD'"
    ).fetchall())
    assert "GOLD" in tiers.values()  # P002 upgraded to GOLD on 2 July
    no_email = one(warehouse, "SELECT count(*) FROM silver.passengers WHERE email_token IS NULL")
    assert no_email[0] == 1  # P012 sent no email: kept, with no token


def test_age_band_replaces_date_of_birth(warehouse):
    bands = {row[0] for row in warehouse.execute(
        "SELECT DISTINCT age_band FROM silver.passengers").fetchall()}
    assert bands <= {"Under 25", "25-34", "35-44", "45-59", "60+", "UNKNOWN"}
    assert date(1990, 5, 12).isoformat() not in str(bands)
