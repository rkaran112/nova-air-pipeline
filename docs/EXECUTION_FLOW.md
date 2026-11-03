# Execution flow: three rows, followed all the way

This follows three real rows from the test fixtures (`tests/fixtures/landing`) through
every file, function, table and transformation. Every value below was read from a real
run of the fixtures. You can reproduce them yourself:

```bash
python -m pytest tests/test_silver_bookings.py -q
```

or run the fixtures into a scratch folder and query it (see "Try it" at the end).

The three rows:

1. **A clean booking:** `B002`, passenger `P002`, on flight NV1001 on 1 July 2025.
2. **A duplicate:** `B001`, which appears twice, identically, in the same file.
3. **An overnight flight:** `" NV 1003 "`, Bengaluru to Delhi, leaving 23:30 and
   arriving at "02:05".

---

## 0. The command

```bash
python -m pipeline.run --start 2025-07-01 --end 2025-07-03
```

- `pipeline/run.py: main()` parses the arguments and calls `load_settings()`
  (`pipeline/settings.py`). That reads `config/pipeline.toml` and the `NOVA_PII_KEY`
  from `.env`. With no key it stops here with exit code 2, before any data is touched.
- `run_pipeline()` opens the DuckDB file (`pipeline/db.py: connect()`), runs
  `sql/meta/create_tables.sql`, registers `pii_token()` (`pipeline/pii.py`), and loops
  over the days. For each day it runs `ingest_bronze`, then `load_silver`. Each one goes
  through `run_step()`, which wraps it in one transaction and writes a row to
  `meta.pipeline_runs`.

---

## 1. Bronze: `pipeline/bronze.py: ingest_day()`

For 1 July, `files_to_ingest()` finds the four reference files and
`flights_2025-07-01.json`, `passengers_2025-07-01.csv` and `bookings_2025-07-01.csv`.

For `bookings_2025-07-01.csv`, `ingest_file()`:

1. `file_hash()` computes SHA-256 of the bytes. `already_loaded()` checks
   `meta.file_log`: the hash is new, so we continue.
2. `batch_id` = `bookings-2025-07-01-15d184ba` (source, file date, first 8 characters of
   the hash). It is the same on every machine, every run.
3. `detect_columns()` reads the header. All required columns from `pipeline.toml` are
   present, so nothing blocks.
4. `align_table()` creates `bronze.bookings` on first sight, every column `VARCHAR`.
5. One `INSERT ... BY NAME SELECT ... FROM read_csv(...)` loads all 21 rows as text and
   adds `_source_file`, `_batch_id`, `_ingested_at`, `_row_number`.
6. A row goes into `meta.file_log` (hash, name, batch, 21 rows).

After this step, bronze holds our rows exactly as sent:

| booking_id | pnr | passenger_id | flight_no | fare_amount | booked_at | _row_number |
|---|---|---|---|---|---|---|
| B001 | PNRAA1 | P001 | NV1001 | 3000.00 | 2025-06-20 10:00:00+05:30 | 1 |
| B001 | PNRAA1 | P001 | NV1001 | 3000.00 | 2025-06-20 10:00:00+05:30 | 2 |
| B002 | PNRAA2 | P002 | NV1001 | 3100.00 | 2025-06-20T04:30:00Z | 3 |

And the overnight flight from `flights_2025-07-01.json` (row 5):

| flight_no | sched_dep | sched_arr | actual_dep | actual_arr |
|---|---|---|---|---|
| `" NV 1003 "` | 01/07/2025 23:30 | 02:05 | 01/07/2025 23:35 | 02:10 |

Notice that nothing was judged: the spaces, the time-only arrival and the PII are all
still there. Running the same day again finds the same hashes and loads nothing.

---

## 2. Silver: `pipeline/silver.py: load_silver()`

`prepare()` runs `sql/silver/00_macros.sql` (the shared helper functions),
`create_tables.sql`, and `reference.sql` (typed airports, aircraft, delay codes, FX
rates). `pending_batches()` lists batches in `meta.file_log` that have no row in
`meta.reconciliation` yet, oldest first: flights, then passengers, then bookings.
Flights go first so that bookings can find them.

### 2a. The overnight flight: `flights_check.sql`, then `flights_merge.sql`

`flights_check.sql` builds a temp table `checked_rows`, one CTE at a time:

| CTE | What happens to " NV 1003 " |
|---|---|
| `batch_rows` | Selects the batch's rows from `bronze.flights` |
| `with_record` | Packs the row into JSON (`row_json()`): its fingerprint, and what quarantine would keep |
| `numbered_copies` | `row_number()` over identical fingerprints: `copy_number = 1` (it is unique) |
| `parsed` | `standard_flight_no()` gives `NV1003`. `parse_utc('01/07/2025 23:30')`: no zone, so IST, minus 5h30 = `2025-07-01 18:00 UTC` |
| `with_arrivals` | `arrival_utc('02:05', 18:00 UTC)`: the departure in IST is 1 July 23:30; 1 July 02:05 would be *before* that, so the arrival is 2 July 02:05 IST = `2025-07-01 20:35 UTC` |
| final `CASE` | Required fields present, `NV1003` matches the pattern, every time parsed, status valid, route known, 155 minutes is within 20-360, actual block 155 minutes is under 2x schedule: `reject_reason` is NULL |

`quarantine_rejects.sql` inserts only rows with a reason, so this row is not touched.
`flights_merge.sql` ranks versions by `updated_at` (there is one), applies the status
rule (operated, so actual times are kept) and `MERGE`s it into `silver.flights`:

| flight_no | sched_dep_utc | sched_arr_utc | actual_dep_utc | actual_arr_utc |
|---|---|---|---|---|
| NV1003 | 2025-07-01 18:00 | 2025-07-01 20:35 | 2025-07-01 18:05 | 2025-07-01 20:40 |

