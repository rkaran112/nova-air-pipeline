# Change drills: 20 requests an interviewer might make

Panels often say "now change X" and watch how you work. For each request: read it,
set a timer for the target time, and try it on a scratch branch
(`git switch -c drill-e1`). Open the answer only afterwards. **None of these changes are
made on `main`.**

How to work every drill: (1) say which files you will touch before touching them;
(2) make the change; (3) run `pytest -q` and the pipeline; (4) show the number that
proves it worked.

Difficulty: 6 easy, 8 medium, 4 hard, 2 explain-only.

---

## Easy

### E1. "Use 10 minutes instead of 15 for on-time." (10 min)
<details><summary>Answer</summary>

- **Files:** `config/pipeline.toml` (`on_time_threshold_minutes = 10`); `docs/DATA_DICTIONARY.md`
  and dashboard help text that say 15; `tests/test_kpis.py` if a fixture flight is between 10
  and 15 minutes late (none is, so 4/6 still holds; say why).
- **Impact:** `fact_flight.is_on_time` and `mart_flight_daily.flights_on_time` change after
  the next run; OTP drops. No silver change, because the threshold is used only in gold.
- **Verify:** `python -m pipeline.run --full-refresh`, then compare the OTP card before and
  after. Mention that a full refresh is not even needed: gold is rebuilt on every run.
</details>

### E2. "Add an 'Average fare' card to the overview." (15 min)
<details><summary>Answer</summary>

- **Files:** `dashboard/queries.py` (`headline_kpis`: add
  `sum(m.fare_revenue_inr) / nullif(sum(m.passengers_flown), 0) AS average_fare`);
  `dashboard/views/overview.py` (a sixth `st.metric`, with help text saying it is fare
  revenue per passenger flown, so no-show fares inflate it slightly).
- **Impact:** dashboard only; no pipeline change, because the mart already has both totals.
- **Verify:** add an assertion to `tests/test_dashboard_queries.py`: on the fixtures,
  122,950 / 14.
</details>

### E3. "Reject fares above ₹1,00,000 as a data error." (15 min)
<details><summary>Answer</summary>

- **Files:** `config/pipeline.toml` (`max_fare_inr = 100000` under `[rules]`);
  `sql/silver/bookings_check.sql` (new `WHEN fare_inr > $max_fare_inr THEN 'FARE_TOO_HIGH'`
  after `NON_POSITIVE_FARE`, using `round(fare_amount * fx_rate, 2)` because `fare_inr` is
  computed in the same SELECT); a fixture row and a test.
- **Impact:** those bookings move from silver to quarantine; revenue drops a little;
  reconciliation still balances because quarantined rows are counted.
- **Verify:** the new test, plus `SELECT count(*) FROM silver.quarantine WHERE reason_code =
  'FARE_TOO_HIGH'`. Say the trade-off: outliers are *flagged*, impossible values are
  *rejected*; where is the line?
</details>

### E4. "Show the top 5 routes by revenue on the overview." (15 min)
<details><summary>Answer</summary>

- **Files:** `dashboard/views/overview.py` only: reuse `queries.route_performance()`,
  `.nlargest(5, "revenue")`, show with `st.dataframe` or a bar chart titled as a question.
- **Impact:** none outside the dashboard.
- **Verify:** compare with `SELECT route_code, sum(total_revenue_inr) ... ORDER BY 2 DESC LIMIT 5`.
</details>

### E5. "Add an is_long_haul flag (over 1,500 km) to routes." (10 min)
<details><summary>Answer</summary>

- **Files:** `sql/gold/dim_route.sql` (`distance_km > 1500 AS is_long_haul`, and `NULL`
  for the unknown row); `docs/DATA_DICTIONARY.md`; optionally a test.
- **Impact:** a new column in `dim_route` and its exports. Power BI users must refresh.
- **Verify:** `SELECT route_code, distance_km, is_long_haul FROM gold.dim_route ORDER BY 2`.
</details>

### E6. "Give late flights 5 days to arrive instead of 3." (10 min)
<details><summary>Answer</summary>

- **Files:** `config/pipeline.toml` (`late_flight_grace_days = 5`); docs that say 3.
- **Impact:** bookings wait longer before `NO_VALID_FLIGHT`. Existing decisions are not
  revisited unless you `--full-refresh`, which replays every day with the new rule.
- **Verify:** `test_waiting_booking_is_rejected_after_the_grace_period` uses its own value
  and still passes; after a full refresh, more December bookings show `waiting`.
</details>

---

## Medium

### M1. "Let me filter the dashboard by sales channel." (30 min)
<details><summary>Answer</summary>

- **The trap:** seats are not sold by channel, so "load factor for the APP channel" has no
  meaning. Do *not* add channel to `mart_booking_daily`: its seats column would be
  repeated per channel and every load factor would be wrong.
