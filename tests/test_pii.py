"""Personal data: never raw beyond bronze, and never processed without a key."""

import csv

import duckdb
import pytest

from pipeline import run as run_module
from pipeline.pii import make_tokenizer
from pipeline.settings import MissingPiiKeyError, read_pii_key
from tests.conftest import FIXTURE_LANDING

PII_COLUMNS = {"passengers": ("passenger_id", "full_name", "email", "phone", "date_of_birth"),
               "bookings": ("passenger_id", "pnr")}


def raw_pii_values():
    """Every personal value in the fixture landing files."""
    values = set()
    for source, columns in PII_COLUMNS.items():
        for path in (FIXTURE_LANDING / source).glob("*.csv"):
            with path.open(newline="") as file:
                for row in csv.DictReader(file):
                    values.update(row[c] for c in columns if row[c])
    return values


def text_values_in(con, schemas):
    columns = con.execute("""
        SELECT table_schema, table_name, column_name FROM information_schema.columns
        WHERE table_schema IN (SELECT unnest($schemas)) AND data_type = 'VARCHAR'""",
                          {"schemas": list(schemas)}).fetchall()
    values = set()
    for schema, table, column in columns:
        rows = con.execute(f'SELECT DISTINCT "{column}" FROM {schema}.{table}').fetchall()
        values.update(str(row[0]) for row in rows if row[0] is not None)
    return values


def contains_any(texts, needles):
    return sorted(n for n in needles if any(n in text for text in texts))


def test_fixture_really_contains_pii(warehouse):
    assert "asha.fixture@example.com" in raw_pii_values()
    assert contains_any(text_values_in(warehouse, ["bronze"]), raw_pii_values())


def test_no_raw_pii_in_silver_gold_or_meta(warehouse):
    found = contains_any(text_values_in(warehouse, ["silver", "gold", "meta"]), raw_pii_values())
    assert found == []


def test_no_raw_pii_in_exported_files(warehouse, settings):
    con = duckdb.connect()
    texts = set()
    for path in settings.export_dir.rglob("*.parquet"):
        con.execute(f"CREATE OR REPLACE VIEW exported AS SELECT * FROM '{path.as_posix()}'")
        texts |= text_values_in(con, ["main"])
    for path in settings.export_dir.rglob("*.csv"):
        texts.add(path.read_text(encoding="utf-8"))
    assert texts
    assert contains_any(texts, raw_pii_values()) == []


def test_missing_key_stops_before_touching_data(tmp_path, monkeypatch):
    monkeypatch.delenv("NOVA_PII_KEY", raising=False)
    with pytest.raises(MissingPiiKeyError, match="NOVA_PII_KEY is not set"):
        read_pii_key(env_file=tmp_path / "no.env")


def test_short_key_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_PII_KEY", "too-short")
    with pytest.raises(MissingPiiKeyError, match="at least"):
        read_pii_key(env_file=tmp_path / "no.env")


def test_cli_exits_with_code_2_without_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("NOVA_PII_KEY", raising=False)
    real_load_settings = run_module.load_settings
    # Point the runner at an empty .env, so the developer's real key is not found.
    monkeypatch.setattr(run_module, "load_settings",
                        lambda data_dir: real_load_settings(data_dir, env_file=tmp_path / "no.env"))
    assert run_module.main(["--date", "2025-07-01", "--data-dir", str(tmp_path)]) == 2
    assert not (tmp_path / "warehouse").exists()


def test_tokens_are_keyed_and_deterministic():
    token_a = make_tokenizer("a" * 40)
    token_b = make_tokenizer("b" * 40)
    assert token_a("P001") == token_a("P001")
    assert token_a("P001") != token_b("P001")
    assert token_a("P001") != token_a("P002")
