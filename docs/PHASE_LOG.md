# Phase log

Karan asked for Phases 1-8 to be built in one pass, without commits. This file keeps
what each phase handed over: what was built, the command, real output, a suggested
commit message and three questions that test understanding. The outputs were captured
from runs on 2 November 2026 (see "Captured output" under each phase).

To commit phase by phase, stage each phase's files in order (`git add <files>`) and use
the message given. Or commit everything at once with the Phase 8 message.

---

## Phase 0: plan, repo setup, environment

**Built:** `requirements*.txt` (pinned), `pyproject.toml`, `.gitignore`, `.gitattributes`,
`.env.example`, `scripts/check_env.py`, `CLAUDE.md`, `DECISIONS.md` (D-001 to D-017).

**Command:** `python -m scripts.check_env`

**Captured output:**

```text
os            Windows 10.0.26200 (AMD64)
python        3.11.7    ok
duckdb        1.5.6     ok
faker         40.43.0   ok
pandas        3.0.6     ok
plotly        7.1.0     ok
python-dotenv 1.2.4     ok
streamlit     1.66.0    ok
psutil        7.2.2     ok
pytest        9.1.1     ok
ruff          0.17.1    ok
NOVA_PII_KEY  set (64 characters)  ok
disk free     859 GB on the drive holding D:\Projects\nova-air-pipeline
READY
```

**Commit:** `chore: project setup, pinned environment and decision log`

**Questions:**
1. Why is the venv built on Python 3.11 when 3.13 is installed?
2. Why does `.gitattributes` mark `tests/fixtures/**` as `-text`?
3. What exactly happens if `NOVA_PII_KEY` is empty, and why is there no default?

---

## Phase 1: data generator

**Built:** `scripts/generate_data.py`, `scripts/datagen/` (reference, schedule, flights,
bookings, patterns, sources, defects, writers), `scripts/profile_landing.py`.

**Commands:** `python -m scripts.generate_data` then
`python -m scripts.profile_landing --defects`

**Captured output:**

```text
profile=small seed=42 days=2025-07-01..2025-12-31 seconds=50.2
rows_written_flights=3864
rows_written_bookings=546108
rows_written_passengers=363913
manifest=data\generator_manifest.json

== planted defects: found by SQL vs generator manifest
  ok        flights: exact duplicate rows                                            found=39      manifest=39      
  ok        flights: older versions in the same file                                 found=61      manifest=61      
  ok        flights: flight number variants                                          found=596     manifest=596     
  ok        flights: corrupted flight numbers                                        found=25      manifest=25      
  ok        flights: arrival given as time only, earlier than departure clock time   found=386     manifest=386     overnight legs that need a date roll-over
  ok        flights: cancelled but with actual times                                 found=2       manifest=2       
  ok        flights: operated but missing actual arrival                             found=84      manifest=84      older versions are pre-departure snapshots, so they have no actual times either
  ok        flights: record sits in a later day's file                               found=123     manifest=123     late arrivals plus next-day corrections and re-sends
  ok        bookings: exact duplicate rows                                           found=4924    manifest=4924    
  ok        bookings: flight number variants                                         found=76794   manifest=76794   
  ok        bookings: corrupted flight numbers                                       found=1597    manifest=1597    
  ok        bookings: flight number in the 9000s (never scheduled)                   found=530     manifest=530     
  ok        bookings: fare zero or negative                                          found=1597    manifest=1597    
  ok        bookings: fare in USD                                                    found=10676   manifest=10676   
  ok        bookings: a required field is empty                                      found=1577    manifest=1577    
  ok        bookings: channel or ancillary amount empty                              found=16190   manifest=16190   
  ok        bookings: record sits in a later day's file                              found=1000    manifest=1000    stale versions re-sent the next day
  ok        passengers: passenger_id empty                                           found=1056    manifest=1056    
  ok        passengers: email or phone empty                                         found=10519   manifest=10519
```

(The same seed gives byte-identical files: `tests/test_generator.py`.)

**Commit:** `feat: seeded generator with 16 planted defects and SQL profiler`

**Questions:**
1. Why is each bookings file the passenger list for flights *departing* that day, and
   what would break if it were bookings *made* that day?
2. Why are flight-number variants counted per written row rather than when the variant
   is applied?
