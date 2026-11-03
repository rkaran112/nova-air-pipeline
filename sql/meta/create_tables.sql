-- The four layers, plus the tables that record what the pipeline did.
-- Every statement is safe to run again: it only creates what is missing.

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS meta;

-- One row per file ever loaded. The content hash is the key, so the same bytes
-- are never loaded twice, whatever the file is called.
CREATE TABLE IF NOT EXISTS meta.file_log (
    content_hash VARCHAR PRIMARY KEY,
    file_name    VARCHAR NOT NULL,
    source       VARCHAR NOT NULL,
    file_date    DATE,
    batch_id     VARCHAR NOT NULL,
    rows_in      BIGINT  NOT NULL,
    run_id       VARCHAR NOT NULL,
    loaded_at    TIMESTAMP NOT NULL
);

-- One row per step per run: what ran, for which date, how long, how many rows.
CREATE TABLE IF NOT EXISTS meta.pipeline_runs (
    run_id           VARCHAR NOT NULL,
    step             VARCHAR NOT NULL,
    target           VARCHAR,
    status           VARCHAR NOT NULL,
    started_at       TIMESTAMP NOT NULL,
    duration_seconds DOUBLE,
    rows_in          BIGINT,
    rows_out         BIGINT,
    rows_quarantined BIGINT,
    message          VARCHAR
);

-- Columns that appeared in, or vanished from, a source file.
CREATE TABLE IF NOT EXISTS meta.schema_changes (
    batch_id    VARCHAR NOT NULL,
    source      VARCHAR NOT NULL,
    column_name VARCHAR NOT NULL,
    change      VARCHAR NOT NULL,
    run_id      VARCHAR NOT NULL
);

-- Every data quality count, with its severity: info, warn or block.
CREATE TABLE IF NOT EXISTS meta.dq_results (
    run_id     VARCHAR NOT NULL,
    batch_id   VARCHAR,
    source     VARCHAR NOT NULL,
    check_name VARCHAR NOT NULL,
    severity   VARCHAR NOT NULL,
    row_count  BIGINT  NOT NULL
);

-- One row per batch that silver has processed: the balance sheet for its rows.
-- rows_in = loaded + exact duplicates + older versions + quarantined.
CREATE TABLE IF NOT EXISTS meta.reconciliation (
    batch_id              VARCHAR PRIMARY KEY,
    source                VARCHAR NOT NULL,
    file_date             DATE,
    rows_in               BIGINT NOT NULL,
    rows_loaded           BIGINT NOT NULL,
    rows_exact_duplicate  BIGINT NOT NULL,
    rows_older_version    BIGINT NOT NULL,
    rows_quarantined      BIGINT NOT NULL,
    balanced              BOOLEAN NOT NULL,
    run_id                VARCHAR NOT NULL
)
