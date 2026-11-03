# CLAUDE.md

Guidance for Claude Code sessions working in this repo.

## What this is

Nova Air is a fictional Indian low-cost airline. This repo is a batch ELT pipeline
built as a **study blueprint** for Karan's data engineering interview at Akasa on
6 Nov 2026. On the day he gets an unseen hackathon problem, so this project has to
be easy to understand, rebuild and adapt under time pressure.

Priorities, in order: (1) Karan can explain every file, function, query and decision
unaided; (2) the structure transfers to a new dataset; (3) it reads well on a resume.
If something would be hard for him to explain, simplify the code rather than adding
more documentation.

```
landing files → bronze (raw text) → silver (clean + quarantine) → gold (star schema + marts)
             → Parquet/CSV exports → Streamlit dashboard and Power BI
```

## Working agreement

- Work in the phases below. After each phase, stop and give: what was built, the
  exact command, real output from running it, a suggested commit message and three
  questions that test understanding. Then wait for Karan to say "next".
- Karan makes the commits. The repo's git identity is set locally to `rkaran112`
  (`155136413+rkaran112@users.noreply.github.com`). Never add Co-Authored-By or any
  other trailer that credits Claude.
- Ask before choices that materially change the design. Otherwise take the simplest
  reasonable option and record it in `DECISIONS.md`.
- Never claim something works without running it. Never invent numbers: every metric
  in docs or resume bullets must come from a real run.
- Ask before pushing to GitHub or creating a remote repo.

| Phase | Output | Status |
|---|---|---|
| 0 | Plan, repo setup, this file, environment | done |
| 1 | Data generator (`scripts/generate_data.py`) | built, awaiting review |
| 2 | Bronze + run logging | built, awaiting review |
| 3 | Silver + quarantine + PII masking | built, awaiting review |
| 4 | Gold star schema + KPI marts | built, awaiting review |
| 5 | Runner, backfill, idempotency | built, awaiting review |
| 6 | Streamlit dashboard + screenshots | built, awaiting review |
| 7 | Tests, CI, benchmarks | built; CI not yet run on GitHub |
| 8 | Learning documents | built, awaiting review |

Phases 1-8 were built in one pass at Karan's request, uncommitted; each phase's
command, output, commit message and questions are in `docs/PHASE_LOG.md`.

Update the Status column when a phase is accepted.

## Commands

Run everything from the repo folder with the venv active. Use `python -m <module>`
throughout. There is no Makefile, because the project must run the same way on
Windows, macOS and Linux.

```bash
python -m scripts.check_env                                   # versions, PII key, disk; exit 1 if not ready
python -m scripts.generate_data                               # small profile, seed 42 -> data/landing
python -m scripts.generate_data --profile medium              # ~3M bookings
python -m scripts.profile_landing --defects                   # SQL profile + planted-defect check
python -m pipeline.run --date 2025-07-01                      # one day
python -m pipeline.run --start 2025-07-01 --end 2025-12-31    # backfill
python -m pipeline.run --full-refresh                         # rebuild silver/gold from bronze
streamlit run dashboard/app.py                                # dashboard (reads data/exports)
pytest -q                                                     # tests (fixtures, no data needed)
ruff check .                                                  # lint
python -m scripts.benchmark                                   # writes docs/BENCHMARKS.md
python -m scripts.update_doc_numbers                          # refills numbers in the docs
python -m scripts.generate_mock_brief                         # mock hackathon -> data/mock_hackathon
```

After any change that alters numbers, rerun the pipeline and
`python -m scripts.update_doc_numbers`, and never edit a number inside a
`<!-- numbers:... -->` block by hand.

## Stack

Python 3.11+ (the venv is built on 3.11 on purpose), DuckDB with plain `.sql` files,
Parquet and CSV exports, Streamlit + Plotly, pytest, ruff, and one GitHub Actions
workflow. Exact versions are in `requirements*.txt`.

