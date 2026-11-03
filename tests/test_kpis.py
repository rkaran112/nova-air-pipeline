"""KPIs: every number below was worked out by hand from the fixture files.

Operated flights and their seats (VT-TAA has 10 seats, VT-TAB has 20):
  NV1001 1 Jul (TAA)  5 flown   NV1002 1 Jul (TAA) 1 flown   NV1005 1 Jul (TAA) 1 flown
  NV1001 2 Jul (TAA)  2 flown   NV1001 3 Jul (TAA) 1 flown
  NV1003 1 Jul (TAB)  3 flown   NV1009 1 Jul (TAB) 1 flown
  NV1004 1 Jul (TAB)  cancelled: its seats are not offered
Seats offered = 5 x 10 + 2 x 20 = 90. Passengers flown = 14.
"""

import pytest

from tests.conftest import one


def ratio(con, numerator, denominator, table, where="true"):
    return one(con, f"SELECT sum({numerator}) / sum({denominator}) FROM gold.{table} "
                    f"WHERE {where}")[0]


def test_load_factor_is_sum_over_sum(warehouse):
    assert ratio(warehouse, "passengers_flown", "seats_offered",
                 "mart_booking_daily") == pytest.approx(14 / 90)


def test_average_of_flight_percentages_would_be_wrong(warehouse):
    # Per flight: 5/10, 1/10, 1/10, 2/10, 1/10, 3/20, 1/20. Their plain average is
    # 0.1714, which overweights the small aircraft. The true load factor is 0.1556.
    average_of_percentages = one(warehouse, """
        SELECT avg(flown / f.seats_offered)
        FROM gold.fact_flight AS f
        JOIN (SELECT flight_key, count(*) FILTER (WHERE is_flown) AS flown
              FROM gold.fact_booking GROUP BY ALL) USING (flight_key)
        WHERE f.is_operated""")[0]
    assert average_of_percentages == pytest.approx(1.2 / 7)
    assert average_of_percentages != pytest.approx(14 / 90)


def test_economy_load_factor_uses_economy_seats_only(warehouse):
    # 12 economy passengers; economy seats 5 x 8 + 2 x 18 = 76.
    assert ratio(warehouse, "passengers_flown", "seats_offered", "mart_booking_daily",
                 "cabin = 'ECONOMY'") == pytest.approx(12 / 76)


def test_on_time_performance(warehouse):
    # Measurable: NV1001 1 Jul (25 min late after the correction), NV1002 (45 late),
    # NV1003 (5), NV1009 (0), NV1001 2 Jul (0), NV1001 3 Jul (0). NV1005 has no arrival.
    assert ratio(warehouse, "flights_on_time", "flights_measured",
                 "mart_flight_daily") == pytest.approx(4 / 6)


def test_cancellation_rate(warehouse):
    assert ratio(warehouse, "flights_cancelled", "flights_scheduled",
                 "mart_flight_daily") == pytest.approx(1 / 8)


def test_average_delay_for_both_populations(warehouse):
    all_measured = ratio(warehouse, "arrival_delay_minutes_total", "flights_measured",
                         "mart_flight_daily")
    delayed_only = ratio(warehouse, "delayed_minutes_total", "flights_delayed",
                         "mart_flight_daily")
    assert all_measured == pytest.approx((25 + 45 + 5 + 0 + 0 + 0) / 6)
    assert delayed_only == pytest.approx((25 + 45) / 2)


def test_revenue_and_ancillary_share(warehouse):
    fare, ancillary = one(warehouse, """
        SELECT sum(fare_revenue_inr), sum(ancillary_revenue_inr) FROM gold.mart_booking_daily""")
    # Fares of the 14 flown bookings plus B003 (a no-show keeps its fare); B017 was
    # refunded because its flight was cancelled. Ancillary: 500 + 850 + 300.
    assert fare == 122_950
    assert ancillary == 1_650
    assert ratio(warehouse, "ancillary_revenue_inr", "total_revenue_inr",
                 "mart_booking_daily") == pytest.approx(1650 / 124_600)


def test_ask_rpk_yield_and_rask(warehouse):
    distance = dict(warehouse.execute(
        "SELECT route_code, distance_km FROM gold.dim_route").fetchall())
    assert 830 < distance["BLR-BOM"] < 850  # Bengaluru to Mumbai is about 840 km
    ask = (10 * distance["BLR-BOM"] * 4      # NV1001 x3 and NV1005
           + 10 * distance["BOM-BLR"]        # NV1002
           + 20 * distance["BLR-DEL"]        # NV1003
           + 20 * distance["BLR-BOM"])       # NV1009
    rpk = 10 * distance["BLR-BOM"] + 1 * distance["BOM-BLR"] + 3 * distance["BLR-DEL"]
    assert one(warehouse, "SELECT sum(ask) FROM gold.mart_flight_daily")[0] == pytest.approx(ask)
    assert one(warehouse, "SELECT sum(ask) FROM gold.mart_booking_daily")[0] == pytest.approx(ask)
    assert one(warehouse, "SELECT sum(rpk) FROM gold.mart_booking_daily")[0] == pytest.approx(rpk)
    assert ratio(warehouse, "fare_revenue_inr", "rpk",
                 "mart_booking_daily") == pytest.approx(122_950 / rpk)
    assert ratio(warehouse, "total_revenue_inr", "ask",
                 "mart_booking_daily") == pytest.approx(124_600 / ask)
