# Practice drills

Do these on 3-5 November, in order. Write your prediction down **before** you run
anything: the point is to train the prediction, not to see the answer.

Set up a scratch warehouse from the test fixtures when a drill asks for one (see "Try
it" in `EXECUTION_FLOW.md`), or use the full data in `data/`.

## 1. Trace drills (predict, then run)

For each one, predict the exact output, then check with a query.

1. **Bronze vs silver count.** The fixture file `bookings_2025-07-01.csv` has 21 data
   rows. How many rows from it end up in `silver.bookings` after the whole fixture run?
   Which ones don't, and why?
2. **The overnight arrival.** In `flights_2025-07-01.json`, `" NV 1003 "` departs
   `01/07/2025 23:30` and arrives `02:05`. What are `sched_dep_utc` and `sched_arr_utc`
   in silver?
3. **Stale resend.** `bookings_2025-07-02.csv` re-sends B003 as CONFIRMED with
   `updated_at` 25 June. What is B003's status in silver after day 2, and what does
   `meta.reconciliation` say for that batch?
4. **The late booking.** B012 is for NV1009, whose flight record only arrives in the
   2 July file. What is B012's quarantine status after day 1? After day 2?
5. **The USD fare.** B010 is 50.00 USD with 10.00 USD of extras, booked on 20 June. What
   are `fare_inr` and `ancillary_inr`?
6. **Load factor.** Using only the fixture files and `aircraft.csv`, compute the overall
   load factor by hand. Then compute the average of the per-flight load factors. Which
   one does `mart_booking_daily` give?
7. **On-time performance.** Which fixture flights count towards on-time performance, and
   what is it? (Watch the correction to NV1001 on 2 July.)
8. **Fare outliers.** Which fixture bookings are flagged as fare outliers? Would a single
   global threshold of "3 x IQR of all economy fares" flag the same ones?
9. **Full data.** Before opening the dashboard, predict which month has the worst
   on-time performance, and why. Then check.
10. **Full data.** Predict roughly how many bookings ended in quarantine as
    `WAITING_FOR_FLIGHT` and then `released`. (Hint: how many flights arrive late, and
    how many passengers does a flight carry?)

Answers for 1-8 are in the tests (`tests/test_*.py`) and in `EXECUTION_FLOW.md`; for 9
and 10, query the warehouse.

## 2. Break-it drills

Make **one** change at a time (on a scratch branch: `git switch -c break-it`), predict
what fails, run `pytest -q`, compare, then undo (`git restore .`).

1. **Remove the exact-duplicate filter.** In `sql/silver/flights_merge.sql`, change
   `WHERE copy_number = 1 AND reject_reason IS NULL` to `WHERE reject_reason IS NULL`.
2. **Drop the overnight roll-over.** In `sql/silver/00_macros.sql`, make `arrival_utc`
   always attach the departure's date (delete the `CASE` that adds a day).
3. **Make a join inner.** In `sql/gold/fact_booking.sql`, change
   `LEFT JOIN gold.dim_passenger` to `JOIN gold.dim_passenger`.
4. **Weaken the upsert guard.** In `sql/silver/bookings_merge.sql`, change
   `WHEN MATCHED AND incoming.updated_at_utc >= target.updated_at_utc THEN UPDATE` to
   `WHEN MATCHED THEN UPDATE`.
5. **Use a global outlier threshold.** In `sql/gold/fact_booking.sql`, compute
   `route_cabin_fare_range` over all bookings (remove `route_key, cabin` from the
   `GROUP BY` and join on `true`).
6. **Average the percentages.** In `dashboard/queries.py: headline_kpis()`, change load
   factor to `avg(m.passengers_flown / nullif(m.seats_offered, 0))`.
7. **Add a fallback key.** In `pipeline/settings.py: read_pii_key()`, return
   `"default-key-..."` instead of raising when the key is missing.
8. **Bring back the old bug.** In `pipeline/silver.py`, add a module-level
   `REJECTED = []` and append each batch's reject count to it.

<details>
<summary>Answers (open only after predicting)</summary>

Each answer was checked on 3 November 2026 by making the change in a scratch copy and
running `pytest -q`.

1. **Silver still has one row per flight**, because the version ranking keeps one row
   per key anyway. But each exact copy is now counted twice, as an exact duplicate *and*
   as an older version, so **reconciliation fails** and the run stops:
   `PipelineError: ... rows in but ... accounted for`. Most fixture tests fail because
   the warehouse never gets built. Lesson: reconciliation catches logic errors, not
   only lost rows.
2. The overnight arrival lands **before** its departure, so the scheduled duration is
   negative and `NV1003` is quarantined as `IMPOSSIBLE_DURATION`. Its three bookings
   then wait for a flight that never comes. `test_overnight_flight_survives...` fails,
   and so do the KPI tests (fewer passengers, seats and revenue). This is exactly the
   previous pipeline's bug.
3. **The tests still pass.** Every fixture booking's passenger profile made it into
   silver, so nothing is lost by the inner join. On the full data, bookings whose
   passenger profile was quarantined (`passenger_id` missing) would silently vanish
   from gold and the revenue would drop. Lesson: a passing test suite only proves what
   the fixtures cover. Fix: add a fixture booking whose passenger profile is
   quarantined, and a test that it still appears in `fact_booking` with
   `passenger_key = '-1'`.
4. **Nothing changes.** The `USING (...)` sub-query already drops rows where
   `older_than_silver` is true, so the stale B003 never reaches the `MERGE`. There are
   two guards; you removed one. Lesson: know which line is actually doing the work
   before you claim a rule is enforced, and ask whether a second guard is worth its
   extra complexity.
5. Three tests fail: `test_fare_outliers_use_route_and_cabin_thresholds` (with one
   global range the flagged set changes), `test_outlier_flag_is_used_downstream` (the
   mart's outlier count changes) and `test_every_page_query_runs` (the dashboard's
   outlier count changes).
6. `test_headline_kpis_match_the_hand_calculation` fails: the dashboard now averages
   route-day percentages and shows a different load factor from the hand calculation
   (14/90).
7. `test_missing_key_stops_before_touching_data` and `test_cli_exits_with_code_2...`
   fail. Worse, in real life every token would now be computable by anyone who reads
   the code.
8. `test_no_module_level_mutable_state` fails and names the file and line.

</details>

## 3. Rebuild drill (90 minutes, closed book)

In a new empty folder, using **only** `SQL_PATTERNS.md` and the DuckDB docs:

1. Load `data/landing/bookings/*.csv` and `data/landing/flights/*.json` into bronze
   tables as text, with the file name.
2. Build `silver_bookings`: standardise `flight_no`, parse both timestamp formats you
   see first, drop exact duplicates, keep the latest version per `booking_id`, and send
   rows with a missing ID or a fare <= 0 to a `quarantine` table with a reason.
3. Build `fact_booking` at one row per booking, joined to flights by an md5 key.
4. Compute load factor and revenue per route, sum ÷ sum.
5. Check: does rows in = loaded + duplicates + older + quarantined?

Then compare your numbers with this repo's `gold.mart_booking_daily`. Differences tell
you which rule you skipped.

## 4. Mock hackathon (5 November, timed)

```bash
python -m scripts.generate_mock_brief
```

It writes a new messy dataset about **baggage handling** and a problem statement to
`data/mock_hackathon/`. There is no solution in the repo. Give yourself 3 hours, follow
`HACKATHON_PLAYBOOK.md`, then do the 5-minute demo out loud, timed.
