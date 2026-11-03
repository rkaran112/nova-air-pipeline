# Data dictionary: gold tables

Every gold table, its **grain** (what one row means), where it comes from, and every
column. All gold tables are rebuilt from silver on every run by `sql/gold/<table>.sql`.

Key convention: surrogate keys are `md5` of the natural key (text, 32 characters), so
they are the same after every rebuild. `dim_date` uses `YYYYMMDD` integers. Every
dimension has an "unknown" row with key `'-1'` (or `-1` for dates).

## dim_date
**Grain:** one row per calendar day from the first to the last flight date, plus unknown.
**Source:** generated from the range of `silver.flights.flight_date`.

| Column | Meaning |
|---|---|
| date_key | YYYYMMDD integer, e.g. 20250701 |
| calendar_date | The date |
| year, month, quarter, week_of_year | Calendar parts |
| month_label | e.g. `Jul 2025` |
| day_of_week | 1 = Monday ... 7 = Sunday |
| day_name | e.g. `Tuesday` |
| is_weekend | Saturday or Sunday |

## dim_airport
**Grain:** one row per airport, plus unknown. **Source:** `silver.airports`.

| Column | Meaning |
|---|---|
| airport_key | md5(airport_code) |
| airport_code | IATA code, e.g. `BLR` |
| airport_name, city, state | Descriptive |
| latitude, longitude | Degrees, used for route distance |

## dim_route
**Grain:** one row per direction flown (BLR-BOM and BOM-BLR are different routes), plus
unknown. **Source:** distinct origin/destination in `silver.flights` + `silver.airports`.

| Column | Meaning |
|---|---|
| route_key | md5('ORIGIN-DESTINATION') |
| route_code | e.g. `BLR-BOM` |
| origin, destination | Airport codes |
| origin_airport_key, destination_airport_key | Keys into dim_airport |
| distance_km | Great-circle distance, rounded to whole km |

## dim_aircraft
**Grain:** one row per registration, plus unknown (0 seats). **Source:** `silver.aircraft`.

| Column | Meaning |
|---|---|
| aircraft_key | md5(aircraft_reg) |
| aircraft_reg | e.g. `VT-NAA` |
| aircraft_type | e.g. `A320neo` |
| seats_plus, seats_economy, seats_total | Seats by cabin |

## dim_passenger
**Grain:** one row per passenger, current profile only (SCD Type 1), plus unknown.
**Source:** `silver.passengers`. Contains no raw personal data.

| Column | Meaning |
|---|---|
| passenger_key | md5(passenger_token) |
| passenger_token | HMAC-SHA256 of passenger_id |
| age_band | `Under 25`, `25-34`, `35-44`, `45-59`, `60+` or `UNKNOWN` |
| loyalty_tier | `NONE`, `BLUE`, `SILVER`, `GOLD` |
| has_email, has_phone | Whether contact details exist (the values are not kept here) |

## dim_delay_reason
**Grain:** one row per delay code, plus `NONE` (no delay code) and unknown.
**Source:** `silver.delay_codes`.

| Column | Meaning |
|---|---|
| delay_reason_key | md5(delay_code) |
| delay_code | IATA-style code, e.g. `93` |
| description | e.g. `Late arrival of aircraft from previous leg` |
| category | Weather, Reactionary, Technical, Crew, Air traffic control, Ground handling, Passenger, No delay, Unknown |

## fact_flight
**Grain:** one row per scheduled flight leg (flight_no + flight_date), operated or not.
**Source:** `silver.flights` + dimension keys.

| Column | Meaning |
|---|---|
| flight_key | md5(flight_no \|\| '\|' \|\| flight_date) |
| date_key, route_key, origin_airport_key, destination_airport_key, aircraft_key, delay_reason_key | Keys into the dimensions |
| flight_no, flight_date, status | Kept on the fact for convenience (a "degenerate dimension") |
| is_operated, is_cancelled | Status as flags |
| sched_dep_utc, sched_arr_utc, actual_dep_utc, actual_arr_utc | Times in UTC |
| sched_dep_ist, sched_dep_hour_ist | Scheduled departure in IST, and its hour, for reporting |
| scheduled_block_minutes | Scheduled gate-to-gate minutes |
| departure_delay_minutes, arrival_delay_minutes | Actual minus scheduled (negative = early); NULL if unknown |
| is_on_time | Arrived within 15 minutes of schedule; NULL if not measurable |
| actuals_missing | Operated, but the feed sent no actual time (excluded from punctuality) |
| actuals_cleared | Cancelled, but the feed sent actual times, which were removed |
| aircraft_leg_number | 1 for the aircraft's first flight of the day, 2 for its second... |
| seats_offered | Aircraft seats if operated, else 0 |
| distance_km | From dim_route |
| ask | Available seat-km: seats_offered x distance_km |