- **Files:** `dashboard/app.py` (a channel multiselect); `dashboard/queries.py` (revenue,
  passengers and bookings by channel from `fact_booking` joined to `dim_date` and
  `dim_route`); say on the page that load factor ignores the channel filter.
- **Verify:** passengers by channel summed over all channels equals the overview's total.
</details>

### M2. "Add a daily baggage file: bag_id, booking_id, weight_kg, fee_inr." (60 min)
<details><summary>Answer</summary>

- **Files:** `config/pipeline.toml` (`[sources.baggage]`, placed after bookings);
  `sql/silver/create_tables.sql` (`silver.baggage`); new `sql/silver/baggage_check.sql`
  and `baggage_merge.sql` copied from the bookings pair (key `bag_id`; rules: booking must
  exist in silver, weight 0-50 kg, fee >= 0); `pipeline/silver.py` usually unchanged;
  `sql/gold/fact_bag.sql` (grain: one row per bag; keys to `fact_booking`); `GOLD_TABLES`,
  `TABLE_KEYS`, `FOREIGN_KEYS` in `pipeline/gold.py`; fixtures and tests.
- **Impact:** a new source, bronze table, silver table and fact. Bronze needs no code.
- **Verify:** reconciliation rows for `baggage` batches; no orphans from `fact_bag` to
  `fact_booking`.
</details>

### M3. "How does revenue depend on how early people book?" (30 min)
<details><summary>Answer</summary>

- **Files:** `dashboard/queries.py` (group `fact_booking.lead_time_days` into bands with
  `CASE`: 0-3, 4-7, 8-14, 15-30, 31+; average fare per band, revenue bookings only);
  a chart in `views/routes.py` or a new page.
- **Impact:** dashboard only; `lead_time_days` is already in `fact_booking`.
- **Verify:** bands sum to the total number of revenue bookings.
</details>

### M4. "Passenger files are messy; don't stop the run for them below 40% rejects." (30 min)
<details><summary>Answer</summary>

