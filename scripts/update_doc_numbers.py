"""Fill the numbers in the docs from the latest pipeline run, so none are typed by hand.

    python -m scripts.update_doc_numbers

Docs mark each generated block like this, and only the text between the markers
is replaced:

    <!-- numbers:headline-kpis -->
    ...generated...
    <!-- /numbers -->
"""

import json
import re
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent
EXPORTS = REPO / "data" / "exports"
MANIFEST = REPO / "data" / "generator_manifest.json"
DOCS = ("README.md", "docs/DATA_QUALITY.md", "docs/GENERATOR_ANSWER_KEY.md", "docs/RESUME.md")
BLOCK = re.compile(r"(<!-- numbers:([a-z-]+) -->\n).*?(<!-- /numbers -->)", re.S)

# defect number, defect, how it is detected, what happens, generator keys, pipeline checks
DEFECTS = (
    (1, "Exact duplicate rows", "Same JSON fingerprint for the whole row",
     "Keep the first copy, count the rest",
     ("flight_exact_duplicate", "booking_exact_duplicate", "passenger_exact_duplicate"),
     ("exact_duplicate_removed",)),
    (2, "Several versions of one record", "Same business key; compare updated_at",
     "Keep the latest; an older version never overwrites a newer one",
     ("flight_older_version", "booking_older_version", "passenger_older_version",
      "booking_stale_version_resent_next_day"), ("older_version_ignored",)),
    (3, "Flight number variants", "Upper-case and strip spaces and hyphens",
     "Standardise to NV1234", ("flight_no_variant", "booking_flight_no_variant"),
     ("flight_no_standardised",)),
    (4, "Corrupted flight numbers", "Fails the NV + 3-4 digits pattern",
     "Quarantine: INVALID_FLIGHT_NO",
     ("flight_corrupted_flight_no_then_resent", "booking_corrupted_flight_no"),
     ("quarantined:INVALID_FLIGHT_NO",)),
    (5, "Mixed timestamp formats (UTC and IST)", "Try the three known formats in order",
     "Store UTC; derive IST in gold; unreadable -> BAD_TIMESTAMP",
     ("timestamp_written_as_utc", "timestamp_written_day_first_no_zone"),
     ("quarantined:BAD_TIMESTAMP",)),
    (6, "Overnight flights with time-only arrival", "Arrival text is HH:MM",
     "Attach the departure date; add a day if it would be before departure",
     ("flight_overnight_time_only_arrival",), ("arrival_time_only_resolved",)),
    (7, "Arrival before departure / impossible duration", "Flight time <= 0 or > 2x schedule",
     "Quarantine: IMPOSSIBLE_DURATION", ("flight_impossible_duration_then_resent",),
     ("quarantined:IMPOSSIBLE_DURATION",)),
    (8, "Status contradicts actual times", "CANCELLED with times / OPERATED without",
     "Cancelled: clear times, flag. Operated: keep, flag, leave out of punctuality",
     ("flight_cancelled_with_actual_times", "flight_operated_missing_actual_times"),
     ("cancelled_actual_times_cleared", "operated_without_actual_times")),
    (9, "Zero or negative fares", "fare_amount <= 0", "Quarantine: NON_POSITIVE_FARE",
     ("booking_non_positive_fare",), ("quarantined:NON_POSITIVE_FARE",)),
    (10, "USD fares in an INR column", "currency = 'USD'",
     "Convert at that booking day's rate from the FX table", ("booking_usd_fare",),
     ("usd_fare_converted",)),
    (11, "Fare outliers", "Beyond 3 x IQR of the same route and cabin",
     "Flag in gold, keep the row", ("booking_fare_outlier",), ("gold:is_fare_outlier",)),
    (12, "Booking arrives before its flight", "No matching flight in silver yet",
     "Quarantine as waiting; retried every run; released when the flight arrives",
     ("flight_arrives_late",), ("late_booking_released",)),
    (13, "Booking for a flight that never exists", "Still no flight 3 days after its date",
     "Rejected for good: NO_VALID_FLIGHT", ("booking_flight_never_exists",),
     ("late_booking_given_up",)),
    (14, "Missing values", "Required vs optional fields",
     "Required: quarantine. Optional: documented default",
     ("booking_missing_required", "passenger_missing_required"),
     ("quarantined:MISSING_REQUIRED_FIELD",)),
    (15, "New promo_code column appears", "File header has a column bronze lacks",
     "Add the column, log it in meta.schema_changes, warn", (), ("meta:schema_added",)),
    (16, "Corrected flight record a day late", "Same flight key, newer updated_at",
     "Update the silver row in place; no duplicate", ("flight_corrected_next_day",), ()),
)


