"""Bronze: copy each new landing file into a table exactly as it arrived.

Every field is stored as text, so nothing can fail to load here; judging the values
is silver's job. Bronze rows are never updated or deleted. The file's rows and its
file_log entry are written in the same transaction (the runner's), so a file is
either fully loaded and logged, or not at all.
"""

import csv
import hashlib
import json
from datetime import datetime, timezone

from pipeline.checks import block, record_check
from pipeline.logs import log_event

META_COLUMNS = ("_source_file", "_batch_id", "_ingested_at", "_row_number")


def file_hash(path):
    """SHA-256 of the file's bytes: a fingerprint that changes if any byte changes."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_columns(path, file_format):
    """Column names in the order the file has them."""
    if file_format == "csv":
        with path.open(encoding="utf-8", newline="") as file:
            return next(csv.reader(file))
    columns = []
    for record in json.loads(path.read_text(encoding="utf-8")):
        columns.extend(key for key in record if key not in columns)
    return columns


def quoted(path):
    return "'" + path.as_posix().replace("'", "''") + "'"


def reader_sql(path, file_format, columns):
    """A DuckDB table function that reads the file with every field as text.

    The columns and CSV dialect are spelled out rather than auto-detected: we already
    know them from the header, and DuckDB's detection costs ~0.25 s per file.
    """
    types = ", ".join(f"'{name}': 'VARCHAR'" for name in columns)
    if file_format == "csv":
        return (f"read_csv({quoted(path)}, header = true, auto_detect = false, delim = ',', "
                f"quote = '\"', escape = '\"', columns = {{{types}}})")
    return f"read_json({quoted(path)}, format = 'array', columns = {{{types}}})"


def table_columns(con, table):
    rows = con.execute("SELECT column_name FROM information_schema.columns "
                       "WHERE table_schema = 'bronze' AND table_name = $table",
                       {"table": table}).fetchall()
    return [row[0] for row in rows]


def align_table(con, table, columns, batch_id, run_id):
    """Create the bronze table on first sight; afterwards add any new columns."""
    existing = table_columns(con, table)
    if not existing:
        definitions = ", ".join(f'"{name}" VARCHAR' for name in columns)
        con.execute(f"CREATE TABLE bronze.{table} ({definitions}, _source_file VARCHAR, "
                    "_batch_id VARCHAR, _ingested_at TIMESTAMP, _row_number BIGINT)")
        return
    for name in columns:
        if name not in existing:
            con.execute(f'ALTER TABLE bronze.{table} ADD COLUMN "{name}" VARCHAR')
            log_schema_change(con, run_id, batch_id, table, name, "added")
    for name in existing:
        if name not in columns and name not in META_COLUMNS:
            log_schema_change(con, run_id, batch_id, table, name, "missing")


def log_schema_change(con, run_id, batch_id, table, column, change):
    con.execute("INSERT INTO meta.schema_changes VALUES ($batch_id, $source, $column, $change, "
                "$run_id)", {"batch_id": batch_id, "source": table, "column": column,
                             "change": change, "run_id": run_id})
    record_check(con, run_id, batch_id, table, f"column_{change}:{column}", "warn", 0)
    log_event("schema_change", source=table, column=column, change=change, batch_id=batch_id)


def already_loaded(con, content_hash):
    return con.execute("SELECT 1 FROM meta.file_log WHERE content_hash = $hash",
                       {"hash": content_hash}).fetchone() is not None


def ingest_file(con, run_id, source, path, file_format, required_columns, file_date):
    """Load one file into bronze.<source>. Returns the rows loaded (0 if seen before)."""
    content_hash = file_hash(path)
    if already_loaded(con, content_hash):
        log_event("file_skipped", file=path.name, reason="same content already loaded")
        return 0

    batch_id = f"{source}-{file_date or 'ref'}-{content_hash[:8]}"
    columns = detect_columns(path, file_format)
    missing = [name for name in required_columns if name not in columns]
    if missing:
        block(con, run_id, batch_id, source, "required_column_missing", len(missing),
              f"{path.name} is missing required columns {missing}")

    ingested_at = datetime.now(timezone.utc).replace(tzinfo=None)
    align_table(con, source, columns, batch_id, run_id)
    # An INSERT returns the number of rows it wrote, so there is no need to count
    # them again by scanning the (ever-growing) bronze table.
    rows = con.execute(f"""
        INSERT INTO bronze.{source} BY NAME
        SELECT *, $file AS _source_file, $batch_id AS _batch_id,
               $ingested_at AS _ingested_at, row_number() OVER () AS _row_number
        FROM {reader_sql(path, file_format, columns)}""",
                       {"file": path.name, "batch_id": batch_id,
                        "ingested_at": ingested_at}).fetchone()[0]
    con.execute("INSERT INTO meta.file_log VALUES ($hash, $name, $source, $file_date, "
                "$batch_id, $rows, $run_id, $loaded_at)",
                {"hash": content_hash, "name": path.name, "source": source,
                 "file_date": file_date, "batch_id": batch_id, "rows": rows,
                 "run_id": run_id, "loaded_at": ingested_at})
    log_event("file_loaded", file=path.name, source=source, rows=rows, batch_id=batch_id)
    return rows


def files_to_ingest(landing_dir, config, day):
    """(source, path, format, required columns, file date) for reference files and,
    if a day is given, that day's daily files."""
    reference = config["reference"]
    found = []
    for name in reference["files"]:
        path = landing_dir / reference["folder"] / f"{name}.csv"
        if path.exists():
            found.append((name, path, "csv", (), None))
    if day is None:
        return found
    for source, spec in config["sources"].items():
        extension = "json" if spec["format"] == "json" else "csv"
        path = landing_dir / spec["folder"] / f"{source}_{day.isoformat()}.{extension}"
        if path.exists():
            found.append((source, path, spec["format"], spec["required_columns"], day))
        else:
            log_event("file_not_found", source=source, day=day.isoformat())
    return found


def ingest_day(con, settings, run_id, day):
    """Bronze step: load every new file for this day (and any changed reference file)."""
    rows_in = 0
    for source, path, file_format, required, file_date in files_to_ingest(
            settings.landing_dir, settings.config, day):
        rows_in += ingest_file(con, run_id, source, path, file_format, required, file_date)
    return {"rows_in": rows_in, "rows_out": rows_in}
