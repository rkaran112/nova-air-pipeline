# Resume bullets

Honest, measured, and clear that the data is synthetic. Every number comes from
`README.md` (filled in from the latest run by `scripts/update_doc_numbers.py`) or
`docs/BENCHMARKS.md` (written by `scripts/benchmark.py`). Re-check them after any rerun.

## Project line

**Nova Air operations pipeline** (Python, DuckDB SQL, Streamlit, pytest, GitHub Actions)

## Bullets

- Built an end-to-end ELT pipeline (bronze/silver/gold medallion layers, star schema with
  2 fact tables, 6 dimensions and 2 KPI marts) that turns 6 months of synthetic daily
  airline files (913,885 source rows, 16 planted defect types) into a Streamlit
  dashboard and Power BI-ready Parquet/CSV exports.
- Designed data-quality handling with a quarantine table and per-batch row reconciliation
  that stops the run on any mismatch; 552 of 552 daily batches balanced,
  and 12,184 late-arriving bookings were released automatically once their
  flight record arrived.
- Made loads idempotent and incremental (content-hash file log, MERGE upserts with
  newer-wins versioning, deterministic md5 surrogate keys); a test proves reruns, daily
  vs backfill runs and full refreshes produce byte-identical warehouses.
- Applied data governance: a sensitivity label (public / internal / pii) on every source
  column, keyed HMAC-SHA256 tokenisation of the pii columns in the first silver step
  (pipeline refuses to run without the key), and a warning when an unlabelled column
  arrives; 77 pytest tests check every defect, hand-calculated KPIs (sum-over-sum load
  factor), orphan keys and the absence of raw PII in silver, gold and the exports.
- Profiled before optimising (CSV dialect sniffing and disk commits, not SQL, were the
  bottleneck) and scaled to a 3.3M-booking-row profile: 184 days in about 28 minutes
  on a 4-core laptop with a hard disk, peaking under 1 GB of memory.

Numbers as of the 2-3 November 2026 runs: 913,885 source rows and 552 batches from the
README results, 77 tests from `pytest -q`, the medium timing (1,670 s, 965 MB) from
`docs/BENCHMARKS.md`. Re-check after any rerun.

## One-line version

Built a tested, idempotent ELT pipeline in Python and DuckDB SQL (bronze/silver/gold, star
schema, quarantine with row reconciliation, HMAC PII masking) over 6 months of synthetic
airline data, with a Streamlit dashboard and Power BI exports.

## What not to claim

- Not production data, not a real airline, not deployed in the cloud.
- The patterns the dashboard "finds" were planted by the generator.
- Benchmarks are from one laptop (see the machine details in `BENCHMARKS.md`).