def connect():
    con = duckdb.connect()
    for folder in ("gold", "meta"):
        for path in (EXPORTS / folder).glob("*.parquet"):
            con.execute(f"CREATE VIEW {path.stem} AS SELECT * FROM '{path.as_posix()}'")
    return con


def fmt(value):
    return f"{int(value):,}"


def found_count(con, check):
    if check == "meta:schema_added":
        sql = "SELECT count(*) FROM schema_changes WHERE change = 'added'"
        return con.execute(sql).fetchone()[0]
    if check == "gold:is_fare_outlier":
        return con.execute("SELECT count(*) FROM fact_booking WHERE is_fare_outlier").fetchone()[0]
    return con.execute("SELECT coalesce(sum(row_count), 0) FROM dq_results "
                       "WHERE regexp_replace(check_name, ':.*', '') = $c OR check_name = $c",
                       {"c": check}).fetchone()[0]


def data_quality_table(con, manifest):
    rows = ["| # | Defect | Detection | Action | Planted by generator | Found by pipeline |",
            "|---|---|---|---|---|---|"]
    for number, name, detection, action, planted_keys, checks in DEFECTS:
        planted = sum(manifest["counts"].get(k, 0) for k in planted_keys)
        found = sum(found_count(con, c) for c in checks)
        planted_text = fmt(planted) if planted_keys else "from 1 Oct"
        found_text = fmt(found) if checks else "see note"
        rows.append(f"| {number} | {name} | {detection} | {action} | {planted_text} | "
                    f"{found_text} |")
    return "\n".join(rows)


def reconciliation_table(con):
    rows = con.execute("""
        SELECT source, count(*), sum(rows_in), sum(rows_loaded), sum(rows_exact_duplicate),
               sum(rows_older_version), sum(rows_quarantined), count(*) FILTER (WHERE balanced)
        FROM reconciliation GROUP BY source ORDER BY source""").fetchall()
    lines = ["| Source | Batches | Rows in | Loaded | Exact duplicates | Older versions | "
             "Quarantined | Batches balanced |", "|---|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append("| " + " | ".join([row[0]] + [fmt(v) for v in row[1:]]) + " |")
    return "\n".join(lines)


def quarantine_table(con):
    rows = con.execute("SELECT source, reason_code, status, row_count FROM quarantine_summary "
                       "ORDER BY source, row_count DESC").fetchall()
    lines = ["| Source | Reason | Status | Rows |", "|---|---|---|---|"]
    lines += [f"| {s} | {r} | {st} | {fmt(n)} |" for s, r, st, n in rows]
    return "\n".join(lines)


def headline_kpis(con):
    booking = con.execute("""
        SELECT sum(total_revenue_inr), sum(passengers_flown),
               sum(passengers_flown) / sum(seats_offered),
               sum(total_revenue_inr) / sum(ask), sum(fare_revenue_inr) / sum(rpk),
               sum(ancillary_revenue_inr) / sum(total_revenue_inr)
        FROM mart_booking_daily""").fetchone()
    flight = con.execute("""
        SELECT sum(flights_scheduled), sum(flights_on_time) / sum(flights_measured),
               sum(flights_cancelled) / sum(flights_scheduled),
               sum(arrival_delay_minutes_total) / sum(flights_measured),
               sum(delayed_minutes_total) / sum(flights_delayed)
        FROM mart_flight_daily""").fetchone()
    return "\n".join([
        "| KPI | Value (1 Jul - 31 Dec 2025, small profile, seed 42) |", "|---|---|",
        f"| Flights scheduled | {fmt(flight[0])} |",
        f"| Passengers flown | {fmt(booking[1])} |",
        f"| Revenue (fares + ancillary) | ₹{float(booking[0]) / 1e7:,.1f} crore |",
        f"| Load factor | {booking[2]:.1%} |",
        f"| On-time performance | {flight[1]:.1%} |",
        f"| Cancellation rate | {flight[2]:.2%} |",
        f"| Average arrival delay, all measured flights | {flight[3]:.1f} min |",
        f"| Average arrival delay, delayed flights only | {flight[4]:.1f} min |",
        f"| RASK | ₹{booking[3]:.2f} per seat-km |",
        f"| Yield | ₹{booking[4]:.2f} per passenger-km |",
        f"| Ancillary share of revenue | {booking[5]:.1%} |",
    ])


def run_facts(con, manifest):
    batches, balanced = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE balanced) FROM reconciliation").fetchone()
    rows_in = con.execute("SELECT sum(rows_in) FROM reconciliation").fetchone()[0]
    quarantined = con.execute("SELECT sum(row_count) FROM quarantine_summary").fetchone()[0]
    released = con.execute("SELECT coalesce(sum(row_count), 0) FROM quarantine_summary "
                           "WHERE status = 'released'").fetchone()[0]
    return "\n".join([
        f"- Source rows processed: **{fmt(rows_in)}** across **{fmt(batches)}** daily batches "
        f"({fmt(manifest['counts']['rows_written_bookings'])} booking rows).",
        f"- Batches that reconciled exactly: **{fmt(balanced)} of {fmt(batches)}**.",
        f"- Rows held in quarantine: **{fmt(quarantined)}**, of which **{fmt(released)}** "
        "were late bookings later released automatically.",
    ])


