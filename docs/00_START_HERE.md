# Start here: a three-day study plan (3-5 November)

The interview is on **6 November**. The goal by then: you can explain any file,
function, query and decision in this repo without help, and you have rebuilt part of it
yourself under time pressure.

Rules for all three days:

- **Run before you read.** Every section below starts with a command. See the output,
  then read the code that produced it.
- **Say it out loud.** After each file, explain it in two sentences as if to the panel.
  If you can't, reread it or ask: if the code is too clever, it should be simplified.
- Keep a notes file of every question you could not answer. Day 3 starts there.

## Before day 1 (30 minutes, 2 November evening)

```bash
python -m scripts.check_env
```

```bash
python -m scripts.generate_data
```

```bash
python -m pipeline.run --start 2025-07-01 --end 2025-12-31
```

```bash
streamlit run dashboard/app.py
```

Click through all four pages. Don't try to understand anything yet. Notice what
surprises you. **Don't open `GENERATOR_ANSWER_KEY.md` or `scripts/datagen/patterns.py`.**

## Day 1 (3 November): the shape of the whole thing

| Time | Do | Read |
|---|---|---|
| 1 h | `python -m scripts.profile_landing` and look at a few raw files in `data/landing/` | `README.md`, `docs/ARCHITECTURE.md` |
| 1 h | Follow three rows through the layers with the "Try it" block | `docs/EXECUTION_FLOW.md` |
| 1.5 h | Read the code in this order: `pipeline/run.py` → `bronze.py` → `silver.py` → `checks.py` → `gold.py` | each file top to bottom |
| 1 h | Read the SQL in this order: `sql/silver/00_macros.sql` → `flights_check.sql` → `flights_merge.sql` → `bookings_check.sql` → `bookings_merge.sql` → `quarantine_rejects.sql` | |
| 45 min | `docs/CONCEPTS.md`: for each concept, find it in the code yourself before reading the "Here" line | |
| 30 min | `DECISIONS.md` D-001 to D-017 | |

**End of day 1 check:** draw the architecture from memory, with table names, and explain
what happens to a duplicate booking, a late booking and an overnight flight.

## Day 2 (4 November): gold, KPIs, tests, SQL

| Time | Do | Read |
|---|---|---|
| 1 h | Open each `sql/gold/*.sql`; say its grain out loud before reading the header | `docs/DATA_DICTIONARY.md` |
| 45 min | Work out load factor, on-time performance and revenue on the fixtures by hand, then run `pytest tests/test_kpis.py -q` | `tests/test_kpis.py` |
| 1 h | `pytest -q`; read `tests/conftest.py`, then two test files of your choice | |
| 1.5 h | Run every snippet in `docs/SQL_PATTERNS.md`; then rewrite three of them from memory | |
| 1 h | Practice drills: all **trace drills** and **break-it drills** | `docs/PRACTICE_DRILLS.md` |
| 30 min | Find the six hidden patterns on the dashboard **yourself**; write them down; then check `GENERATOR_ANSWER_KEY.md` | |

**End of day 2 check:** answer `INTERVIEW_QA.md` questions 1-30 out loud, without
looking.

## Day 3 (5 November): rehearse the day

| Time | Do |
|---|---|
| 30 min | Read `docs/HACKATHON_PLAYBOOK.md` fully |
| **3 h, timed** | **Mock hackathon:** `python -m scripts.generate_mock_brief`, then follow `data/mock_hackathon/BRIEF.md`. No looking at this repo's code except `SQL_PATTERNS.md` |
| 15 min | Record yourself giving the 5-minute demo of your mock solution |
| 45 min | Change drills: do E1, E3, M1 and M8 in `docs/CHANGE_DRILLS.md` on a scratch branch, timed |
| 45 min | `INTERVIEW_QA.md` 31-47; `docs/SCALING.md` mapping table; `docs/ETL_VS_ELT.md` |
| 30 min | Your notes file: every unanswered question from days 1-3 |

**Evening of day 3:** rest. On the morning of the 6th, skim the playbook's first 15
minutes and the demo script, nothing else.

## If you only have 2 hours

1. `README.md` and `docs/ARCHITECTURE.md` (20 min)
2. `docs/EXECUTION_FLOW.md` (30 min)
3. `docs/HACKATHON_PLAYBOOK.md` (30 min)
4. `docs/INTERVIEW_QA.md` (40 min)
