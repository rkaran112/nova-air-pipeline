-- Shared by every source: put this batch's failed rows into silver.quarantine.
-- Exact duplicates are not quarantined: they are counted, and their first copy
-- goes through the rules like any other row.

INSERT INTO silver.quarantine
SELECT md5($batch_id || '#' || _row_number) AS quarantine_id,
       $source                               AS source,
       $batch_id                             AS batch_id,
       _row_number                           AS row_number,
       reject_reason                         AS reason_code,
       CASE WHEN reject_reason = 'WAITING_FOR_FLIGHT' THEN 'waiting' ELSE 'rejected' END
                                             AS status,
       record_json                           AS record,
       flight_no,
       flight_date,
       $file_date                            AS file_date,
       NULL                                  AS resolved_batch_id
FROM checked_rows
WHERE row_origin = 'batch' AND copy_number = 1 AND reject_reason IS NOT NULL
