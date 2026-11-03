# Decisions

Every meaningful choice in this project, written so you can defend it out loud.
Each entry has:

- **Context**: the problem.
- **Options**: what else was possible.
- **Choice**: what was done.
- **Why**: the reasoning.
- **If asked**: a one-line answer for the panel.

Entries are numbered in the order they were made. The phase is in brackets.

---

## D-001 A Python command line instead of a Makefile (Phase 0)

- **Context:** The project must run the same way on Windows, macOS and Linux.
- **Options:** a Makefile; shell scripts; Python modules run with `python -m ...`.
- **Choice:** Python modules, for example `python -m pipeline.run --date 2025-07-01`.
- **Why:** `make` is not installed on Windows by default, and shell scripts differ
  between operating systems. Python is already on every machine that runs this project.
- **If asked:** "The command is identical on every OS, and it needs nothing beyond Python."

## D-002 Develop on Python 3.11 (Phase 0)

- **Context:** Python 3.11 and 3.13 are both installed. The brief says 3.11 or newer.
- **Options:** develop on 3.13; develop on 3.11.
- **Choice:** The virtual environment uses 3.11. CI tests both 3.11 and 3.13.
- **Why:** Building on the oldest supported version stops newer-only features from
  slipping in. Python 3.11 also includes `tomllib`, so the config file needs no
  extra library.
- **If asked:** "Develop on the oldest version you support, and test on the newest."

## D-003 Pin each package to its newest release that is at least two weeks old (Phase 0)

- **Context:** On 2 Nov 2026, DuckDB 2.0.0 (a new major version) was 12 days old, and
  pandas 3.1.0 was 10 days old. The interview is on 6 Nov.
- **Options:** the latest of everything; the latest minus a safety margin.
- **Choice:** duckdb 1.5.6, faker 40.43.0, pandas 3.0.6, plotly 7.1.0, python-dotenv
  1.2.4, streamlit 1.66.0; for development, pytest 9.1.1, ruff 0.17.1, psutil 7.2.2.
- **Why:** Brand-new releases, and especially major versions, carry the most bugs and
  breaking changes. A few weeks of other people's bug reports is worth more here than
  the newest features.
- **If asked:** "I picked versions with a short track record over versions with none."

## D-004 Pin only the packages we use directly (Phase 0)

- **Context:** Pinning means fixing an exact version. Our packages bring their own
  dependencies too: streamlit, for example, brings in pyarrow and about 35 others.
- **Options:** pin only what we import; pin the whole tree with `pip freeze` (45 lines).
- **Choice:** Pin what we import in `requirements.txt` and `requirements-dev.txt`.
- **Why:** A freeze taken on Windows records whatever Windows happened to install, so
  it is not a reliable list for macOS and Linux. It is also too long to read. A lock
  tool (pip-tools or uv) is the proper way to pin everything, and it is listed below
  under ideas not implemented.
- **If asked:** "Exact versions for everything I import. A lock file is the next step
  if every transitive version has to match too."

## D-005 Three small additions to the stack (Phase 0, approved 2 Nov)

- **Context:** The brief's stack table does not list these three tools, but each one
  solves a problem the brief raises.
- **Choice:**
  - `python-dotenv` reads `.env` into environment variables, which is where the PII
    key lives.
  - `ruff` (development only) is a linter: it reads code and reports mistakes such as
    unused imports.
  - `psutil` (benchmarks only) measures the peak memory of the whole process,
    including memory DuckDB allocates outside Python. Python's built-in
    `tracemalloc` cannot see that memory.
- **If asked:** "Each one closes a gap the brief asked about: secrets, unused imports
  and honest memory numbers."

## D-006 What one day's files contain (Phase 0)

- **Context:** The brief says one file per source per day, but not what goes in each.
- **Options:**
  - (a) The bookings file holds bookings *made* that day, for flights weeks ahead.
  - (b) The bookings file is the passenger list for flights *departing* that day.
- **Choice:** (b). For each day D:
  - `flights_D.json` holds every flight leg scheduled for D, with what actually happened.
  - `bookings_D.csv` holds the bookings for flights departing on D.
  - `passengers_D.csv` holds new or changed customer profiles.
- **Why:** With (a), almost every booking would point at a flight that had not
  happened yet, so "waiting for its flight" would be normal rather than a defect. With
  (b), late-arriving data means something specific: the flight's record turned up
  after its bookings did.
- **If asked:** "I modelled the feed as an end-of-day departure manifest, so a booking
  without its flight is a real exception."

## D-007 One run handles one day; gold is rebuilt once per run (Phase 0)

- **Context:** We need daily runs, backfills over 184 days, and about a minute for
  the small profile.
- **Choice:** Bronze and silver process one day at a time, in date order. A backfill
  is a loop over days. Gold is rebuilt in full once, at the end of the run.
