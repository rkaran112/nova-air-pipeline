# Rebuilding the dashboard in Power BI

The pipeline exports every gold table to `data/exports/gold/` as both Parquet and CSV.
This guide uses CSV because every Power BI version reads it; Parquet works the same way
through **Get data → Parquet**.

The expected values at the end come from the latest pipeline run (small profile, seed
42), so you can check your measures are right. The DAX in this guide has not been run
in Power BI by the author of this repo: verify each measure against those expected
values.

## 1. Import the tables

1. Open Power BI Desktop → **Get data → Text/CSV**.
2. Import these files from `data/exports/gold/`:
   `dim_date`, `dim_route`, `dim_airport`, `dim_aircraft`, `dim_passenger`,
   `dim_delay_reason`, `fact_flight`, `fact_booking`, `mart_flight_daily`,
   `mart_booking_daily`.
3. In **Transform data**, check the types: keys ending in `_key` are Text except
   `date_key` (Whole number); `calendar_date` is Date; money columns are Decimal number;
   `is_*` columns are True/False. Then **Close & Apply**.

## 2. Build the star schema relationships

In **Model view**, drag from the fact column to the dimension column. Every relationship
is **many-to-one (*:1)**, single direction, dimension filters fact.

| From (many) | To (one) |
|---|---|
| fact_flight[date_key] | dim_date[date_key] |
| fact_flight[route_key] | dim_route[route_key] |
| fact_flight[origin_airport_key] | dim_airport[airport_key] |
| fact_flight[aircraft_key] | dim_aircraft[aircraft_key] |
| fact_flight[delay_reason_key] | dim_delay_reason[delay_reason_key] |
| fact_booking[date_key] | dim_date[date_key] |
| fact_booking[route_key] | dim_route[route_key] |
| fact_booking[passenger_key] | dim_passenger[passenger_key] |
| mart_flight_daily[date_key] | dim_date[date_key] |
| mart_flight_daily[route_key] | dim_route[route_key] |
| mart_booking_daily[date_key] | dim_date[date_key] |
| mart_booking_daily[route_key] | dim_route[route_key] |

`fact_flight[destination_airport_key]` → `dim_airport` would be a second path to the same
table; Power BI makes it inactive. Leave it inactive and use `USERELATIONSHIP` in a
measure when you need arrivals by airport.

Mark `dim_date` as the date table: **Table tools → Mark as date table → calendar_date**.

## 3. Write the measures

Create a blank table called `_Measures` to hold them (**Enter data → OK**, then add
measures to it).

### Why load factor must be sum ÷ sum

The tempting measure is:

```DAX
Load Factor WRONG = AVERAGEX ( fact_flight, [passengers on this flight] / fact_flight[seats_offered] )
```

It averages each flight's percentage, so a 20-seat flight that is 10% full counts as much
as a 180-seat flight that is 100% full: (10% + 100%) / 2 = 55%. The airline actually
filled 182 of 200 seats: 91%. In DAX, divide the **sum** of passengers by the **sum** of
seats, and let the filters decide which rows go into each sum:

```DAX
Load Factor =
DIVIDE (
    SUM ( mart_booking_daily[passengers_flown] ),
    SUM ( mart_booking_daily[seats_offered] )
)
```

`DIVIDE` returns blank instead of an error when the denominator is 0.

### The rest

```DAX
Revenue = SUM ( mart_booking_daily[total_revenue_inr] )

Passengers Flown = SUM ( mart_booking_daily[passengers_flown] )

On-Time Performance =
DIVIDE ( SUM ( mart_flight_daily[flights_on_time] ), SUM ( mart_flight_daily[flights_measured] ) )

Cancellation Rate =
DIVIDE ( SUM ( mart_flight_daily[flights_cancelled] ), SUM ( mart_flight_daily[flights_scheduled] ) )

ASK = SUM ( mart_booking_daily[ask] )

RPK = SUM ( mart_booking_daily[rpk] )

Yield = DIVIDE ( SUM ( mart_booking_daily[fare_revenue_inr] ), [RPK] )

RASK = DIVIDE ( [Revenue], [ASK] )

Ancillary Share =
DIVIDE ( SUM ( mart_booking_daily[ancillary_revenue_inr] ), [Revenue] )

Avg Arrival Delay (all measured flights) =
DIVIDE ( SUM ( mart_flight_daily[arrival_delay_minutes_total] ), SUM ( mart_flight_daily[flights_measured] ) )

Avg Delay (delayed flights only) =
DIVIDE ( SUM ( mart_flight_daily[delayed_minutes_total] ), SUM ( mart_flight_daily[flights_delayed] ) )
```

Format the ratio measures as Percentage (except Yield, RASK and the delays).

## 4. Build the four pages

Use a slicer on `dim_date[calendar_date]` (Between), `dim_route[route_code]` and
`mart_booking_daily[cabin]` on every page (**View → Sync slicers**). Note that the cabin
slicer cannot filter `mart_flight_daily`, which has no cabin: punctuality is per flight.

| Page | Visuals |
|---|---|
| Executive overview | Cards: Revenue, Passengers Flown, Load Factor, On-Time Performance, Cancellation Rate. Column chart: Revenue by `dim_date[month_label]`. Line charts: Load Factor and On-Time Performance by month (two charts, not a dual axis) |
| Route performance | Bar chart: RASK by `route_code`, sorted. Scatter: X = Load Factor, Y = RASK, Values = route_code |
| Delay analysis | From `fact_flight`: bar of departure delay minutes by `dim_delay_reason[category]`; matrix with `dim_airport[airport_code]` on rows, `sched_dep_hour_ist` on columns, average departure delay with conditional formatting; line of average delay by `aircraft_leg_number` |
| Data health | Import `data/exports/meta/*.parquet` (Get data → Parquet). Table of `reconciliation`, bar of `quarantine_summary[row_count]` by reason |

## 5. Check against the pipeline

With all filters cleared, your cards should show the values in the README's "Results"
table (filled in from the latest run). If Load Factor is a little different, check you
used the measure above and not an average.
