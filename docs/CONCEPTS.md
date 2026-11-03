# Concepts, each with an example from this project

Each entry says what the idea does in plain words first, then names it, then points
at where it lives in this repo.

## ETL vs ELT

**What it does:** decides *where* data gets cleaned. Either you clean it on the way in,
in your own code, and load only clean data (**ETL**: extract, transform, load). Or you
load the raw data into the warehouse first and clean it there with SQL (**ELT**:
extract, load, transform).

**Here:** ELT. Files are loaded raw into `bronze`, then SQL in `sql/silver` and
`sql/gold` transforms them inside DuckDB. See `ETL_VS_ELT.md`.

## Medallion architecture

**What it does:** keeps raw, cleaned and business-ready data in separate layers, so you
can always go back to what arrived and replay from it. The layers are called **bronze**
(raw), **silver** (clean) and **gold** (ready for questions).

**Here:** `bronze.bookings` holds the CSV rows exactly as sent; `silver.bookings` one
clean row per booking; `gold.fact_booking` the reporting table.

## Star schema

**What it does:** puts the things you count and add (passengers, revenue, seats) in a
central table, and the things you filter and group by (date, route, airport) in small
tables around it, each joined by one key. The picture looks like a star. The central
tables are **facts**; the surrounding ones are **dimensions**.

**Here:** `fact_flight` and `fact_booking` in the middle; `dim_date`, `dim_route`,
`dim_airport`, `dim_aircraft`, `dim_passenger`, `dim_delay_reason` around them.

## Grain

**What it does:** says exactly what one row of a table represents. Getting it wrong is
the most common cause of double counting.

**Here:** `fact_booking` is "one booking: one passenger on one flight";
`mart_booking_daily` is "one date, route and cabin". That is why flight counts are *not*
in `mart_booking_daily`: with two cabins, each flight would appear twice. Every gold SQL
file states its grain at the top.

## Surrogate keys

**What it does:** gives every dimension row an ID that the warehouse owns, separate from
the business's own codes, so facts can point at dimensions with one simple column. The
business's own identifier (like `BLR` or `NV1003 + 2025-07-01`) is the **natural key**;
the warehouse's ID is the **surrogate key**.

**Here:** `route_key = md5('BLR-BOM')`. Because it is a hash of the natural key, it is
the same after every rebuild, so Power BI relationships never break
(`test_surrogate_keys_survive_a_full_rebuild`). Each dimension also has an "unknown" row
(`'-1'`), so a booking whose passenger profile was quarantined still joins.

## Idempotency

**What it does:** running the same job twice gives exactly the same result as running it
once. Like pressing a lift button twice: the lift still comes once.

**Here:** files are skipped by content hash, batch IDs come from the file, upserts only
apply newer versions, and gold is rebuilt from scratch. `tests/test_idempotency.py`
proves a second run, a day-by-day run, a backfill and a full refresh all give
byte-identical silver and gold.

## Incremental loads

**What it does:** processes only what is new since the last run, instead of everything
every time.

**Here:** `pending_batches()` picks only batches with no row in `meta.reconciliation`;
bronze skips files already in `meta.file_log`.

## Watermarks

**What it does:** remembers "how far we got" so the next run starts from there. Often a
timestamp: "everything updated after 2025-07-03 23:00".

**Here:** this project uses a file log instead of a timestamp watermark: `meta.file_log`
records every file processed, and `meta.reconciliation` every batch silver has finished.
A timestamp watermark would be used if the source were a database table:
`WHERE updated_at > (SELECT max(updated_at) FROM meta.watermark)`. File logs are safer
for files, because late files can carry old timestamps.

## Upserts

**What it does:** "update if it exists, insert if it does not", in one statement. The
name is a blend of *update* and *insert*.

**Here:** every `*_merge.sql` uses `MERGE INTO silver.<table> ... WHEN MATCHED AND
incoming.updated_at_utc >= target.updated_at_utc THEN UPDATE WHEN NOT MATCHED THEN
INSERT`. The `>=` condition is what stops a stale re-sent booking (B003 on 2 July)
from overwriting the newer NO_SHOW status.

## Slowly changing dimensions (SCD) Type 1 and Type 2

**What it does:** decides what happens to a dimension row when the real-world thing
changes, for example a passenger moving from SILVER to GOLD tier.

- **Type 1:** overwrite. You only know the current tier. Simple; history is lost.
- **Type 2:** add a new row for each change, with `valid_from`, `valid_to` and
  `is_current` columns. You can ask "what tier were they *when they flew*?"

**Here:** `dim_passenger` is Type 1 (P002 is GOLD; the earlier SILVER is gone). Turning
it into Type 2 would keep every version of a passenger.

## Partitioning

**What it does:** splits a big table or folder into pieces by a column, usually date, so
a query or rebuild touches only the pieces it needs. Like filing receipts in one folder
per month.

**Here:** landing files are already partitioned by day (`bookings_2025-07-01.csv`).
Gold is rebuilt in full because it is small; `SCALING.md` explains rebuilding only the
changed months (`INSERT OR REPLACE ... WHERE month = ...`) when it is not.

## Columnar storage

**What it does:** stores a table column by column instead of row by row. A query that
sums one column reads only that column, and similar values compress well. **Parquet** is
the standard columnar file format.

**Here:** DuckDB stores tables in columns, and `data/exports/gold/*.parquet` are
columnar files. On the small profile, `fact_booking.parquet` is 45 MB; the same rows as
`fact_booking.csv` take 132 MB.

## Late-arriving data

**What it does:** handles records that arrive after something they depend on, or before
the thing they point to exists.

**Here:** flight NV1009's record arrived a day late, so booking B012 arrived *before*
its flight. Instead of dropping B012, silver puts it in quarantine with status `waiting`,
re-checks it on every run, and released it on 2 July when the flight appeared. After
3 days of waiting (`late_flight_grace_days`), a booking is rejected as
`NO_VALID_FLIGHT`.

## Schema drift

**What it does:** copes when a source adds, removes or renames columns without warning.

**Here:** `promo_code` appears in bookings files from 1 October. `bronze.align_table()`
notices a column the table does not have, adds it, and logs the change to
`meta.schema_changes` as a warning. Silver reads fields from the JSON record, so old
rows simply have no promo code. A *missing required* column, on the other hand, stops
the run.

## Quarantine (dead-letter table)

**What it does:** keeps every rejected row, with the reason and a pointer back to where
it came from, instead of deleting it. Often called a **dead-letter** queue or table.

**Here:** `silver.quarantine` (reason code, status, masked JSON record, batch and row
number).

## Reconciliation

**What it does:** proves no row went missing: what came in equals what went out, plus
everything you deliberately set aside.

**Here:** per batch, rows in = loaded + exact duplicates + older versions + quarantined,
stored in `meta.reconciliation`. A mismatch stops the run.

## Tokenisation (keyed hashing, HMAC)

**What it does:** replaces a personal value with a code that is always the same for the
same value (so joins still work) but cannot be reversed or guessed without a secret key.

**Here:** `pii_token()` = HMAC-SHA256 with `NOVA_PII_KEY`. Without the key, someone with
a list of real emails cannot hash them to find matches, which a plain SHA-256 would allow.