- **Why:** Processing day by day keeps late-arriving behaviour identical whether you
  run one day at a time or backfill. Rebuilding gold 184 times during a backfill would
  waste time, because only the final state is used. A full gold rebuild is cheap at
  this size. `docs/SCALING.md` explains how to rebuild only the changed partitions
  (slices of a table, such as one month) when data is larger.
- **If asked:** "Incremental where there is state to protect (silver), full rebuild
  where it is cheap (gold)."

## D-008 Fingerprint files by content; build batch IDs from the file (Phase 0)

- **Context:** The same file must never be loaded twice, and reruns must give
  identical results.
- **Choice:** `meta.file_log` stores a SHA-256 hash of each file's bytes. A hash is a
  fingerprint: change one byte and it changes completely. If the same hash arrives
  again, the file is skipped, even under a different name. The batch ID is built from
  the source, the file date and the first characters of the hash.
- **Why:** File names can change (a re-sent file may be renamed), but the bytes tell
  you whether the content is new. Random batch IDs, such as UUIDs, would make two runs
  over identical data look different.
- **If asked:** "Idempotency starts at ingestion: the same bytes in give the same IDs
  and load nothing new."

## D-009 Rule values in a TOML config file, rule logic in SQL (Phase 0)

- **Context:** The validation rules must come from one short, readable config file,
  without building a framework.
- **Choice:** `config/pipeline.toml` holds the sources, business keys, patterns and
  thresholds. Each silver SQL file has one `CASE` expression, and the first rule a
  row fails becomes its reason code. Values from the config reach the SQL as `$name`
  parameters.
- **Why:** You can read the rules top to bottom in one place, and changing a
  threshold does not touch code. A rules engine that generated SQL from config would
  be a framework, and much harder to explain.
- **If asked:** "Values live in config, and the logic is SQL you can read."

## D-010 Reconciliation counts replaced versions separately (Phase 0)

- **Context:** The brief's equation is rows in = rows loaded + duplicates removed +
  rows quarantined.
- **Choice:** rows in = loaded + exact duplicates + older versions replaced + quarantined.
- **Why:** An exact duplicate and an older version of a record are different
  problems. One combined number would hide which one went wrong. Adding the two
  middle terms together gives back the brief's equation.
- **If asked:** "I split duplicates into two buckets so that a mismatch points at its cause."

## D-011 How personal data is protected (Phase 0)

- **Context:** The data contains names, emails, phone numbers, dates of birth,
  passenger IDs and PNRs.
- **Choice:**
  - Passenger ID, PNR, email and phone become HMAC-SHA256 tokens. HMAC mixes the
    value with a secret key before hashing, so someone who guesses an email cannot
    reproduce its token without the key.
  - Full name is dropped.
  - Date of birth becomes an age band.
  - Quarantined rows are stored with the same masking.
- **Why:** Tokens are deterministic: the same input with the same key always gives
  the same token, so joins still work. A name has no analytical use, so keeping it in
  any form is risk with no benefit. An age band keeps what analysis needs from a birth
  date without identifying anyone.
- **Limitation:** Bronze keeps raw PII in the same DuckDB file as silver and gold. In
  production, bronze would live in separate storage with stricter access.
  `docs/ARCHITECTURE.md` explains this.
- **If asked:** "Tokenise what we join on, generalise what we analyse, drop the rest."

## D-012 Surrogate keys are an md5 of the natural key, plus an "unknown" row (Phase 0)

- **Context:** A surrogate key is an ID the warehouse creates for each dimension row,
  separate from the business's own IDs. Fact tables point at dimensions through these
  keys, so the keys must stay the same every time gold is rebuilt.
- **Options:**
  - Auto-increment numbers: these change on every rebuild.
  - DuckDB's `hash()`: not guaranteed to stay the same across DuckDB versions.
  - `md5` of the natural key.
- **Choice:** `md5` of the natural key, for example `md5('NV1234|2025-07-01')`.
  `dim_date` uses YYYYMMDD integers by convention. Every dimension has an "unknown"
  row with key `-1`, so a fact with a missing reference still joins instead of
  disappearing.
- **Trade-off:** 32-character text keys take more space than integers. At large
  scale, use a 64-bit integer hash instead.
- **If asked:** "Deterministic keys mean a rebuild never breaks the links that Power
  BI or anyone else relies on."

## D-013 Two marts at different grains, storing totals only (Phase 0)

- **Context:** A table's *grain* is what one row represents. A *mart* is a table
  shaped to answer one group of questions.
- **Choice:**
  - `mart_flight_daily`: one row per date and route.
  - `mart_booking_daily`: one row per date, route and cabin.

  Marts store totals (seats, passengers, revenue and so on). Ratios are calculated
  after filtering, as sum ÷ sum.