3. How does `profile_landing.py` prove the generator planted what its manifest claims?

---

## Phase 2: bronze and run logging

**Built:** `config/pipeline.toml`, `pipeline/settings.py`, `db.py`, `logs.py`, `checks.py`
(base), `bronze.py`, `run.py` (first version), `sql/meta/create_tables.sql`.

**Command:** `python -m pipeline.run --date 2025-07-01`, twice.

**Captured output:**

First run, then the same command again, in a scratch folder holding only 1 July's
files. Captured with the finished code, so the silver step runs too; the second run
loads nothing because every file's hash is already in `meta.file_log`:

```text
event=file_loaded file=airports.csv source=airports rows=10 batch_id=airports-ref-be53d041
event=file_loaded file=aircraft.csv source=aircraft rows=5 batch_id=aircraft-ref-a27545f1
event=file_loaded file=delay_codes.csv source=delay_codes rows=9 batch_id=delay_codes-ref-d5ccc64f
event=file_loaded file=fx_rates.csv source=fx_rates rows=304 batch_id=fx_rates-ref-1d3d4d8a
event=file_loaded file=flights_2025-07-01.json source=flights rows=20 batch_id=flights-2025-07-01-53d789b3
event=file_loaded file=passengers_2025-07-01.csv source=passengers rows=1869 batch_id=passengers-2025-07-01-c7f66f27
event=file_loaded file=bookings_2025-07-01.csv source=bookings rows=2769 batch_id=bookings-2025-07-01-81a7360f
event=step_finished step=ingest_bronze target=2025-07-01 seconds=4.67 rows_in=4986 rows_out=4986
event=batch_loaded batch_id=flights-2025-07-01-53d789b3 rows_in=20 rows_exact_duplicate=0 rows_quarantined=0 rows_waiting=0 rows_older_version=0 rows_loaded=20 rows_released=0 rows_given_up=0
event=batch_loaded batch_id=passengers-2025-07-01-c7f66f27 rows_in=1869 rows_exact_duplicate=17 rows_quarantined=2 rows_waiting=0 rows_older_version=86 rows_loaded=1764 rows_released=0 rows_given_up=0
event=batch_loaded batch_id=bookings-2025-07-01-81a7360f rows_in=2769 rows_exact_duplicate=17 rows_quarantined=25 rows_waiting=2 rows_older_version=43 rows_loaded=2684 rows_released=0 rows_given_up=0
event=step_finished step=load_silver target=2025-07-01 seconds=1.03 rows_in=4658 rows_out=4468 rows_quarantined=27
exit code: 0
---
event=file_skipped file=airports.csv reason="same content already loaded"
event=file_skipped file=aircraft.csv reason="same content already loaded"
event=file_skipped file=delay_codes.csv reason="same content already loaded"
event=file_skipped file=fx_rates.csv reason="same content already loaded"
event=file_skipped file=flights_2025-07-01.json reason="same content already loaded"
event=file_skipped file=passengers_2025-07-01.csv reason="same content already loaded"
event=file_skipped file=bookings_2025-07-01.csv reason="same content already loaded"
event=step_finished step=ingest_bronze target=2025-07-01 seconds=1.06 rows_in=0 rows_out=0
event=step_finished step=load_silver target=2025-07-01 seconds=0.03 rows_in=0 rows_out=0 rows_quarantined=0
exit code: 0
---
```

**Commit:** `feat: bronze ingestion with content-hash file log and run logging`

**Questions:**
1. Why does bronze store every field as text?
2. A file is re-sent under a new name with identical bytes. What happens, and which
   table makes that decision?
3. Where does `_row_number` come from, and what is it used for later?

---

## Phase 3: silver and quarantine

**Built:** `sql/silver/*.sql`, `pipeline/silver.py`, `pipeline/pii.py`, reconciliation and
quarantine-rate checks.

**Command:** `pytest tests/test_silver_flights.py tests/test_silver_bookings.py tests/test_reconciliation.py tests/test_pii.py -q`

**Captured output:**

```text
....................................                                     [100%]
36 passed in 134.25s (0:02:14)
```

**Commit:** `feat: silver layer with quarantine, reconciliation and HMAC PII tokens`

**Questions:**
1. Walk through `arrival_utc()` for an arrival of `02:05` after a 23:30 IST departure.
2. Write the reconciliation equation and say which counter an exact duplicate, an older
   version and a waiting booking each fall into.