This is the bug from the old pipeline, fixed: the overnight flight is **kept**, with a
155-minute duration. `tests/test_silver_flights.py` checks exactly this.

### 2b. The bookings: `bookings_check.sql`

| CTE | B001 (both copies) | B002 |
|---|---|---|
| `batch_rows` | `pii_token()` replaces `passenger_id` and `pnr` with HMAC tokens straight away | same |
| `with_record`, `numbered_copies` | Both rows have the same JSON, so row 1 gets `copy_number = 1` and row 2 gets `copy_number = 2` | `copy_number = 1` |
| `all_candidates` | Adds bookings waiting in quarantine (none yet on day one) | |
| `parsed` | Reads each field from the JSON record; `booked_at` `+05:30` becomes 04:30 UTC | `booked_at` `...Z` is already UTC: 04:30 |
| `with_fx_and_flight` | INR, so `fx_rate = 1.0`; NV1001 on 1 July is in silver.flights, so `flight_found` | same |
| final `CASE` | No rule fails: `reject_reason` NULL | NULL |

Copy 2 of B001 has `copy_number = 2`, so it is **counted as an exact duplicate** and goes
no further. It is not quarantined, because it is not bad data, just repeated data.

### 2c. `bookings_merge.sql`

1. Releases waiting bookings whose flight has arrived (none yet), and rejects those past
   the grace period.
2. `latest_booking_version` ranks the valid rows of each `booking_id` by `updated_at`.
   B001 and B002 have one valid row each, so rank 1.
3. A `LEFT JOIN` to `silver.bookings` sets `older_than_silver` (false: they are new).
4. `MERGE` inserts them. In `silver.bookings`:

| booking_id | pnr_token | passenger_token | fare_inr | channel | status | booked_at_utc |
|---|---|---|---|---|---|---|
| B001 | ff9f706b7b99... | 77704b7073aa... | 3000.00 | WEB | CONFIRMED | 2025-06-20 04:30 |
| B002 | a5d7a2746754... | d6c287764437... | 3100.00 | APP | CONFIRMED | 2025-06-20 04:30 |

(The tokens depend on the key. These came from the tests' key; yours will differ.)

### 2d. Reconciliation: `pipeline/checks.py: check_reconciliation()`

`batch_counts()` counts where all 21 rows of the batch went:

| rows_in | loaded | exact duplicates | older versions | quarantined | balanced |
|---|---|---|---|---|---|
| 21 | 12 | 1 (B001's copy) | 1 (the older B003) | 7 | true |

12 + 1 + 1 + 7 = 21, so the batch balances and a row goes into `meta.reconciliation`.
If it had not balanced, `PipelineError` would roll the whole day back and the run would
exit with code 1. `record_batch_details()` also writes the defect counts to
`meta.dq_results`, for example `exact_duplicate_removed = 1`.

---

## 3. Gold: `pipeline/gold.py: build_gold()`

After the last day, the runner rebuilds gold once, in the order in `GOLD_TABLES`.

**fact_flight** (`sql/gold/fact_flight.sql`) for the overnight flight:

- `flight_key = md5('NV1003|2025-07-01')`
- route BLR-DEL, `distance_km = 1709` (computed from the airport coordinates in
  `dim_route.sql`)
- `sched_dep_ist = 2025-07-01 23:30`, `scheduled_block_minutes = 155`, arrival delay
  5 minutes, so `is_on_time = true`
- aircraft VT-TAB has 20 seats, so `seats_offered = 20` and
  `ask = 20 x 1709 = 34,180`

**fact_booking** (`sql/gold/fact_booking.sql`) for B002:

- `booking_key = md5('B002')`, and `flight_key` joins to NV1001 on 1 July
- `date_key = 20250701`; `route_key` is BLR-BOM
- CONFIRMED on an operated flight, so `is_flown = true` and `is_revenue = true`
- `fare_revenue_inr = 3100`; `rpk = 834` (one passenger x 834 km)
- 3100 is inside the BLR-BOM economy range, so `is_fare_outlier = false`

**mart_booking_daily** sums it: on 1 July, BLR-BOM economy has `seats_offered = 34`
(NV1001, NV1005 and NV1009: 8 + 8 + 18), `passengers_flown = 6` and
`fare_revenue_inr = 38,600`. B002 is one of the six and 3,100 of the 38,600.

`check_gold()` then confirms every key is unique and every fact key has a dimension row.
`export()` writes the tables to `data/exports/gold` as Parquet and CSV.

---

## 4. Dashboard

`dashboard/queries.py: headline_kpis()` reads `mart_booking_daily.parquet` and computes
`sum(passengers_flown) / sum(seats_offered)` over whatever the filters select. B002 is
one of the passengers in that numerator.

---

## Try it

Start `python` in the repo folder (with the venv active) and paste:

```python
from pathlib import Path
import duckdb
from tests.conftest import make_settings, FIXTURE_DAYS
from pipeline.run import run_pipeline

run_pipeline(make_settings(Path("data/trace")), list(FIXTURE_DAYS))
con = duckdb.connect("data/trace/warehouse/nova.duckdb", read_only=True)
print(con.sql("SELECT * FROM bronze.flights WHERE flight_no LIKE '%1003%'"))
print(con.sql("SELECT * FROM silver.flights WHERE flight_no = 'NV1003'"))
print(con.sql("SELECT * FROM gold.fact_flight WHERE flight_no = 'NV1003'"))
print(con.sql("SELECT source, reason_code, status, record FROM silver.quarantine"))
```

Delete `data/trace` and run it again whenever you like: the results are identical.