- **Files:** `config/pipeline.toml` (per-source override, e.g.
  `[sources.passengers] quarantine_block_rate = 0.40`); `pipeline/silver.py: process_batch()`
  (use the source's value if present, else the default); a test with a 30%-bad passenger file.
- **Impact:** only that source's stop threshold; the warning still fires.
- **Verify:** the new test passes and `test_too_many_rejected_rows_stop_the_run` still does.
  Be ready to argue whether loosening a stop rule is a good idea.
</details>

### M5. "Warn me if today's files didn't arrive." (40 min)
<details><summary>Answer</summary>

- **Files:** `pipeline/bronze.py` (`files_to_ingest` already logs `file_not_found`: also
  `record_check(..., "file_missing", "warn", 1)`); `dashboard/queries.py: freshness()` (days
  between latest file and latest run); Data health page.
- **Impact:** a new warning in `meta.dq_results`; no change to the data.
- **Verify:** delete one landing file in a scratch copy, run that day, see the warning on
  the Data health page.
</details>

### M6. "Show on-time performance by airport and hour, not just delay minutes." (30 min)
<details><summary>Answer</summary>

- **Files:** `dashboard/queries.py` (`avg(CAST(is_on_time AS INTEGER))` grouped by origin
  and `sched_dep_hour_ist`, excluding `is_on_time IS NULL`); `views/delays.py` (reuse
  `heatmap()`, but colour scale reversed or titled so that darker = worse).
- **Impact:** dashboard only.
- **Verify:** the weighted average of the cells equals the overview OTP for the same filters.
</details>

### M7. "Give Power BI a monthly route table." (30 min)
<details><summary>Answer</summary>

- **Files:** new `sql/gold/mart_route_monthly.sql` (grain: month x route; totals only:
  seats, passengers, revenue, ASK, RPK, flights); add to `GOLD_TABLES` and `FOREIGN_KEYS`
  in `pipeline/gold.py` (it is exported automatically); `DATA_DICTIONARY.md`.
- **Impact:** a new table and export; nothing else changes.
- **Verify:** its totals equal `mart_booking_daily` summed by month; the orphan check covers it.
</details>

### M8. "The ops system now also sends 2025-07-01T06:00:00+0530 (no colon)." (30 min)
<details><summary>Answer</summary>

- **Files:** `sql/silver/00_macros.sql` (`parse_utc`: a new `WHEN text_value LIKE
  '%+0530'` branch, same as `+05:30`); a fixture row with the new format; a test.
- **Impact:** those rows parse instead of becoming `BAD_TIMESTAMP`. Old data is unaffected.
- **Verify:** the test; and `SELECT count(*) FROM silver.quarantine WHERE reason_code =
  'BAD_TIMESTAMP'` drops after a full refresh if real files contained the format.
</details>

---

## Hard

### H1. "Keep passenger tier history (SCD Type 2)." (90 min)
<details><summary>Answer</summary>

- **Files:** `sql/silver/create_tables.sql` (a `silver.passenger_versions` table: token,
  tier, age band, `valid_from`); `passengers_merge.sql` (also insert every new version
  into it, ignoring exact repeats); `sql/gold/dim_passenger.sql` (one row per version,
  `passenger_key = md5(token || valid_from)`, `valid_to = lead(valid_from) OVER (PARTITION
  BY token ORDER BY valid_from)`, `is_current`); `sql/gold/fact_booking.sql` (join on token
  AND `booked_at` between `valid_from` and `valid_to`).
- **Impact:** dim_passenger gets more rows; bookings point at the tier *at booking time*.
  Out-of-order versions need care: build history from all versions, not only accepted ones.
- **Verify:** a fixture passenger with two tiers and a booking before and after the change,
  each pointing at the right version; no orphans; P002 has three versions in the fixtures.
</details>

### H2. "Gold rebuild takes too long: only rebuild the days that changed." (90 min)
<details><summary>Answer</summary>

- **Files:** `pipeline/gold.py` (collect the flight dates touched in this run from the
  batches silver processed; facts and marts do `DELETE ... WHERE date_key IN (...)` then
  `INSERT ... WHERE flight_date IN (...)`; dims stay full rebuilds); each fact/mart SQL
  file gains a `WHERE flight_date IN (SELECT flight_date FROM touched_dates)`; outlier
  thresholds move to their own table (a full rebuild of quantiles defeats the purpose).
- **Impact:** faster daily runs; a corrected flight from an *old* date must also mark that
  date as touched (the batch's `file_date` is not enough: use the flight dates in it).
- **Verify:** `test_idempotency.py` still passes, and a partial rebuild equals a full one
  (fingerprint both).
</details>

### H3. "Raw PII must never enter the warehouse." (60 min)
<details><summary>Answer</summary>

- **Files:** `pipeline/bronze.py` (for passengers and bookings, select
  `pii_token(email) AS email` etc. in the `INSERT ... SELECT`, drop `full_name`, band the
  date of birth); `sql/silver/passengers_check.sql` and `bookings_check.sql` (stop
  tokenising again); `tests/test_pii.py` (also scan bronze); `ARCHITECTURE.md` and
  `ETL_VS_ELT.md` (this step is now ETL).
- **Impact:** bronze is no longer an exact copy: if a tokenisation rule is wrong, you
  can only replay from landing. Say this trade-off out loud.
- **Verify:** the PII test with `bronze` added to the schemas.
</details>

### H4. "Sources now send a morning and an evening file for the same day." (75 min)
<details><summary>Answer</summary>

- **Files:** `pipeline/bronze.py: files_to_ingest()` (glob `bookings_2025-07-01*.csv` and
  sort by name); file names to batch IDs already include the hash, so two batches per day
  work; `pipeline/silver.py: pending_batches()` (order by `file_date`, source, then
  `loaded_at` or file name, so the evening file wins ties); fixtures with two files.
- **Impact:** the version rule (`updated_at`) already resolves which record wins; the
  ordering matters only for ties.
- **Verify:** reconciliation per batch still balances; a record changed in the evening file
  ends up in silver with the evening value.
</details>

---

## Explain-only (no code)

### X1. "How would you run this at 06:00 every day on a server, and know when it fails?" (5 min to answer)
<details><summary>Answer</summary>

Schedule `python -m pipeline.run --date <yesterday>` with cron (Linux) or Task Scheduler
(Windows), or a managed scheduler (Cloud Scheduler, EventBridge, Data Factory). Exit
codes are already meaningful (0, 1, 2), so the scheduler can alert on non-zero. Ship
the `key=value` logs to a log service. Add a freshness alert from `meta.pipeline_runs`
("no successful run in 26 hours"), because a job that never starts never fails. When
there are several dependent jobs, move to Airflow and keep the same commands as tasks.
</details>

### X2. "Finance says our load factor doesn't match theirs. How do you investigate?" (5 min to answer)
<details><summary>Answer</summary>

Agree the definition first: numerator (flown passengers, or all paid bookings incl.
no-shows? infants?), denominator (seats offered, or seats sold? blocked seats?),
population (operated flights only? which dates, local or UTC?). Then reconcile on a tiny
slice, one route on one day: list their flights and passengers next to ours and find the
first row that differs. Check the obvious traps: averaging percentages, cancelled flights
in the denominator, time-zone shifted dates, duplicates. Document the agreed definition
in the data dictionary and add a test with that slice.
</details>
