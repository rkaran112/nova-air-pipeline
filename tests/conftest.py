"""Shared test setup: a fresh warehouse built from the small hand-written fixtures.

The fixture files in tests/fixtures/landing hold one example of every defect, so
each expected number in the tests can be checked by reading those files.
"""

import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from pipeline.run import run_pipeline
from pipeline.settings import Settings, load_config

FIXTURE_LANDING = Path(__file__).parent / "fixtures" / "landing"
FIXTURE_DAYS = (date(2025, 7, 1), date(2025, 7, 2), date(2025, 7, 3))
# A test-only key: long enough to pass the length check, and never used for real data.
TEST_PII_KEY = "test-only-key-" + "0123456789" * 4


def fixture_config():
    config = load_config()
    # The fixtures pack every defect into a few rows, so a quarter of day one's
    # bookings are rejected on purpose. Real files stay at the 20% limit.
    config["thresholds"]["quarantine_block_rate"] = 0.5
    return config


def make_settings(data_dir, config=None, pii_key=TEST_PII_KEY):
    landing = data_dir / "landing"
    if not landing.exists():
        shutil.copytree(FIXTURE_LANDING, landing)
    return Settings(data_dir=data_dir, pii_key=pii_key, config=config or fixture_config())


def fingerprint(con, schemas=("silver", "gold")):
    """Row count and content hash of every table in the given schemas.
    Two warehouses with equal fingerprints hold exactly the same data."""
    tables = con.execute("""
        SELECT table_schema || '.' || table_name FROM information_schema.tables
        WHERE table_schema IN (SELECT unnest($schemas)) ORDER BY 1""",
                         {"schemas": list(schemas)}).fetchall()
    result = {}
    for (table,) in tables:
        result[table] = con.execute(f"""
            SELECT count(*), md5(coalesce(string_agg(CAST(t AS VARCHAR), '|'
                                          ORDER BY CAST(t AS VARCHAR)), ''))
            FROM {table} AS t""").fetchone()
    return result


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def warehouse(settings):
    """Run all three fixture days, then open the warehouse read-only."""
    run_pipeline(settings, list(FIXTURE_DAYS))
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    yield con
    con.close()


def one(con, sql, params=None):
    return con.execute(sql, params or {}).fetchone()


def rows_as_dicts(con, sql, params=None):
    """Query results as plain dicts (no pandas, so a missing value is None, not NaT)."""
    cursor = con.execute(sql, params or {})
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]
