# Scaling: what breaks first, and what to change

The small profile is about 550,000 booking rows; medium is about 3 million. Measured
timings are in `BENCHMARKS.md`. This page reasons about 10x, 100x and 1000x the
**medium** profile, which is roughly a real mid-size Indian airline's six months.

## What breaks first

| Scale | Rough size | What breaks first | Fix |
|---|---|---|---|
| **10x** (30M bookings) | ~7 GB of CSV, warehouse ~10 GB | Full gold rebuild and full-table `LEFT JOIN` to `silver.bookings` in every merge get slow; one laptop disk becomes the bottleneck | Rebuild gold by partition (below); keep silver merges keyed on a date column so DuckDB can skip old data; Parquet instead of CSV in landing |
| **100x** (300M) | ~70 GB | A single DuckDB file on one machine: memory for sorts and window functions, and a single writer process | Move storage to object storage as partitioned Parquet (or Delta/Iceberg tables) and compute to a cloud warehouse; process days in parallel |
| **1000x** (3B) | ~700 GB, likely streaming arrival | Daily batch latency, one orchestrator box, one transaction per day | Distributed engine (Spark/Databricks, Snowflake, BigQuery); event streaming (Kafka) for flight status; incremental models (dbt) |

What does **not** break: the design. Layers, quarantine, reconciliation, idempotent
upserts on business keys, surrogate keys, sum-over-sum marts: all of these carry over
unchanged. Only the engines underneath change.

## Measured: the silver merge grows with the table

`docs/BENCHMARKS.md` shows the silver step taking about 2 s a day at the start of the
medium backfill and about 8 s a day by the end. Each batch's `MERGE`, and the
`LEFT JOIN` that finds versions older than silver, scan all of `silver.bookings`. Fixes,
cheapest first:

1. Restrict the existing-row lookup to the flight dates in the batch
   (`AND existing.flight_date BETWEEN ...`), because a booking's flight date never
   changes. DuckDB can then skip whole row groups using their min/max statistics.
2. Keep silver physically sorted (or partitioned) by `flight_date`, so that skipping works well.
3. At larger scale, a table format with partitioned `MERGE` (Delta, Iceberg) or a
   warehouse with clustering keys does the same thing for you.

## Partition-based gold rebuilds (replacing the full rebuild)

Today `build_gold()` runs `CREATE OR REPLACE TABLE` for every gold table. At scale:

1. Record which `flight_date`s each run touched (they are already in `meta.file_log`
   and in the batches silver processed).
2. For each fact table, delete and re-insert only those dates:

```sql
DELETE FROM gold.fact_booking
WHERE date_key IN (SELECT date_key FROM touched_dates);

INSERT INTO gold.fact_booking
SELECT ... FROM silver.bookings ... WHERE flight_date IN (SELECT flight_date FROM touched_dates);
```

3. Marts are rebuilt for the same dates. Dimensions stay full rebuilds (they are small)
   or become upserts.
4. Outlier thresholds (`route_cabin_fare_range`) would move to their own small table,
   refreshed weekly, because recomputing quantiles over all history every day is the
   expensive part.

With table formats like Delta Lake or Iceberg, step 2 is a single
`INSERT OVERWRITE ... PARTITION (flight_date)`.

## When each tool becomes worth it

| Tool | Adopt when | Not before, because |
|---|---|---|
| **Airflow** (or Dagster, Prefect) | Several pipelines with dependencies between them, schedules, retries, backfills across teams, alerting | One job a day on one machine is just a scheduled command; `meta.pipeline_runs` already records runs |
| **dbt** | 50+ SQL models, several people editing them, a need for lineage graphs, generated docs and built-in tests | ~20 SQL files in a fixed order are readable as they are; dbt adds a tool to learn |
| **Spark** | Data no longer fits one machine's disk or memory (hundreds of GB and up), or the team already runs Databricks | DuckDB on one laptop handles tens of millions of rows; Spark's start-up alone is longer than our whole run |
| **Kafka** | Flight status must reach the dashboard within seconds or minutes, or many systems consume the same events | The sources here are daily files; a stream adds operations work for no gain |
| **A cloud warehouse** (Snowflake, BigQuery, Redshift, Synapse, Databricks SQL) | Many analysts query concurrently, data is shared across teams, or data outgrows one machine | One user and a few GB fit in a file |
| **Docker** | The pipeline must run identically on servers or in CI with system dependencies | Pure Python with pinned packages already runs anywhere Python does |

## How each local piece maps to the cloud

| Local component | Role | AWS | Azure | GCP |
|---|---|---|---|---|
| `data/landing/` | Object storage for raw files | S3 | ADLS Gen2 / Blob Storage | Cloud Storage (GCS) |
| Python CLI runner (`pipeline/run.py`) | Orchestrator | MWAA (managed Airflow), Step Functions | Data Factory, or Airflow in Fabric | Cloud Composer (Airflow), Workflows |
| DuckDB (`nova.duckdb`) | Warehouse and transformation engine | Redshift, or Athena on S3 | Synapse / Fabric Warehouse, Databricks | BigQuery |
| `silver.quarantine` | Dead-letter / rejected-records store | S3 prefix + Glue table, or SQS DLQ for streams | ADLS folder + table, Event Grid dead-letter | GCS prefix + BigQuery table, Pub/Sub dead-letter topic |
| `meta.*` tables | Run log and data-quality results | CloudWatch + a Redshift table | Azure Monitor + a table | Cloud Logging + a BigQuery table |
| `.env` PII key | Secret | Secrets Manager / KMS | Key Vault | Secret Manager / Cloud KMS |
| GitHub Actions | CI/CD | CodePipeline / CodeBuild (or keep GitHub Actions) | Azure DevOps Pipelines (or GitHub Actions) | Cloud Build (or GitHub Actions) |
| Streamlit dashboard | BI | QuickSight | Power BI | Looker / Looker Studio |

## Small things that would also change in production

- Landing files would arrive by an event (a new object in S3 triggers the run), not by date argument.
- The PII key would be rotated, and bronze access restricted (see `ARCHITECTURE.md`).
- Alerts: a blocking check would page someone, not only print a log line.
- `meta.pipeline_runs` would feed a monitoring dashboard with run time and row-count trends,
  so a sudden drop in volume is noticed even when no check fails.