- **Why:**
  - Putting flight counts on the per-cabin table would count every flight once per cabin.
  - Averaging percentages weights a quiet day the same as a busy one. Example: on day
    1 one flight carries 180 people in 180 seats (100%); on day 2 four flights carry
    360 people in 720 seats (50%). The average of the percentages is 75%. The true
    load factor is 540 ÷ 900 = 60%.
- **If asked:** "Store totals, divide last."

## D-014 The dashboard reads the exported Parquet files (Phase 0)

- **Context:** DuckDB lets only one process write to a database file, and not while
  another process has the file open.
- **Choice:** The pipeline exports the gold and meta tables to Parquet (plus CSV for
  gold). The dashboard queries those files with an in-memory DuckDB.
- **Why:** The dashboard can stay open while the pipeline runs, and it reads exactly
  what Power BI reads.
- **If asked:** "The dashboard consumes the published layer, not the warehouse's
  working files."

## D-015 Two cabins (Phase 0)

- **Choice:** Economy (174 seats) and a small premium cabin called "Plus" (12 seats),
  on a 186-seat aircraft.
- **Why:** The cabin filter, and outlier thresholds per route and cabin, need at
  least two cabins.

## D-016 The small profile flies every route every day (Phase 0)

- **Context:** The brief suggested about 300,000 bookings. Twenty routes flying once
  a day gives about 3,700 flights. At 186 seats and roughly 75% full, that is about
  500,000 bookings (an estimate; Phase 1 records the real count). Reaching 300,000
  would mean only about 12 flights a day, which would thin out the delay heatmap and
  the aircraft-rotation pattern.
- **Choice:** Twenty flights a day for `small`. For `medium`, each route flies 6 times
  a day.
- **If asked:** "I sized the network to be realistic, let the row count follow, and
  then measured it."

## D-017 Checks that stop the run vs checks that only warn (Phase 0)

- **Rule:** Stop the run when continuing would publish wrong or unsafe numbers. Only
  warn when the numbers are still right but someone should look.
- **Stop (non-zero exit code):**
  - the PII key is missing
  - a file is missing a required column
  - reconciliation doesn't balance
  - more than 20% of a batch is quarantined
  - there are duplicate keys in silver or gold
  - a fact table has orphan keys
  - a KPI is impossible, such as load factor above 100%
- **Warn:**
  - a new column appeared
  - 5–20% of a batch is quarantined
  - fare outliers were flagged
  - flight status contradicted the actual times
  - bookings are still waiting for their flight
  - data is older than expected
- Bookings that are waiting for their flight do not count towards the quarantine
  percentage, because they are early, not bad. The 5% and 20% thresholds were
  provisional in Phase 0; see D-022 for the values after real runs.

## D-018 Ten airports, not twelve (Phase 1)

- **Context:** The brief said about 12 airports and listed 10.
- **Choice:** The 10 listed airports. 10 out-and-back city pairs give exactly 20
  routes, and 5 aircraft each fly 4 legs a day.
- **If asked:** "Every airport has a reason to be there; adding two would only add
  routes with no story."

## D-019 One transaction per step (Phase 3)

- **Context:** The first version committed every statement on its own. D: is a
  spinning hard disk, and every commit forces a disk write, so a day took about 2 s.
- **Options:** commit per statement; per batch; per step.
- **Choice:** The runner wraps each step (one day's bronze, one day's silver, gold,
  checks, export) in one transaction. If anything in the step fails, the whole step
  is rolled back and the failure is then recorded.
- **Why:** All-or-nothing is the easiest rule to reason about: a failed day leaves the
  warehouse exactly as it was. It also cut the commits to two a day.
- **If asked:** "A step either fully happens or never happened."

## D-020 Spell out the CSV format; checkpoint rarely (Phase 3)

- **Context:** Profiling showed DuckDB spent ~0.25 s per file guessing the CSV dialect
  (delimiter, quoting), and rewrote its main file every 16 MB of changes.
- **Choice:** Bronze passes the column names (already read from the header) and the
  dialect explicitly: 0.002 s per file. `checkpoint_threshold` is raised so the main
  file is rewritten once, when the run closes.
- **Result:** In back-to-back profiling runs the 184-day backfill went from 249 s to
  130 s. Timings on this laptop vary by up to 2x from run to run, so
  docs/BENCHMARKS.md records several measurements rather than one number.
- **If asked:** "I profiled before optimising: the time was in CSV sniffing and disk
  syncs, not in the SQL."

## D-021 Full refresh replays day by day (Phase 4)

- **Context:** The first full refresh replayed all 552 batches in one transaction and
  had not finished after 10 minutes: updating rows that are still uncommitted gets
  slower as the transaction grows.
- **Choice:** `--full-refresh` empties silver, then replays every day already in
  bronze, one transaction per day, with silver only allowed to see batches up to that
  day. It is literally the same code path as a backfill.