def pattern_evidence(con):
    def table(sql, headers):
        rows = con.execute(sql).fetchall()
        lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
        lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in rows]
        return "\n".join(lines)

    return "\n\n".join([
        "Average departure delay (minutes) by month, flights leaving BOM vs elsewhere:\n\n"
        + table("""SELECT d.month_label, round(avg(greatest(departure_delay_minutes, 0))
                          FILTER (WHERE r.origin = 'BOM'), 1),
                          round(avg(greatest(departure_delay_minutes, 0))
                          FILTER (WHERE r.origin <> 'BOM'), 1)
                   FROM fact_flight f JOIN dim_route r USING (route_key)
                   JOIN dim_date d USING (date_key) WHERE is_operated
                   GROUP BY d.month, d.month_label ORDER BY d.month""",
                ["Month", "From BOM", "From elsewhere"]),
        "Average departure delay (minutes) of DEL departures before 10:00 IST, by month:\n\n"
        + table("""SELECT d.month_label, round(avg(greatest(departure_delay_minutes, 0)), 1)
                   FROM fact_flight f JOIN dim_route r USING (route_key)
                   JOIN dim_date d USING (date_key)
                   WHERE is_operated AND r.origin = 'DEL' AND sched_dep_hour_ist < 10
                   GROUP BY d.month, d.month_label ORDER BY d.month""",
                ["Month", "DEL morning delay"]),
        "Average departure delay (minutes) by the aircraft's leg of the day:\n\n"
        + table("""SELECT aircraft_leg_number, round(avg(greatest(departure_delay_minutes, 0)), 1),
                          round(avg(CAST(is_on_time AS INTEGER)) * 100, 1)
                   FROM fact_flight WHERE is_operated GROUP BY 1 ORDER BY 1""",
                ["Leg", "Avg delay", "On time %"]),
        "Routes with the lowest RASK and the lowest load factor:\n\n"
        + table("""SELECT r.route_code,
                          round(sum(passengers_flown) / sum(seats_offered) * 100, 1),
                          round(sum(total_revenue_inr) / sum(ask), 2)
                   FROM mart_booking_daily m JOIN dim_route r USING (route_key)
                   GROUP BY 1 ORDER BY 3 LIMIT 3""", ["Route", "Load factor %", "RASK ₹"])
        + "\n\n"
        + table("""SELECT r.route_code,
                          round(sum(passengers_flown) / sum(seats_offered) * 100, 1)
                   FROM mart_booking_daily m JOIN dim_route r USING (route_key)
                   GROUP BY 1 ORDER BY 2 LIMIT 3""", ["Route", "Load factor %"]),
        "Revenue (₹ crore) by full week, around Diwali (20 Oct 2025):\n\n"
        + table("""SELECT CAST(date_trunc('week', d.calendar_date) AS DATE),
                          round(sum(total_revenue_inr) / 1e7, 2)
                   FROM mart_booking_daily m JOIN dim_date d USING (date_key)
                   WHERE d.calendar_date BETWEEN DATE '2025-09-29' AND DATE '2025-11-09'
                   GROUP BY 1 ORDER BY 1""", ["Week starting", "Revenue ₹ cr"]),
    ])


def main():
    if not (EXPORTS / "gold").exists():
        print("No exports: run the pipeline first.")
        return 1
    con = connect()
    manifest = json.loads(MANIFEST.read_text())
    blocks = {
        "headline-kpis": headline_kpis(con),
        "run-facts": run_facts(con, manifest),
        "data-quality": data_quality_table(con, manifest),
        "reconciliation": reconciliation_table(con),
        "quarantine": quarantine_table(con),
        "pattern-evidence": pattern_evidence(con),
    }
    for doc in DOCS:
        path = REPO / doc
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        updated = BLOCK.sub(lambda m: m.group(1) + blocks[m.group(2)] + "\n" + m.group(3), text)
        path.write_text(updated, encoding="utf-8")
        print(f"updated {doc}: {len(BLOCK.findall(text))} block(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
