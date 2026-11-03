"""Profile the landing files with plain SQL, before any pipeline code touches them.

    python -m scripts.profile_landing              # shape of every source
    python -m scripts.profile_landing --defects    # also count each planted defect

This is the first thing to do with an unseen dataset: row counts, columns, nulls,
odd formats. The --defects checks are written independently of the pipeline, and
are compared with data/generator_manifest.json to prove the generator planted what
it claims.
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb

FLIGHT_COLUMNS = ("flight_no", "flight_date", "origin", "destination", "sched_dep", "sched_arr",
                  "actual_dep", "actual_arr", "aircraft_reg", "status", "delay_code",
                  "updated_at")

# label, SQL that returns one number, manifest keys whose sum it should equal, note
DEFECT_CHECKS = (
    ("flights: exact duplicate rows",
     "SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM flights)) FROM flights",
     ("flight_exact_duplicate",), ""),
    ("flights: older versions in the same file",
     """SELECT count(*) - count(DISTINCT (file_date, std_no, flight_date))
               - (SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM flights))
                  FROM flights)
        FROM flights""",
     ("flight_older_version",), ""),
    ("flights: flight number variants",
     "SELECT count(*) FROM flights WHERE flight_no <> std_no AND std_no SIMILAR TO 'NV[0-9]+'",
     ("flight_no_variant",), ""),
    ("flights: corrupted flight numbers",
     "SELECT count(*) FROM flights WHERE flight_no LIKE '%?%'",
     ("flight_corrupted_flight_no_then_resent",), ""),
    ("flights: arrival given as time only, earlier than departure clock time",
     """SELECT count(*) FROM flights
        WHERE regexp_full_match(sched_arr, '\\d{2}:\\d{2}')
          AND sched_arr < strftime(to_ist(sched_dep), '%H:%M')""",
     ("flight_overnight_time_only_arrival",), "overnight legs that need a date roll-over"),
    ("flights: cancelled but with actual times",
     "SELECT count(*) FROM flights WHERE status = 'CANCELLED' AND actual_dep IS NOT NULL",
     ("flight_cancelled_with_actual_times",), ""),
    ("flights: operated but missing actual arrival",
     "SELECT count(*) FROM flights WHERE status = 'OPERATED' AND actual_arr IS NULL",
     ("flight_operated_missing_actual_times", "flight_older_version"),
     "older versions are pre-departure snapshots, so they have no actual times either"),
    ("flights: record sits in a later day's file",
     "SELECT count(*) FROM flights WHERE file_date <> flight_date",
     ("flight_arrives_late", "flight_corrected_next_day",
      "flight_corrupted_flight_no_then_resent", "flight_impossible_duration_then_resent"),
     "late arrivals plus next-day corrections and re-sends"),
    ("bookings: exact duplicate rows",
     "SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM bookings)) FROM bookings",
     ("booking_exact_duplicate",), ""),
    ("bookings: flight number variants",
     """SELECT count(*) FROM bookings
        WHERE flight_no <> std_no AND std_no SIMILAR TO 'NV[0-9]+'""",
     ("booking_flight_no_variant",), ""),
    ("bookings: corrupted flight numbers",
     "SELECT count(*) FROM bookings WHERE flight_no LIKE '%?%'",
     ("booking_corrupted_flight_no",), ""),
    ("bookings: flight number in the 9000s (never scheduled)",
     "SELECT count(*) FROM bookings WHERE std_no SIMILAR TO 'NV9[0-9]{3}'",
     ("booking_flight_never_exists",), ""),
    ("bookings: fare zero or negative",
     "SELECT count(*) FROM bookings WHERE try_cast(fare_amount AS DOUBLE) <= 0",
     ("booking_non_positive_fare",), ""),
    ("bookings: fare in USD",
     "SELECT count(*) FROM bookings WHERE currency = 'USD'",
     ("booking_usd_fare",), ""),
    ("bookings: a required field is empty",
     """SELECT count(*) FROM bookings
        WHERE booking_id IS NULL OR passenger_id IS NULL OR fare_amount IS NULL
           OR cabin IS NULL""",
     ("booking_missing_required",), ""),
    ("bookings: channel or ancillary amount empty",
     "SELECT count(*) FROM bookings WHERE channel IS NULL OR ancillary_amount IS NULL",
     ("booking_missing_optional",), ""),
    ("bookings: record sits in a later day's file",
     "SELECT count(*) FROM bookings WHERE file_date <> flight_date",
     ("booking_stale_version_resent_next_day",), "stale versions re-sent the next day"),
    ("passengers: passenger_id empty",
     "SELECT count(*) FROM passengers WHERE passenger_id IS NULL",
     ("passenger_missing_required",), ""),
    ("passengers: email or phone empty",
     "SELECT count(*) FROM passengers WHERE email IS NULL OR phone IS NULL",
     ("passenger_missing_optional",), ""),
)


def create_views(con, landing):
    """One view per source, with every field as text, plus the file it came from."""
    con.execute("""
        CREATE MACRO to_ist(ts) AS CASE
            WHEN ts LIKE '%Z' THEN strptime(ts, '%Y-%m-%dT%H:%M:%SZ') + INTERVAL 330 MINUTE
            WHEN ts LIKE '%+05:30' THEN strptime(left(ts, 19), '%Y-%m-%d %H:%M:%S')
            ELSE try_strptime(ts, '%d/%m/%Y %H:%M') END""")
    columns = ", ".join(f"'{c}': 'VARCHAR'" for c in FLIGHT_COLUMNS)
    con.execute(f"""
        CREATE VIEW flights AS
        SELECT *, regexp_extract(filename, '(\\d{{4}}-\\d{{2}}-\\d{{2}})', 1) AS file_date,
               upper(regexp_replace(flight_no, '[\\s-]', '', 'g')) AS std_no
        FROM read_json('{landing}/flights/*.json', format = 'array',
                       columns = {{{columns}}}, filename = true)""")
    for source in ("bookings", "passengers"):
        extra = ("upper(regexp_replace(flight_no, '[\\s-]', '', 'g')) AS std_no,"
                 if source == "bookings" else "")
        con.execute(f"""
            CREATE VIEW {source} AS
            SELECT *, {extra}
                   regexp_extract(filename, '(\\d{{4}}-\\d{{2}}-\\d{{2}})', 1) AS file_date
            FROM read_csv('{landing}/{source}/*.csv', all_varchar = true,
                          union_by_name = true, filename = true)""")


def print_shape(con):
    for source in ("flights", "bookings", "passengers"):
        rows, files = con.execute(
            f"SELECT count(*), count(DISTINCT filename) FROM {source}").fetchone()
        print(f"\n== {source}: {rows:,} rows in {files} files")
        summary = con.execute(f"""
            SELECT column_name, approx_unique, null_percentage, min
            FROM (SUMMARIZE {source})
            WHERE column_name NOT IN ('filename', 'file_date', 'std_no')""").fetchall()
        for name, unique, nulls, minimum in summary:
            print(f"  {name:<18} distinct~{unique:<9} null={float(nulls):5.2f}%  "
                  f"e.g. {str(minimum)[:30]}")
    first_promo = con.execute(
        "SELECT min(file_date) FROM bookings WHERE promo_code IS NOT NULL").fetchone()[0]
    print(f"\npromo_code first appears in the bookings file for {first_promo}")
    formats = con.execute("""
        SELECT CASE WHEN ts LIKE '%Z' THEN 'UTC with Z'
                    WHEN ts LIKE '%+05:30' THEN 'IST with +05:30'
                    WHEN regexp_full_match(ts, '\\d{2}/\\d{2}/\\d{4} \\d{2}:\\d{2}')
                         THEN 'DD/MM/YYYY HH:MM, no zone'
                    WHEN regexp_full_match(ts, '\\d{2}:\\d{2}') THEN 'time only'
                    ELSE 'other' END AS format, count(*)
        FROM (SELECT unnest([sched_dep, sched_arr, actual_dep, actual_arr, updated_at]) AS ts
              FROM flights)
        WHERE ts IS NOT NULL GROUP BY ALL ORDER BY 2 DESC""").fetchall()
    print("flight timestamp formats: " + ", ".join(f"{f}={n:,}" for f, n in formats))


def print_defects(con, manifest_path):
    counts = json.loads(manifest_path.read_text())["counts"]
    print("\n== planted defects: found by SQL vs generator manifest")
    all_match = True
    for label, sql, keys, note in DEFECT_CHECKS:
        found = con.execute(sql).fetchone()[0]
        expected = sum(counts.get(key, 0) for key in keys)
        status = "ok" if found == expected else "DIFFERENT"
        all_match = all_match and found == expected
        print(f"  {status:<9} {label:<72} found={found:<7} manifest={expected:<7} {note}")
    return all_match


def main(argv=None):
    parser = argparse.ArgumentParser(description="Profile the landing files.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--defects", action="store_true")
    args = parser.parse_args(argv)
    landing = (args.data_dir / "landing").as_posix()
    con = duckdb.connect()
    create_views(con, landing)
    print_shape(con)
    if args.defects and not print_defects(con, args.data_dir / "generator_manifest.json"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