3. Why is personal data tokenised in the *first* CTE of the check SQL, not in the merge?

---

## Phase 4: gold and KPIs

**Built:** `sql/gold/*.sql`, `pipeline/gold.py` (build, checks, export),
`sql/meta/health_snapshot.sql`.

**Command:** `pytest tests/test_gold.py tests/test_kpis.py -q`

**Captured output:**

```text
.................                                                        [100%]
17 passed in 75.48s (0:01:15)
```

**Commit:** `feat: gold star schema, KPI marts, orphan and capacity checks, exports`

**Questions:**
1. What is the grain of `mart_booking_daily`, and why are flight counts not in it?
2. Why is `flight_key` an md5 rather than a row number?
3. Show that averaging per-flight load factors on the fixtures gives 0.1714 while the
   true load factor is 0.1556.

---

## Phase 5: runner, backfill, idempotency

**Built:** final `pipeline/run.py` (one transaction per step, dependencies, full refresh
replaying day by day), `tests/test_idempotency.py`.

**Command:** `python -m pipeline.run --start 2025-07-01 --end 2025-12-31`

**Captured output:**

```text
Backfill run, from meta.pipeline_runs (step, times run, seconds inside the step):
ingest_bronze   184     15.8
load_silver     184     57.0
build_gold        1      2.2
check_gold        1      0.3
export            1      3.5

meta.reconciliation: 552 of 552 batches balanced

Re-running 2025-12-31 on the finished warehouse (fingerprint of all silver and gold tables
before and after, from tests/conftest.py: fingerprint()):
rerun of 2025-12-31: exit 0
silver+gold identical after rerun: True (18 tables)
```

**Commit:** `feat: step runner with per-step transactions, backfill and full refresh`

**Questions:**
1. Why does a full refresh replay day by day instead of all batches at once?
2. Name three things that make a second run change nothing.
3. A step fails halfway through a day. What is in the warehouse afterwards, and what
   records the failure?

---

## Phase 6: dashboard

**Built:** `dashboard/app.py`, `queries.py`, `charts.py`, `views/*.py`,
`.streamlit/config.toml`, screenshots in `docs/images/`.

**Command:** `streamlit run dashboard/app.py`

**Captured output:** all four pages rendered (screenshots in `docs/images/`); the Data
health page showed "552 of 552 batches balanced". `tests/test_dashboard_queries.py`
checks every query on the fixture exports.

**Commit:** `feat: Streamlit dashboard on exported gold and meta tables`

**Questions:**
1. Why does the dashboard read Parquet exports rather than the DuckDB file?
2. Why doesn't the cabin filter change on-time performance?
3. Which chart reveals that delays are passed from one flight to the next, and how?

---

## Phase 7: tests, CI, benchmarks

**Built:** the full `tests/` suite, `.github/workflows/ci.yml`, `scripts/benchmark.py`,
`docs/BENCHMARKS.md`.

**Commands:** `pytest -q`, `ruff check .`, `python -m scripts.benchmark`

**Captured output:**

```text
.......................................................................  [100%]
71 passed in 244.98s (0:04:04)
All checks passed!
```

Benchmark results: `docs/BENCHMARKS.md`. A clean copy (no data, new venv, new key) was rebuilt by following the README:
71 passed, lint clean, and every silver and gold table identical to this warehouse except
the five that hold PII tokens, which differ because the key differs.

**Commit:** `test: full suite, CI on three OSes, measured benchmarks`

**Questions:**
1. Which test would catch the old "module-level list of rejected rows" bug, and how?
2. Why do the tests raise the quarantine stop threshold to 50%, and which test proves
   the real 20% limit still works?
3. In the benchmark, why is wall time larger than the sum of the step durations?

---

## Phase 8: learning documents

**Built:** everything in `docs/`, `README.md`, `scripts/update_doc_numbers.py`,
`scripts/generate_mock_brief.py`.

**Command:** `python -m scripts.update_doc_numbers`

**Commit:** `docs: study guides, playbook, drills and generated results`

**Questions:**
1. Which numbers in the docs are generated, and how would you refresh them after a change?
2. In your own words, when would you move this project to Airflow? To Spark?
3. What would you do in the first two minutes with an unseen dataset, before writing code?
