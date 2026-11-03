-- Small reusable SQL functions (DuckDB calls them macros) shared by the silver files.
-- TEMP means they live only for this connection, so creating them writes nothing to disk.
-- India has no daylight saving, so IST is always UTC + 5 hours 30 minutes.

-- Parse a timestamp written in any of the three formats the sources use, into UTC.
--   2025-07-01T00:30:00Z        UTC
--   2025-07-01 06:00:00+05:30   IST with its offset
--   01/07/2025 06:00            no zone written: the sources use IST, so treat it as IST
-- Anything else gives NULL, which the rules then report as BAD_TIMESTAMP.
CREATE OR REPLACE TEMP MACRO parse_utc(text_value) AS
    CASE
        WHEN text_value LIKE '%Z'
            THEN try_strptime(text_value, '%Y-%m-%dT%H:%M:%SZ')
        WHEN text_value LIKE '%+05:30'
            THEN try_strptime(left(text_value, 19), '%Y-%m-%d %H:%M:%S') - INTERVAL 330 MINUTE
        ELSE try_strptime(text_value, '%d/%m/%Y %H:%M') - INTERVAL 330 MINUTE
    END;

CREATE OR REPLACE TEMP MACRO to_ist(utc_value) AS utc_value + INTERVAL 330 MINUTE;

CREATE OR REPLACE TEMP MACRO is_time_only(text_value) AS
    regexp_full_match(trim(text_value), '\d{1,2}:\d{2}');

-- An arrival written as a time only ("02:05") belongs to the departure's IST date,
-- unless that would put it at or before the departure: then the flight crossed
-- midnight and the arrival is on the next day. This is the overnight-flight rule.
CREATE OR REPLACE TEMP MACRO arrival_utc(arrival_text, departure_utc) AS
    CASE
        WHEN arrival_text IS NULL OR departure_utc IS NULL THEN NULL
        WHEN is_time_only(arrival_text) THEN
            CASE
                WHEN CAST(to_ist(departure_utc) AS DATE) + CAST(trim(arrival_text) AS TIME)
                     > to_ist(departure_utc)
                    THEN CAST(to_ist(departure_utc) AS DATE) + CAST(trim(arrival_text) AS TIME)
                ELSE (CAST(to_ist(departure_utc) AS DATE) + 1)
                     + CAST(trim(arrival_text) AS TIME)
            END - INTERVAL 330 MINUTE
        ELSE parse_utc(arrival_text)
    END;

-- A row as JSON, without its empty fields. Dropping nulls means a row looks the
-- same whether a column was empty or did not exist yet (promo_code before October),
-- so replaying old files after a schema change gives identical records.
CREATE OR REPLACE TEMP MACRO row_json(row_struct) AS
    regexp_replace(
        regexp_replace(CAST(to_json(row_struct) AS VARCHAR), ',"[^"]*":null', '', 'g'),
        '"[^"]*":null,?', '', 'g');

-- NV-1234, nv1234 and " NV 1234 " all mean NV1234.
CREATE OR REPLACE TEMP MACRO standard_flight_no(text_value) AS
    upper(regexp_replace(text_value, '[\s-]', '', 'g'));

CREATE OR REPLACE TEMP MACRO minutes_between(start_value, end_value) AS
    date_diff('minute', start_value, end_value);

-- Completed years between a date of birth and a given day.
CREATE OR REPLACE TEMP MACRO age_on(birth_text, on_day) AS
    date_sub('year', try_cast(birth_text AS DATE), on_day);

-- Age band from date of birth. Bands are wide on purpose: an exact birth date
-- helps identify a person, a band only helps analysis.
CREATE OR REPLACE TEMP MACRO age_band(birth_text, on_day) AS
    CASE
        WHEN try_cast(birth_text AS DATE) IS NULL THEN 'UNKNOWN'
        WHEN age_on(birth_text, on_day) < 25 THEN 'Under 25'
        WHEN age_on(birth_text, on_day) < 35 THEN '25-34'
        WHEN age_on(birth_text, on_day) < 45 THEN '35-44'
        WHEN age_on(birth_text, on_day) < 60 THEN '45-59'
        ELSE '60+'
    END
