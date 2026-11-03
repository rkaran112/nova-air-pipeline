"""The dashboard's queries run on the exports and agree with the hand-worked KPIs."""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))
import queries  # noqa: E402  (the dashboard imports its modules from its own folder)

ALL = queries.Filters(date(2025, 7, 1), date(2025, 7, 3), (), "ALL")


@pytest.fixture
def con(warehouse, settings):
    return queries.connect(settings.export_dir)


def test_headline_kpis_match_the_hand_calculation(con):
    kpis = queries.headline_kpis(con, ALL)
    assert kpis["load_factor"] == pytest.approx(14 / 90)
    assert kpis["on_time"] == pytest.approx(4 / 6)
    assert kpis["cancellation"] == pytest.approx(1 / 8)
    assert kpis["revenue"] == 124_600


def test_filters_narrow_the_numbers(con):
    plus_only = queries.Filters(ALL.start, ALL.end, (), "PLUS")
    assert queries.headline_kpis(con, plus_only)["passengers"] == 2
    one_route = queries.Filters(ALL.start, ALL.end, ("BLR-DEL",), "ALL")
    assert queries.headline_kpis(con, one_route)["passengers"] == 3


def test_every_page_query_runs(con):
    for function in (queries.monthly_trends, queries.weekly_revenue, queries.route_performance,
                     queries.delay_causes, queries.delay_by_airport_hour,
                     queries.delay_by_airport_month, queries.delay_by_leg):
        assert function(con, ALL) is not None
    for function in (queries.last_run, queries.reconciliation_summary, queries.layer_counts,
                     queries.quarantine_reasons, queries.check_results):
        assert not function(con).empty
    assert queries.fare_outliers(con, ALL)["outliers"] == 1
