-- Silver tables: clean, typed, one row per business key, no raw personal data.
-- All times are stored in UTC; IST is added in gold for reporting.

CREATE TABLE IF NOT EXISTS silver.flights (
    flight_no       VARCHAR NOT NULL,
    flight_date     DATE    NOT NULL,   -- scheduled departure date, IST
    origin          VARCHAR NOT NULL,
    destination     VARCHAR NOT NULL,
    sched_dep_utc   TIMESTAMP NOT NULL,
    sched_arr_utc   TIMESTAMP NOT NULL,
    actual_dep_utc  TIMESTAMP,
    actual_arr_utc  TIMESTAMP,
    aircraft_reg    VARCHAR,
    status          VARCHAR NOT NULL,   -- OPERATED or CANCELLED
    delay_code      VARCHAR,
    actuals_cleared BOOLEAN NOT NULL,   -- cancelled, but the feed sent actual times
    actuals_missing BOOLEAN NOT NULL,   -- operated, but the feed has no actual times
    updated_at_utc  TIMESTAMP NOT NULL,
    batch_id        VARCHAR NOT NULL,
    PRIMARY KEY (flight_no, flight_date)
);

CREATE TABLE IF NOT EXISTS silver.passengers (
    passenger_token VARCHAR PRIMARY KEY,  -- HMAC token of passenger_id
    email_token     VARCHAR,
    phone_token     VARCHAR,
    age_band        VARCHAR NOT NULL,
    loyalty_tier    VARCHAR NOT NULL,
    updated_at_utc  TIMESTAMP NOT NULL,
    batch_id        VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS silver.bookings (
    booking_id      VARCHAR PRIMARY KEY,
    pnr_token       VARCHAR,
    passenger_token VARCHAR NOT NULL,
    flight_no       VARCHAR NOT NULL,
    flight_date     DATE    NOT NULL,
    cabin           VARCHAR NOT NULL,
    fare_amount     DECIMAL(12, 2) NOT NULL,  -- as sent, in the original currency
    currency        VARCHAR NOT NULL,
    fx_rate         DOUBLE  NOT NULL,         -- 1.0 for INR
    fare_inr        DECIMAL(12, 2) NOT NULL,
    ancillary_inr   DECIMAL(12, 2) NOT NULL,
    channel         VARCHAR NOT NULL,
    status          VARCHAR NOT NULL,         -- CONFIRMED, NO_SHOW or CANCELLED
    promo_code      VARCHAR,
    booked_at_utc   TIMESTAMP,
    updated_at_utc  TIMESTAMP NOT NULL,
    batch_id        VARCHAR NOT NULL
);

-- Every row that did not make it into silver, and why. Nothing is dropped silently.
-- status: rejected (final), waiting (a booking whose flight has not arrived yet),
-- released (a waiting booking that later found its flight and was loaded).
CREATE TABLE IF NOT EXISTS silver.quarantine (
    quarantine_id     VARCHAR PRIMARY KEY,  -- md5 of batch id and row number
    source            VARCHAR NOT NULL,
    batch_id          VARCHAR NOT NULL,
    row_number        BIGINT  NOT NULL,     -- points back to the bronze row
    reason_code       VARCHAR NOT NULL,
    status            VARCHAR NOT NULL,
    record            VARCHAR NOT NULL,     -- the original row as JSON, PII masked
    flight_no         VARCHAR,
    flight_date       DATE,
    file_date         DATE,
    resolved_batch_id VARCHAR
)