## fact_booking
**Grain:** one row per booking, which is one passenger on one flight.
**Source:** `silver.bookings` joined to `fact_flight`.

| Column | Meaning |
|---|---|
| booking_key | md5(booking_id) |
| flight_key, date_key, route_key, passenger_key | Keys |
| booking_id, cabin, channel, status, promo_code | Descriptive (`promo_code` exists from 1 Oct) |
| original_currency | `INR` or `USD` as sent |
| fare_inr, ancillary_inr | Amounts in rupees (USD converted at the booking-day rate) |
| is_flown | CONFIRMED booking on an operated flight: a passenger on board |
| is_revenue | CONFIRMED or NO_SHOW on an operated flight: money kept |
| fare_revenue_inr, ancillary_revenue_inr | The amounts if is_revenue, else 0 |
| rpk | Revenue passenger-km: distance_km if is_flown, else 0 |
| is_fare_outlier | Fare beyond 3 x IQR of its route and cabin |
| booked_at_ist, lead_time_days | When booked, and how many days before the flight |

## mart_flight_daily
**Grain:** one row per date and route. **Source:** `fact_flight`. Totals only.

| Column | Meaning |
|---|---|
| date_key, route_key | Keys |
| flights_scheduled, flights_operated, flights_cancelled | Counts |
| flights_measured | Operated flights with an actual arrival time (punctuality denominator) |
| flights_on_time | Of those, arrived within 15 minutes |
| arrival_delay_minutes_total | Sum of arrival delay over measured flights, early counted as 0 |
| flights_delayed, delayed_minutes_total | Flights more than 15 minutes late, and their total delay |
| seats_offered, ask | Capacity |

## mart_booking_daily
**Grain:** one row per date, route and cabin. **Source:** `fact_booking` + `fact_flight`
seats per cabin. Totals only.

| Column | Meaning |
|---|---|
| date_key, route_key, cabin | Keys |
| seats_offered, ask | Seats in this cabin on operated flights, and seat-km |
| bookings, passengers_flown | Counts |
| fare_revenue_inr, ancillary_revenue_inr, total_revenue_inr | Revenue kept |
| rpk | Revenue passenger-km |
| fare_outlier_bookings | Bookings flagged as fare outliers |

## KPI definitions (plain language)

| KPI | Formula on the marts | In words |
|---|---|---|
| Load factor | sum(passengers_flown) / sum(seats_offered) | Share of seats that had someone in them |
| On-time performance | sum(flights_on_time) / sum(flights_measured) | Share of flights arriving within 15 min of schedule |
| Cancellation rate | sum(flights_cancelled) / sum(flights_scheduled) | Share of scheduled flights that did not fly |
| ASK | sum(ask) | Seats flown x km: the airline's capacity |
| RPK | sum(rpk) | Passengers carried x km: the traffic sold |
| Yield | sum(fare_revenue_inr) / sum(rpk) | What a passenger pays per km (fares only) |
| RASK | sum(total_revenue_inr) / sum(ask) | Revenue per seat-km, full or empty: the best single measure of a route |
| Ancillary share | sum(ancillary_revenue_inr) / sum(total_revenue_inr) | Share of revenue from extras |
| Avg delay (all) | sum(arrival_delay_minutes_total) / sum(flights_measured) | Typical lateness, early = 0 |
| Avg delay (delayed) | sum(delayed_minutes_total) / sum(flights_delayed) | How late, when late |

## Exported meta tables (data/exports/meta)

`pipeline_runs`, `reconciliation`, `dq_results`, `schema_changes`, `file_log`,
`layer_counts`, `quarantine_summary`. They hold counts and run records only, never
quarantined rows, so no personal data can leak through them.
