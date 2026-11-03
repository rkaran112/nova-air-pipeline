"""Fill the MySQL and MongoDB source systems from the generator's landing files.

    python -m scripts.seed_sources                      # every day in data/landing
    python -m scripts.seed_sources --start 2025-07-01 --end 2025-07-07

The data is synthetic, so there is no real reservation system to read from. This script
plays that part: bookings go into a MySQL table and passengers into MongoDB documents,
as text exactly as delivered, so the planted defects survive. Running it again replaces
each day's rows instead of adding to them.
"""

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path

from pipeline.logs import configure_logging, log_event
from pipeline.settings import REPO_ROOT
from pipeline.sources import (
    BOOKINGS_TABLE,
    PASSENGERS_COLLECTION,
    SourceUnavailableError,
    mongo_client,
    mongo_database_name,
    mysql_connection,
    passenger_to_document,
)

COLUMN_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def daily_files(landing_dir, source, start, end):
    """(day, path) for each of the source's daily files in the date range, oldest first."""
    found = []
    for path in sorted((landing_dir / source).glob(f"{source}_*.csv")):
        day = date.fromisoformat(path.stem.split("_")[-1])
        if (start is None or day >= start) and (end is None or day <= end):
            found.append((day, path))
    return found


def read_csv_file(path):
    """(header, rows) with every value kept as the text it was delivered as."""
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.reader(file)
        header = next(reader)
        return header, list(reader)


def mysql_column_names(connection, table):
    with connection.cursor() as cursor:
        cursor.execute("SELECT column_name FROM information_schema.columns "
                       "WHERE table_schema = DATABASE() AND table_name = %s", (table,))
        return [row[0] for row in cursor.fetchall()]


def prepare_bookings_table(connection, header):
    """Create the table on first use; afterwards add any column the file brings that the
    table does not have yet, as a real source system would when its schema changes."""
    for name in header:
        if not COLUMN_NAME.match(name):
            raise ValueError(f"unexpected column name in file header: {name!r}")
    existing = mysql_column_names(connection, BOOKINGS_TABLE)
    with connection.cursor() as cursor:
        if not existing:
            definitions = ", ".join(f"`{name}` VARCHAR(255) NULL" for name in header)
            cursor.execute(f"CREATE TABLE {BOOKINGS_TABLE} (id BIGINT AUTO_INCREMENT PRIMARY KEY, "
                           f"file_date DATE NOT NULL, {definitions}, KEY idx_file_date "
                           "(file_date)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
            return
        for name in header:
            if name not in existing:
                cursor.execute(
                    f"ALTER TABLE {BOOKINGS_TABLE} ADD COLUMN `{name}` VARCHAR(255) NULL")


def seed_mysql(landing_dir, start=None, end=None):
    """Load the bookings files into MySQL. Returns the number of rows inserted."""
    connection = mysql_connection()
    total = 0
    try:
        for day, path in daily_files(landing_dir, "bookings", start, end):
            header, rows = read_csv_file(path)
            prepare_bookings_table(connection, header)
            padded = [row + [None] * (len(header) - len(row)) for row in rows]
            names = ", ".join(f"`{name}`" for name in header)
            marks = ", ".join(["%s"] * (len(header) + 1))
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {BOOKINGS_TABLE} WHERE file_date = %s", (day,))
                cursor.executemany(
                    f"INSERT INTO {BOOKINGS_TABLE} (file_date, {names}) VALUES ({marks})",
                    [[day] + row for row in padded])
            connection.commit()
            total += len(rows)
            log_event("seeded", system="mysql", day=day.isoformat(), rows=len(rows))
    finally:
        connection.close()
    return total


def seed_mongo(landing_dir, start=None, end=None):
    """Load the passengers files into MongoDB. Returns the number of documents inserted."""
    client = mongo_client()
    total = 0
    try:
        collection = client[mongo_database_name()][PASSENGERS_COLLECTION]
        collection.create_index("file_date")
        for day, path in daily_files(landing_dir, "passengers", start, end):
            header, rows = read_csv_file(path)
            documents = [passenger_to_document(dict(zip(header, row)), day, number)
                         for number, row in enumerate(rows, start=1)]
            collection.delete_many({"file_date": day.isoformat()})
            if documents:
                collection.insert_many(documents)
            total += len(documents)
            log_event("seeded", system="mongodb", day=day.isoformat(), rows=len(documents))
    finally:
        client.close()
    return total


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Fill the MySQL and MongoDB source systems.")
    parser.add_argument("--landing-dir", help="defaults to data/landing in the repo")
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    return parser.parse_args(argv)


def main(argv=None):
    configure_logging()
    args = parse_args(argv)
    landing_dir = Path(args.landing_dir) if args.landing_dir else REPO_ROOT / "data" / "landing"
    try:
        bookings = seed_mysql(landing_dir, args.start, args.end)
        passengers = seed_mongo(landing_dir, args.start, args.end)
    except SourceUnavailableError as error:
        log_event("source_unavailable", error=str(error))
        return 2
    log_event("seed_finished", bookings=bookings, passengers=passengers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
