"""Extract: read one day from the source systems and write the daily landing files.

    python -m pipeline.extract --date 2025-07-01
    python -m pipeline.extract --start 2025-07-01 --end 2025-07-31

Bookings come from MySQL and passenger profiles from MongoDB (see pipeline/sources.py).
The files written here are exactly the files the generator writes, so bronze, silver and
gold do not change. Flights and the reference files still arrive as files.

Exit codes: 0 success, 2 a source system cannot be reached.
"""

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

from pipeline.logs import configure_logging, log_event
from pipeline.run import days_between
from pipeline.settings import REPO_ROOT
from pipeline.sources import (
    BOOKING_EXTRA_COLUMNS,
    BOOKINGS_TABLE,
    PASSENGER_COLUMNS,
    PASSENGERS_COLLECTION,
    SourceUnavailableError,
    document_to_passenger,
    mongo_client,
    mongo_database_name,
    mysql_connection,
)


def extract_bookings(day):
    """The booking rows delivered on this day, in the order they were stored."""
    connection = mysql_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {BOOKINGS_TABLE} WHERE file_date = %s ORDER BY id",
                           (day,))
            names = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
    finally:
        connection.close()
    # A column that is NULL on every row of the day did not exist yet in that day's file
    # (it was added to the table later), so it is left out, as in the original file.
    keep = [i for i, name in enumerate(names)
            if name not in BOOKING_EXTRA_COLUMNS and any(row[i] is not None for row in rows)]
    return ([names[i] for i in keep],
            [["" if row[i] is None else row[i] for i in keep] for row in rows])


def extract_passengers(day):
    """The passenger documents delivered on this day, flattened to the file's columns."""
    client = mongo_client()
    try:
        collection = client[mongo_database_name()][PASSENGERS_COLLECTION]
        documents = list(collection.find({"file_date": day.isoformat()}).sort("row_number", 1))
    finally:
        client.close()
    rows = []
    for document in documents:
        passenger = document_to_passenger(document)
        rows.append(["" if passenger[name] is None else passenger[name]
                     for name in PASSENGER_COLUMNS])
    return list(PASSENGER_COLUMNS), rows


def write_daily_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(rows)


def extract_day(day, landing_dir):
    """Write bookings_<day>.csv and passengers_<day>.csv; a source with no rows that
    day writes no file, exactly like a day on which the generator wrote none."""
    for source, extract in (("bookings", extract_bookings), ("passengers", extract_passengers)):
        columns, rows = extract(day)
        if not rows:
            log_event("extract_empty", source=source, day=day.isoformat())
            continue
        path = landing_dir / source / f"{source}_{day.isoformat()}.csv"
        write_daily_csv(path, columns, rows)
        log_event("extract_written", source=source, day=day.isoformat(), rows=len(rows),
                  file=path.name)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Extract daily files from MySQL and MongoDB.")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--data-dir", help="defaults to data/ in the repo")
    args = parser.parse_args(argv)
    if args.date and (args.start or args.end):
        parser.error("use --date, or --start with --end, not both")
    if bool(args.start) != bool(args.end):
        parser.error("--start and --end go together")
    if not (args.date or args.start):
        parser.error("give --date, or --start with --end")
    if args.start and args.start > args.end:
        parser.error("--start must not be after --end")
    return args


def main(argv=None):
    configure_logging()
    args = parse_args(argv)
    data_dir = Path(args.data_dir) if args.data_dir else REPO_ROOT / "data"
    days = [args.date] if args.date else days_between(args.start, args.end)
    try:
        for day in days:
            extract_day(day, data_dir / "landing")
    except SourceUnavailableError as error:
        log_event("source_unavailable", error=str(error))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
