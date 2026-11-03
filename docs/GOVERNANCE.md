# Data governance

Governance here means three things you can check: who the data is about (privacy),
whether it can be trusted (quality), and where it came from (lineage). Each control
below says where it lives in the code and which test proves it.

| Control | What it does | Where | Proved by |
|---|---|---|---|
| **Classification** | Every source column has a label: `public`, `internal` or `pii` | `[classification.*]` in `config/pipeline.toml` | `tests/test_governance.py` |
| **Unlabelled-column warning** | A column that arrives without a label is logged as a warning in `meta.dq_results` (it can never reach silver, which reads named columns) | `warn_unclassified` in `pipeline/bronze.py` | `test_only_the_unlabelled_fixture_column_is_flagged` |
| **Pseudonymisation** | `pii` identifiers become keyed HMAC-SHA256 tokens in the first silver step, so they still join but cannot be reversed without the key. The run refuses to start without the key | `pipeline/pii.py`, `sql/silver/*_check.sql` | `tests/test_pii.py` |
| **Minimisation** | Names are dropped (no analysis needs them) and dates of birth become age bands | `sql/silver/passengers_check.sql` | `test_no_raw_pii_in_silver_gold_or_meta` |
| **No raw PII downstream** | Silver, gold, the meta tables and every exported Parquet/CSV file are searched for every raw `pii` value in the fixtures. The list of `pii` columns comes from the labels above | `tests/test_pii.py` | the same tests |
| **Data quality** | Rejected rows go to a quarantine table with the rule they failed; every batch must reconcile (rows in = loaded + duplicates + older versions + quarantined) or the run stops | `pipeline/checks.py`, `sql/silver/quarantine_rejects.sql` | `tests/test_reconciliation.py` |
| **Lineage** | Every bronze row keeps its source file, batch id, ingest time and row number; loaded files are logged by content hash | `meta.file_log`, `_source_file` and friends | `tests/test_bronze.py` |
| **Schema-drift log** | A column that appears or disappears is recorded in `meta.schema_changes` | `align_table` in `pipeline/bronze.py` | `test_new_column_is_added_and_logged` |
| **Catalog** | Every gold table and KPI is defined in plain language | `docs/DATA_DICTIONARY.md` | n/a |

## What this does not do

- **Bronze still holds raw personal data**, in the same DuckDB file as silver and gold.
  Nobody is stopped from opening the file; there are no users, roles or access control.
- **There is no retention purge.** Blanking old raw values in bronze would break
  `--full-refresh`, which rebuilds silver (and its tokens) from bronze. In production,
  tokenise at the landing boundary, or keep raw values in a separate restricted store
  with a retention period, and let the warehouse hold tokens only.
- The data is synthetic. Nothing here is a legal compliance claim (for example, DPDP Act).