Do not add Airflow, dbt, Spark, Kafka, Docker, Kubernetes, cloud services, an ORM or a
custom framework. These belong in `DECISIONS.md` under "Ideas not implemented" and in
`docs/SCALING.md`. Any new dependency needs Karan's approval.

## Layer rules

- **Landing** (`data/landing/`): one file per source per day, as delivered. Read only.
- **Bronze**: every field stored as text, plus `_source_file`, `_batch_id` and
  `_ingested_at`. Never update or delete bronze rows. `meta.file_log` records each
  file's content hash, so the same bytes are never loaded twice. Batch IDs come from
  the file, never from randomness, so reruns are identical.
- **Silver**: one SQL file per source. A `CASE` checks the rules in a fixed order, and
  the first rule a row fails becomes its reason code. Rejected rows go to
  `silver.quarantine`; nothing is silently dropped. Rows are updated or inserted on the
  business key, and an older version never overwrites a newer one.
- **PII**: raw personal data may exist only in landing and bronze. Silver and later
  layers hold HMAC-SHA256 tokens keyed by `NOVA_PII_KEY`. If the key is missing the
  run must stop with a clear error, and there is never a fallback key. Full name is
  dropped and date of birth becomes an age band.
- **Gold**: rebuilt in full on each run. Each SQL file states its grain in the header.
  Surrogate keys are `md5` of the natural key. Facts join to dimensions only through
  surrogate keys, and every dimension has an "unknown" row. Marts store totals only;
  ratios are calculated after filtering, as sum ÷ sum.
- **Dashboard**: reads only the exported gold and meta Parquet files, never the
  DuckDB file (DuckDB won't let the pipeline write while another process holds the
  file open) and never raw PII.
- **Checks**: stop the run when continuing would publish wrong or unsafe numbers.
  Only warn when the numbers are still right but someone should look.
  Reconciliation (rows in = loaded + duplicates + replaced versions + quarantined)
  stops the run if it fails.

## Code rules

- Short functions with one job each. Prefer plain functions to classes. Prefer clear,
  slightly longer code to clever one-liners.
- Comments explain why, not what.
- No module-level mutable state (lists, dicts or sets at module level). Constants are
  tuples or plain values. Pass connections and paths in as arguments.
- No unused imports, dead code or placeholder TODOs. `ruff check .` must pass.
- No blanket warning filters. pytest treats warnings as errors; any exception must be
  specific and give its reason.
- SQL: set-based, never row-by-row Python. Name each CTE after what its step does
  (for example `latest_booking_version`). Pass values in as `$name` parameters.
- Any flag that is calculated must be used downstream.
- Keep secrets (`.env`) and generated data (`data/`) out of Git.

These rules exist because Karan's previous airline pipeline had these bugs. Each one
needs a regression test or a review check:

- overnight-flight logic was inverted
- PII was hashed without a key
- a flag was calculated but never used
- surrogate keys were never joined
- cancellation rate was never calculated
- outlier thresholds were global
- bad rows were silently dropped
- warnings were suppressed
- there were unused imports
- a module-level list accumulated rejected rows across runs

## Writing docs

Use simple English. Before naming a term, say what it does in plain language with an
example from this project. Every command and number in a doc must have come from a
real run. The hidden business patterns appear only in `docs/GENERATOR_ANSWER_KEY.md`
and `scripts/datagen/patterns.py`; never hint at them in analysis code, SQL comments or
other docs. `docs/CHANGE_DRILLS.md` describes changes for Karan to attempt; do not
implement them on `main`.

## Machine notes

- Windows 11. The C: drive is nearly full, so keep the venv, data and DuckDB files in
  this repo on D:. pip installs here used `--no-cache-dir` to keep C: clear.
- Docker does not run on this machine. Nothing may depend on it.
- For web browsing and dashboard screenshots, use the gstack `/browse` skill.
