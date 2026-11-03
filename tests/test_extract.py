"""Extracting from MySQL and MongoDB must give back exactly the landing files that went in.

These tests need the two servers running and NOVA_MYSQL_PASSWORD set (see .env.example),
so each one is skipped when its server is not available. They use a throwaway database
called nova_source_test and never touch the real nova_source.
"""

import csv
from datetime import date

import pytest

from pipeline import extract, sources
from scripts import seed_sources
from tests.conftest import FIXTURE_LANDING

pytest.importorskip("pymysql")
pytest.importorskip("pymongo")

TEST_DATABASE = "nova_source_test"


def mysql_database_exists(server):
    with server.cursor() as cursor:
        cursor.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                       (TEST_DATABASE,))
        return cursor.fetchone() is not None


@pytest.fixture
def mysql_source(monkeypatch):
    monkeypatch.setenv("NOVA_MYSQL_DATABASE", TEST_DATABASE)
    try:
        server = sources.mysql_connection(use_database=False)
    except sources.SourceUnavailableError as error:
        pytest.skip(str(error))
    with server.cursor() as cursor:
        if mysql_database_exists(server):
            cursor.execute(f"DROP DATABASE {TEST_DATABASE}")
        cursor.execute(f"CREATE DATABASE {TEST_DATABASE}")
    yield
    with server.cursor() as cursor:
        cursor.execute(f"DROP DATABASE {TEST_DATABASE}")
    server.close()


@pytest.fixture
def mongo_source(monkeypatch):
    monkeypatch.setenv("NOVA_MONGO_DATABASE", TEST_DATABASE)
    try:
        client = sources.mongo_client()
    except sources.SourceUnavailableError as error:
        pytest.skip(str(error))
    client.drop_database(TEST_DATABASE)
    yield client
    client.drop_database(TEST_DATABASE)
    client.close()


def rows_of(path):
    """Header and rows as parsed values, so line endings do not matter."""
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.reader(file))


def assert_extract_matches_landing(tmp_path, source, extract_function):
    originals = sorted((FIXTURE_LANDING / source).glob(f"{source}_*.csv"))
    assert originals
    for original in originals:
        day = date.fromisoformat(original.stem.split("_")[-1])
        columns, rows = extract_function(day)
        copy = tmp_path / original.name
        extract.write_daily_csv(copy, columns, rows)
        assert rows_of(copy) == rows_of(original), original.name


def test_bookings_from_mysql_match_the_landing_files(mysql_source, tmp_path):
    inserted = seed_sources.seed_mysql(FIXTURE_LANDING)
    assert inserted > 0
    assert_extract_matches_landing(tmp_path, "bookings", extract.extract_bookings)


def test_seeding_mysql_twice_does_not_duplicate_rows(mysql_source, tmp_path):
    seed_sources.seed_mysql(FIXTURE_LANDING)
    seed_sources.seed_mysql(FIXTURE_LANDING)
    assert_extract_matches_landing(tmp_path, "bookings", extract.extract_bookings)


def test_passengers_from_mongodb_match_the_landing_files(mongo_source, tmp_path):
    inserted = seed_sources.seed_mongo(FIXTURE_LANDING)
    assert inserted > 0
    assert_extract_matches_landing(tmp_path, "passengers", extract.extract_passengers)


def test_passenger_documents_nest_email_and_phone_under_contact(mongo_source):
    seed_sources.seed_mongo(FIXTURE_LANDING)
    collection = mongo_source[TEST_DATABASE][sources.PASSENGERS_COLLECTION]
    document = collection.find_one({"passenger_id": "P001"})
    assert document["contact"] == {"email": "asha.fixture@example.com", "phone": "+91 9000000001"}
    assert "email" not in document


def test_seeding_mongodb_twice_does_not_duplicate_documents(mongo_source, tmp_path):
    seed_sources.seed_mongo(FIXTURE_LANDING)
    seed_sources.seed_mongo(FIXTURE_LANDING)
    assert_extract_matches_landing(tmp_path, "passengers", extract.extract_passengers)
