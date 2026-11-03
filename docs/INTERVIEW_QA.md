# Interview questions and answers

Short answers you can say out loud. Each points to where the proof is in the repo.
Numbers come from `README.md` (filled in from the latest run).

## Architecture

**1. Walk me through your pipeline in 30 seconds.**
Daily files land in a folder. Bronze copies them into DuckDB exactly as they arrived, as
text. Silver cleans them: standardises, parses, removes duplicates, keeps the latest
version per key, masks personal data, and puts every rejected row in a quarantine table
with a reason. Gold is a star schema with two KPI marts. The dashboard reads exported
Parquet. Every run reconciles row counts and stops if anything is unaccounted for.

**2. Why three layers instead of cleaning straight into tables?**
So I can always go back to exactly what arrived. If a cleaning rule was wrong, I fix it
and replay from bronze (`--full-refresh`). Without bronze, a bug destroys the evidence.

**3. Why is bronze all text?**
So loading never fails. If bronze typed the columns, one value like `not-a-time` would
fail the whole file. Judging values is silver's job, where a bad value becomes a reason
code.

**4. What is the grain of your fact tables?**
`fact_flight`: one row per scheduled flight leg. `fact_booking`: one row per booking,
one passenger on one flight. The marts: date x route, and date x route x cabin.

**5. Why two marts instead of one?**
Flight counts have no cabin. If I put them on the per-cabin table, each flight would be
counted twice. Different grains get different tables.

**6. Why does the dashboard read Parquet, not the database?**
DuckDB won't let the pipeline write while another process holds the file open. Reading
exports also means the dashboard sees only what was published, like Power BI would.

**7. Why md5 surrogate keys rather than auto-increment numbers?**
Auto-increment numbers change on every rebuild, and that breaks any saved relationship.
A hash of the natural key is the same forever. The trade-off is size: 32 characters vs
an integer. At scale I'd use a 64-bit hash.

**8. What is the "unknown" row in each dimension for?**
If a booking's passenger profile was quarantined, the booking still needs a passenger
key. It points at `-1` instead of disappearing from every inner join.

## Data quality and failure handling

**9. What happens to bad rows?**
They go to `silver.quarantine` with the source, batch, row number, reason code and the
masked original record. Nothing is dropped silently.

**10. How do you know no rows were lost?**
Reconciliation per batch: rows in = loaded + exact duplicates + older versions +
quarantined. It's stored in `meta.reconciliation`, and any mismatch stops the run. There
is a test that deliberately breaks it.

**11. Which checks stop the pipeline and which only warn?**
Stop when continuing would publish wrong numbers: missing key, missing column,
reconciliation mismatch, more than 20% rejected, duplicate or orphan keys, load factor
over 100%. Warn when the numbers are still right: schema drift, 5-20% rejected,
contradictions fixed by rule, late bookings.

**12. How do you handle late-arriving data?**
A booking whose flight isn't in silver yet waits in quarantine with status `waiting`.
Every run re-checks it; when the flight arrives, it's released into silver. After 3 days
it becomes `NO_VALID_FLIGHT`. The 3 days are counted from the date being processed, so
replays give the same answer.

**13. How do you handle duplicates?**
Two kinds. Exact duplicates share a whole-row fingerprint; I keep one copy. Several
versions of the same record share a business key; I keep the latest `updated_at`, and the
`MERGE` only updates if the incoming row is at least as new as the stored one.

**14. What about an older version arriving after a newer one?**
The `MERGE` condition `incoming.updated_at >= target.updated_at` ignores it, and it's
counted as an older version. Booking B003 in the fixtures tests exactly that.

**15. How do you handle overnight flights?**
The source sends a time-only arrival like `02:05`. I attach the departure's IST date, and
if that would put it at or before departure, add a day. Then I check the duration is
plausible. The previous pipeline had this inverted and deleted valid flights; a test now
checks an overnight flight survives with 155 minutes.

**16. What if a file arrives twice?**
Bronze fingerprints every file with SHA-256. The same bytes are skipped, even under a
different name.

**17. What if a new column appears?**
Bronze adds it to the table and logs it in `meta.schema_changes` as a warning. If a
required column disappears, the run stops.

**18. What if a step fails halfway?**
Each step is one transaction. A failure rolls it back, records the failure in
`meta.pipeline_runs` and `meta.dq_results`, and exits with code 1. The next run retries
from the same point.

**19. How do you treat outliers?**
Flag, don't delete: a fare beyond 3 x IQR of its own route and cabin. A global threshold
would flag every long-haul fare and miss a crazy short-haul one.

## Personal data

**20. How do you protect PII?**
Passenger ID, PNR, email and phone become HMAC-SHA256 tokens keyed by a secret; name is
dropped; date of birth becomes an age band. This happens in the first silver SQL step,
so silver, gold, exports and the quarantine never hold raw values. A test scans them.

**21. Why HMAC and not plain SHA-256?**
Anyone can SHA-256 a list of known emails and match them. HMAC needs the key.

