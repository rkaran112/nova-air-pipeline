# Generator answer key

**Spoiler.** These are the business patterns hidden in the synthetic data. Try to find
them yourself on the dashboard first (`PRACTICE_DRILLS.md` tells you how), then check
here.

The patterns are coded in `scripts/datagen/patterns.py` (also a spoiler). The evidence
tables below are computed from the latest pipeline run's exports by
`python -m scripts.update_doc_numbers`.

| # | Pattern planted | Where it shows on the dashboard |
|---|---|---|
| 1 | **Mumbai monsoon:** July to September, flights touching BOM have a 35% chance of a weather delay (about 20-60 minutes) | Delay analysis → "Which airports have bad months?" BOM, and GOI (whose only route is to BOM), are dark in Jul-Sep |
| 2 | **Delhi winter fog:** December, departures from DEL before 10:00 IST (and arrivals into DEL before 11:00) have a 55% chance of a 30-90+ minute weather delay, and more cancellations | Same heatmap: the whole December column darkens, because the fog delays pass on to later legs; the hour heatmap shows DEL's early hours |
| 3 | **Delays build up through the day:** each aircraft passes on its lateness minus 5 minutes of slack, and small problems get likelier on later legs | "Do delays build up through an aircraft's day?" rises from leg 1 to leg 4; "Reactionary" is the biggest cause |
| 4 | **Busy route, poor revenue per seat:** DEL-BOM and BOM-DEL fill to ~93% of economy seats (before no-shows) but fares are 45% below the normal formula, a fare war | Route performance: the two dots at the bottom-right of the scatter; the shortest RASK bars |
| 5 | **A route that never fills:** BLR-COK and COK-BLR sell about half their economy seats | The two left-most dots on the scatter |
| 6 | **Festival revenue:** 14-24 Oct (Diwali, 20 Oct 2025) +8 points of load factor and fares x1.3; 20-31 Dec +5 points and x1.15 | Overview → "Which weeks brought in the most revenue?" spikes in the weeks of 13 and 20 October |

Also built in (not "hidden", just realistic): Fridays and Sundays are a little fuller,
Tuesdays and Wednesdays a little emptier; late bookings pay more.

## Evidence from the latest run

<!-- numbers:pattern-evidence -->
Average departure delay (minutes) by month, flights leaving BOM vs elsewhere:

| Month | From BOM | From elsewhere |
|---|---|---|
| Jul 2025 | 36.9 | 18.0 |
| Aug 2025 | 41.5 | 18.3 |
| Sep 2025 | 36.0 | 16.3 |
| Oct 2025 | 5.4 | 9.5 |
| Nov 2025 | 8.4 | 9.3 |
| Dec 2025 | 55.3 | 44.8 |

Average departure delay (minutes) of DEL departures before 10:00 IST, by month:

| Month | DEL morning delay |
|---|---|
| Jul 2025 | 12.1 |
| Aug 2025 | 16.5 |
| Sep 2025 | 12.9 |
| Oct 2025 | 3.5 |
| Nov 2025 | 4.7 |
| Dec 2025 | 78.8 |

Average departure delay (minutes) by the aircraft's leg of the day:

| Leg | Avg delay | On time % |
|---|---|---|
| 1 | 13.5 | 80.7 |
| 2 | 19.7 | 70.1 |
| 3 | 23.7 | 61.3 |
| 4 | 27.4 | 51.6 |

Routes with the lowest RASK and the lowest load factor:

| Route | Load factor % | RASK ₹ |
|---|---|---|
| DEL-BOM | 83.7 | 3.57 |
| BOM-DEL | 84.3 | 3.61 |
| DEL-MAA | 72.5 | 4.82 |

| Route | Load factor % |
|---|---|
| BLR-COK | 45.3 |
| COK-BLR | 46.5 |
| PNQ-DEL | 72.4 |

Revenue (₹ crore) by full week, around Diwali (20 Oct 2025):

| Week starting | Revenue ₹ cr |
|---|---|
| 2025-09-29 | 14.92 |
| 2025-10-06 | 14.87 |
| 2025-10-13 | 19.92 |
| 2025-10-20 | 19.5 |
| 2025-10-27 | 15.1 |
| 2025-11-03 | 14.93 |
<!-- /numbers -->

## Why GOI and December look the way they do

- GOI's only route is BOM-GOI, flown by the BOM-based aircraft, so Goa inherits
  Mumbai's monsoon delays (on arrival at BOM and through the aircraft's next leg).
- In December every airport's average delay rises, not only DEL's: the DEL-based
  aircraft carry their morning fog delays onto every later leg of the day (pattern 3
  amplifying pattern 2). A good panel answer separates the *cause* (DEL morning fog)
  from the *spread* (reactionary delays).
