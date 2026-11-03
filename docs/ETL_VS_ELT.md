# ETL vs ELT

## The difference in one sentence

**ETL** cleans data in your own code *before* loading it into the warehouse; **ELT**
loads the raw data first and cleans it *inside* the warehouse with SQL.

## This pipeline is ELT

1. **Extract:** the files arrive in `data/landing/`.
2. **Load:** `pipeline/bronze.py` copies them into `bronze.*` as text, unchanged.
3. **Transform:** `sql/silver/*.sql` and `sql/gold/*.sql` run inside DuckDB.

## One step both ways: standardising flight numbers and removing duplicates

### As ELT (what this repo does)

The raw rows are already in `bronze.flights`. One SQL statement transforms the whole
batch at once:

```sql
WITH numbered_copies AS (
    SELECT *,
           row_number() OVER (PARTITION BY record_json ORDER BY _row_number) AS copy_number
    FROM with_record
)
SELECT upper(regexp_replace(flight_no, '[\s-]', '', 'g')) AS flight_no, ...
FROM numbered_copies
WHERE copy_number = 1
```

### As ETL (how it would look in Python before loading)

```python
import csv

def clean_bookings(path):
    seen = set()
    clean = []
    with open(path, newline="") as file:
        for row in csv.DictReader(file):
            fingerprint = tuple(row.values())
            if fingerprint in seen:
                continue  # exact duplicate
            seen.add(fingerprint)
            row["flight_no"] = row["flight_no"].replace(" ", "").replace("-", "").upper()
            clean.append(row)
    return clean  # then INSERT these into the warehouse
```

Note: in ETL the raw rows never reach the warehouse. If the cleaning had a bug, the
original values are gone unless you kept the files.

## How to choose

| Question | Points to ELT | Points to ETL |
|---|---|---|
| Is the warehouse strong and cheap to compute in? (DuckDB, Snowflake, BigQuery, Databricks) | Yes | |
| Do analysts need to re-run transformations on raw data later? | Yes: raw is in bronze | |
| Must sensitive data never land in the warehouse at all? | | Yes: mask before loading |
| Is the transformation hard to express in SQL (ML scoring, parsing PDFs, calling an API)? | | Yes: do it in code |
| Is the volume tiny and the target a plain operational database? | | Often fine either way |
| Do you want transformations to be testable SQL files in version control? | Yes (this is what dbt is built on) | |

**The honest answer is usually "ELT, with a little ETL at the edges."** This project does
exactly that: PII tokenisation runs as a Python function, but it is *called from SQL*
inside the warehouse, and the raw values are still in bronze. If the requirement is "raw PII
must never enter the warehouse", the change is to tokenise in Python during the bronze
load, which turns that one step into ETL.

## A one-line answer to "ETL or ELT?"

"ELT: I land raw data unchanged so I can always replay it, and do set-based
transformations in SQL inside the warehouse. I'd move a step to ETL when the data must
not land raw, or the logic can't be expressed in SQL."