**22. What if the key is missing?**
The pipeline stops before touching data, exit code 2. There's no default key, because
a default makes every token guessable.

**23. Where is raw PII still present, and how would you protect it?**
Landing and bronze. In production: separate storage that only the pipeline can read, a
retention period, the key in a secrets manager.

## SQL

**24. How do you dedupe in SQL?**
`row_number() OVER (PARTITION BY key ORDER BY updated_at DESC)`, then keep row 1.

**25. How do you upsert?**
`MERGE INTO target USING incoming ON key WHEN MATCHED AND newer THEN UPDATE WHEN NOT
MATCHED THEN INSERT`. In Postgres, `INSERT ... ON CONFLICT DO UPDATE`.

**26. Why calculate load factor as sum over sum?**
An average of per-flight percentages weights a 20-seat flight the same as a 186-seat one.
Sum of passengers divided by sum of seats is the real share of seats filled. A test
proves the two differ on the fixtures.

**27. How do you find bookings with no flight?**
An anti-join: `LEFT JOIN flights ... WHERE flights.key IS NULL`.

**28. How do you handle time zones?**
Store UTC; parse each known format explicitly; IST is added in gold for reporting. India
has no daylight saving, so it's always +5:30.

**29. Why named CTEs?**
Each step has a name that says what it does (`latest_booking_version`), so the query
reads like a recipe and you can debug one step at a time.

## KPIs

**30. Define RASK and yield, and why both?**
RASK is revenue per available seat-km: it rewards filling seats *and* charging well.
Yield is fare revenue per passenger-km: price only. A route can have a fine yield and a
bad RASK if it flies empty.

**31. What did the data show?**
(Answer from the dashboard; see `GENERATOR_ANSWER_KEY.md`.) DEL-BOM is the busiest and
fullest route but has the lowest RASK; BLR-COK is half empty; BOM delays rise in the
monsoon; DEL mornings in December; delays build through the day; Diwali weeks spike
revenue.

**32. How is on-time performance defined?**
Operated flights arriving within 15 minutes of schedule, divided by operated flights
with an actual arrival time. Flights with no arrival time are excluded, not counted as
late.

**33. Average delay: of what?**
I give two, each labelled: all measured flights (early = 0), and delayed flights only.
On the small profile they are about 23 and 60 minutes.

## Scale and trade-offs

**34. What breaks first at 10x?**
The full gold rebuild and the merges that join against all of silver. I'd rebuild gold
by date partition and use Parquet in landing.

**35. And at 100x or 1000x?**
One machine. Move to object storage with partitioned Parquet or Delta/Iceberg, and a
cloud warehouse or Spark. The layers, quarantine and reconciliation stay the same.

**36. Is it idempotent?**
Yes: a test runs it twice, day by day vs backfill, and full refresh, and compares a
content hash of every silver and gold table.

**37. Is it incremental?**
Bronze loads only new files; silver processes only batches without a reconciliation row.
Gold is a full rebuild because it takes seconds; I'd switch to partitions at scale.

**38. How long does it take?**
See `BENCHMARKS.md`: measured on my laptop, including a spinning hard disk where the
commits dominate.

## "Why didn't you use X?"

**39. Why not Airflow?**
One job a day on one machine. My runner has an ordered step list with dependencies,
logging and a run table. I'd add Airflow when there are several pipelines with
cross-dependencies, schedules and retries to manage.

**40. Why not dbt?**
About twenty SQL files in a fixed order are readable as they are. dbt pays off with many
models, several authors, lineage and generated docs; my SQL files would port to dbt
models almost one to one.

**41. Why not Spark?**
The data fits on one machine; DuckDB processes millions of rows in seconds. Spark's
start-up would be longer than my whole run.

**42. Why not Pandas for the transformations?**
Set-based SQL is faster, testable in the warehouse, and exactly what the role uses. I
use Python only where it's simpler: file handling, the HMAC function, orchestration.

**43. Why DuckDB?**
No server, no setup, full SQL including MERGE and window functions, and it reads Parquet
and CSV directly. The same SQL ports to Snowflake or BigQuery with small changes.

**44. Why Streamlit and not Power BI?**
Streamlit runs anywhere with no licence and lives in the repo. The exports are ready for
Power BI too, with a guide and DAX measures in `POWER_BI_GUIDE.md`.

## About you

**45. What would you do with more time?**
SCD Type 2 for passengers, partition-based gold rebuilds, data contracts with the source
teams, alerting on blocking checks, and freshness monitoring from `meta.pipeline_runs`.

**46. What was the hardest bug?**
A full refresh gave slightly different quarantine records from the original run: after
the promo_code column appeared, old rows replayed with an extra empty field in their
JSON. The idempotency test caught it; I fixed it by dropping null fields from the record.

**47. What did you measure before optimising?**
I profiled first. The time wasn't in the SQL: it was CSV dialect sniffing (0.25 s per
file) and disk syncs on a spinning disk. Spelling out the CSV format and committing once
per step took a back-to-back measurement from 249 s to 130 s.