- **Why:** The same path means the same results: a test proves a full refresh
  rebuilds byte-identical silver and gold.
- **If asked:** "Rebuilding from raw is just a backfill that starts from an empty silver."

## D-022 Quarantine thresholds after real runs (Phase 3)

- **Context:** D-017 set 5% (warn) and 20% (stop) provisionally.
- **Finding:** On the small profile the worst booking or passenger batch rejects about
  1% of rows. Flight batches have only ~20 rows, so a single bad flight is 5% and
  trips the warning a few times; that is acceptable noise for a warning.
- **Choice:** Keep 5% and 20%. The hand-written test fixtures deliberately reject a
  quarter of day one, so the tests raise the limit to 50% and a separate test proves
  the real 20% limit stops the run.

## D-023 Late bookings wait in the quarantine table (Phase 3)

- **Options:** a separate "waiting room" table of typed rows; or the quarantine table
  with a status.
- **Choice:** One quarantine table with `status` = rejected, waiting or released.
  Waiting rows keep their (masked) record as JSON; every bookings batch re-reads them
  through exactly the same SQL as new rows (`bookings_check.sql`).
- **Why:** One place to look for "everything that is not in silver", and one code
  path, so a retried booking can never be treated differently from a new one.
  "Waiting" ends after `late_flight_grace_days` (3), counted from the date being
  processed, not today's clock, so replays give the same answer.

## D-024 Record JSON drops empty fields (Phase 3)

- **Context:** A full refresh first produced different quarantine records: by then
  bronze had gained the promo_code column, so old rows gained `"promo_code": null`.
- **Choice:** `row_json()` removes null fields, so an empty field and a missing
  column look the same.
- **If asked:** "Schema drift should not change the fingerprint of an old row."

## D-025 Passenger profiles are SCD Type 1 (Phase 3)

- **Context:** Loyalty tiers change over time.
- **Choice:** Overwrite: silver and dim_passenger hold the current tier only.
- **Why:** No question in the brief needs history ("what tier was this passenger
  when they flew?"). Type 2 (a new row per change with valid-from/valid-to dates) is
  explained in docs/CONCEPTS.md and is a change drill.

## D-026 What counts as a passenger and as revenue (Phase 4)

- **Choice:**
  - Passenger flown: a CONFIRMED booking on a flight that operated.
  - Revenue: CONFIRMED and NO_SHOW bookings on flights that operated (a no-show has
    paid). CANCELLED bookings, and every booking on a cancelled flight, are refunded.
- **Why:** Load factor must measure people on board, but revenue must measure money
  kept. Mixing them is a classic mistake.

## D-027 Two average delays, each with its population named (Phase 4)

- **Choice:** "Average arrival delay, all measured flights" counts early arrivals as 0
  and excludes flights without an actual arrival time. "Average delay of delayed flights"
  averages only flights more than 15 minutes late.
- **Why:** The two answer different questions (how late is a typical flight vs how bad
  is it when we are late), and on the small profile the two are about 23 and 60 minutes.

## D-028 Phase gates and commits (Phase 1)

- **Context:** After Phase 0, Karan asked for Phases 1-8 in one go, uncommitted.
- **Choice:** Each phase's command, output, suggested commit message and check
  questions are in docs/PHASE_LOG.md, so the history can still be committed phase by
  phase if wanted.

---

## Ideas not implemented

Each of these is a real tool that this project deliberately does not use.
`docs/SCALING.md` explains when each would become worthwhile.

| Tool | What it does | Why not here |
|---|---|---|
| Airflow | A scheduler that runs pipelines on a timetable, retries failed steps and shows run history | One machine and one daily job. An ordered list of steps plus `meta.pipeline_runs` covers it |
| dbt | Manages SQL transformation files: their order, tests and documentation | About 20 SQL files run in a fixed order. Plain SQL is also what the interview tests |
| Spark | Spreads a computation across many machines | The data fits on one laptop, and DuckDB handles millions of rows |
| Kafka | Moves a continuous stream of events between systems | The sources arrive as daily files, so this is a batch problem |
| Docker | Packages an app together with its whole environment | Docker does not run on this machine, and a venv with pinned versions is enough |
| Kubernetes | Runs many containers across a cluster | Nothing to orchestrate at this size |
| Cloud services (S3, ADLS, Snowflake, BigQuery…) | Hosted storage and warehouses | Runs locally for free with no account. `docs/SCALING.md` maps each local part to its cloud equivalent |
| An ORM such as SQLAlchemy | Maps tables to Python classes | It would hide the SQL that the interview tests |
| A custom framework | A home-made rules engine or step runner | It would be the hardest thing in the repo to explain. A plain list of steps does the job |
| A lock tool (pip-tools, uv) | Pins every transitive package, per OS | The next step if exact reproducibility of every package is needed (see D-004) |
