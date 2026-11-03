# Hackathon playbook

For the day itself: an unseen problem, a fixed time, a pipeline plus a dashboard, then a
demo. Read this on 5 November, and skim it again on the morning of the 6th.

## The first 15 minutes (no code yet)

### Questions to ask the panel (pick the ones the brief doesn't answer)

1. Who will use the dashboard, and what decision will they make with it?
2. Which three questions matter most if I can only answer three?
3. What is one row of each file? (A booking? A passenger? A flight leg? A bag?)
4. Which columns identify a record? Can a record be sent again with changes?
5. What time zone are timestamps in?
6. Are there known data problems I should look for, or should I find them?
7. Must personal data be masked? Is there anything I must not show?
8. What stack is required, and what can I choose? (Python, SQL, Power BI, a cloud?)
9. Do you want a running pipeline or a one-off analysis? Will you rerun it on new data?
10. How will you judge: correctness, code quality, the dashboard, or the explanation?

### Profile the data (10 minutes)

Run SQL straight on the files before writing any pipeline code. Copy
`scripts/profile_landing.py` and point it at their folder, or in a Python shell:

```python
import duckdb
con = duckdb.connect()
con.sql("CREATE VIEW raw AS SELECT * FROM read_csv('their_folder/*.csv', all_varchar = true, union_by_name = true, filename = true)")
print(con.sql("SELECT count(*), count(DISTINCT filename) FROM raw"))
print(con.sql("SUMMARIZE raw"))                     # per column: distinct, nulls, min, max
print(con.sql("SELECT * FROM raw USING SAMPLE 10"))
```

Then ask of every column: is it unique? (`count(DISTINCT x)` vs `count(*)`) Are there
nulls? Mixed formats (look at min/max of dates)? Values outside a sensible range? Case or
spacing variants (`SELECT x, count(*) GROUP BY x ORDER BY 2 DESC`)?

Write the defects you find in a list as you go: it becomes your data-quality slide.

### Decide before coding (5 minutes, write it down)

- **Business questions:** 3 to 5, phrased as questions.
- **Grain:** one sentence per table: "one row per ...".
- **Keys:** natural key of each source; which columns join them.
- **KPIs:** each as numerator / denominator, and the population (operated flights only?).
- **Must-have vs nice-to-have:** circle the must-haves.

## Time-boxed plans

Every plan has the same shape: **make it work end to end with the simplest version
first, then deepen**. A thin pipeline that runs is worth far more than a perfect silver
layer and no dashboard.

### 3-hour hackathon

| Time | Do | Must-have version |
|---|---|---|
| 0:00-0:15 | Questions, profiling, grain and KPIs on paper | |
| 0:15-0:45 | Bronze: load every file as text into DuckDB with `_source_file` | One `CREATE TABLE ... AS SELECT * FROM read_csv(..., all_varchar = true, filename = true)` per source |
| 0:45-1:30 | Silver: one SQL file per source: standardise, parse, dedupe (`row_number`), a `reject_reason` CASE, quarantine table | Dedupe + 3-4 most important rules + quarantine |
| 1:30-2:00 | Gold: one fact table at a clear grain + 2-3 dimensions + KPI query | Fact + date and one other dimension |
| 2:00-2:35 | Dashboard: KPI cards + 3 charts, titles as questions | Streamlit, one page |
| 2:35-2:50 | Reconciliation count, 2-3 tests, README with how to run | Row counts per layer printed at the end of the run |
| 2:50-3:00 | Rehearse the 5-minute demo | |

**Cut first if late:** tests beyond 2-3, PII masking beyond a simple hash with a key from
an env var, Parquet exports, extra pages, incremental loading (do a full rebuild and say
so).

### 6-hour hackathon

As the 3-hour plan up to 2:00, then:

| Time | Add |
|---|---|
| 2:00-3:00 | Proper star schema: all dimensions with md5 surrogate keys and unknown rows; marts with totals |
| 3:00-3:45 | Incremental load: file log by hash, upsert with `MERGE`, run twice to prove idempotency |
| 3:45-4:45 | Dashboard: 3-4 pages incl. a data-health page; filters |
| 4:45-5:30 | Tests: one per main defect, idempotency, no orphans, a hand-checked KPI |
| 5:30-6:00 | README, decisions list, rehearse |

**Cut first:** late-arriving retry logic (quarantine them and say "next I'd retry
them"), schema drift handling, benchmarks.

### 8-hour hackathon

As 6-hour, plus: late-arriving data retry, schema drift, PII tokenisation with HMAC,
step runner with run logging and exit codes, Parquet/CSV export for BI, a short
`DECISIONS.md`, a scaling paragraph. Keep the last 45 minutes for testing from a clean
folder and rehearsing.

### When time runs out (in this order)

1. Stop adding features 30 minutes before the end. Get it running end to end.
2. Make sure `python -m <your run command>` works from a clean start.
3. Make sure the dashboard opens.
4. Write down what you'd do next. A clear "next steps" list beats half-finished code.

## Stack variations

| If they require... | What changes | What stays the same |
|---|---|---|
| **Power BI** | Export gold as CSV/Parquet; build relationships and DAX measures (`POWER_BI_GUIDE.md`); skip Streamlit | Bronze/silver/gold SQL, the star schema, sum ÷ sum |
| **Pandas only** | `pd.read_csv(dtype=str)` for bronze; `drop_duplicates()`; `sort_values().groupby().tail(1)` for latest version; `merge(..., indicator=True)` for anti-joins; `groupby().agg()` for marts. Write each step as a function | The layers, quarantine DataFrame with a reason column, reconciliation counts |
| **MySQL / Postgres** | `CREATE TABLE` with types first; `COPY` (Postgres) or `LOAD DATA INFILE` (MySQL) for bronze; upsert = `INSERT ... ON CONFLICT DO UPDATE` (Postgres) / `ON DUPLICATE KEY UPDATE` (MySQL); `md5()` exists in both; `FILTER (WHERE ...)` → `SUM(CASE WHEN ... THEN 1 ELSE 0 END)` in MySQL; `try_cast` → a regex check or `CASE` | Everything else |
| **AWS** | S3 for landing; Glue or Lambda to load; Athena or Redshift for SQL; QuickSight for the dashboard | SQL, layers, checks |
| **Azure** | ADLS for landing; Data Factory to orchestrate; Synapse/Fabric SQL or Databricks; Power BI | Same |
| **Databricks** | Notebooks per layer; Delta tables (`MERGE INTO` works as here); Auto Loader for files; Databricks SQL dashboards | Same; Spark SQL is close to DuckDB SQL |

## Adapting this blueprint to a new dataset (ordered checklist)

1. **Copy the repo shape**, not the airline logic: `pipeline/`, `sql/`, `config/`,
   `dashboard/`, `tests/`.
2. **`config/pipeline.toml`:** replace `[sources.*]` with their sources: folder, format,
   business key, required columns. Replace `[rules]` values.
3. **`pipeline/bronze.py`:** usually unchanged. Change `files_to_ingest()` only if their
   file names don't follow `<source>_<date>.<ext>`.
4. **`sql/silver/00_macros.sql`:** keep `parse_utc` and `row_json`; replace the
   flight-specific macros.
5. **`sql/silver/<source>_check.sql`:** one per source. Copy `flights_check.sql`, keep
   the CTE skeleton (`batch_rows` → `with_record` → `numbered_copies` → `parsed` →
   `CASE reject_reason`), change the columns and rules.
6. **`sql/silver/<source>_merge.sql`:** copy one, change the key in `PARTITION BY`,
   `LEFT JOIN` and `MERGE ... ON`.
7. **`sql/silver/create_tables.sql`:** the new silver tables (quarantine stays as is).
8. **`pipeline/silver.py`:** usually unchanged; remove the flight/booking-specific
   lines in `record_batch_details()`.
9. **`sql/gold/*.sql`:** new dims and facts, grain at the top. Update `GOLD_TABLES`,
   `TABLE_KEYS` and `FOREIGN_KEYS` in `pipeline/gold.py`.
10. **`dashboard/queries.py` and `views/`:** new queries and charts; keep `Filters`.
11. **`tests/fixtures/`:** a few hand-written rows per defect; adapt `test_kpis.py`.

## Common failures and what to do

| Symptom | Likely cause | Fix |
|---|---|---|
| File won't parse | Wrong delimiter, a stray quote, a BOM, mixed encodings | Load as text with `all_varchar = true`; `read_csv(..., delim = ';')`; `ignore_errors = true` plus a count of skipped rows; `encoding = 'latin-1'` |
| Dates won't parse | Mixed formats | `coalesce(try_strptime(x, fmt1), try_strptime(x, fmt2), ...)`; list the unparseable ones: `WHERE parsed IS NULL AND x IS NOT NULL` |
| A join explodes row counts | The "one" side isn't unique on the join key, or you joined two facts at different grains | `SELECT key, count(*) FROM dim GROUP BY 1 HAVING count(*) > 1`; dedupe the dimension; never join two facts directly, aggregate one first |
| A join loses rows | Inner join with missing keys | `LEFT JOIN` and count the NULLs; add an "unknown" dimension row |
| KPIs look wrong | Averaging percentages; wrong population (cancelled flights included); double counting from grain | Recompute as sum ÷ sum; write the numerator and denominator separately and check each by hand on a tiny slice |
| Numbers change between runs | Non-deterministic dedupe (ties in `ORDER BY`), `now()` in logic, random IDs | Add a tie-breaker column to every `ORDER BY`; use dates from the data, not the clock |
| Dashboard breaks shortly before the demo | A filter with no data; a column renamed; a lock on the database file | Guard empty results (`if df.empty: st.info(...)`); read exported Parquet, not the live DB; keep a screenshot of every page as a fallback |
| DuckDB "could not set lock" | Another process (dashboard, notebook) has the file open | Close it, or read exports instead |

## The 5-minute demo script

1. **Business problem (30 s):** "Nova Air wants to know how it is doing on revenue, load
   factor and punctuality, which routes lose money per seat, where delays come from,
   and whether today's data can be trusted."
2. **Architecture (60 s):** show the diagram in the README. "Files land daily. Bronze
   keeps them exactly. Silver cleans and quarantines with a reason. Gold is a star schema
   with KPI marts. Every run reconciles, and stops if a row goes missing."
3. **One data-quality story (60 s):** the overnight flight, or the late booking. "This
   flight leaves at 23:30 and the source sends '02:05' as its arrival. A naive pipeline
   thinks it lands before it leaves and deletes it. Mine rolls the date and keeps it; a
   test proves the duration is 155 minutes."
4. **Dashboard insights (90 s):** the three strongest findings with numbers: the
   full-but-cheap route, the monsoon and fog delay pattern, and delays building through
   the day. Then the Data health page: "552 of 552 batches balanced."
5. **Trade-offs and next steps (60 s):** "I chose DuckDB and a plain Python runner over
   Airflow and Spark because it's one job on one machine. At 100x I'd move to partitioned
   Parquet and a cloud warehouse; the layers and checks stay the same. Next: SCD Type 2
   for passengers, partition-based gold rebuilds, alerting."

## "What would you do with more time?" (a strong close)

"Three things, in order of value. First, **data contracts** with the source teams, so
schema changes and late files are agreed, not discovered. Second, **monitoring**: the run
table already records rows and durations per step; I'd alert on volume drops and
freshness, not only on failures. Third, **history**: make passenger profiles SCD Type 2,
so we can ask what tier someone was when they flew, and move gold to partition rebuilds
so it scales. None of these changes the architecture, which is the point of building it
this way."
