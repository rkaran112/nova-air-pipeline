-- gold.dim_delay_reason
-- Grain: one row per delay code, plus a "no delay code" row and an "unknown" row
-- (delay_reason_key '-1') for codes missing from the reference list.
-- Key: delay_reason_key = md5(delay_code).

CREATE OR REPLACE TABLE gold.dim_delay_reason AS
SELECT md5(delay_code) AS delay_reason_key,
       delay_code,
       description,
       category
FROM silver.delay_codes
UNION ALL
SELECT md5('NONE'), 'NONE', 'No delay code recorded', 'No delay'
UNION ALL
SELECT '-1', 'UNK', 'Code not in the reference list', 'Unknown'
