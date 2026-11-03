# Data quality: defect, detection, action, count

The generator plants 16 kinds of defect at known rates and counts every one in
`data/generator_manifest.json`. The pipeline detects them independently and records
what it found in `meta.dq_results`. The tables below are filled in from the latest run
by `python -m scripts.update_doc_numbers`; nothing in them is typed by hand.

Run used: small profile, seed 42, 1 July to 31 December 2025.

## Every defect

<!-- numbers:data-quality -->
| # | Defect | Detection | Action | Planted by generator | Found by pipeline |
|---|---|---|---|---|---|
| 1 | Exact duplicate rows | Same JSON fingerprint for the whole row | Keep the first copy, count the rest | 8,362 | 8,362 |
| 2 | Several versions of one record | Same business key; compare updated_at | Keep the latest; an older version never overwrites a newer one | 18,016 | 18,012 |
| 3 | Flight number variants | Upper-case and strip spaces and hyphens | Standardise to NV1234 | 77,390 | 77,390 |
| 4 | Corrupted flight numbers | Fails the NV + 3-4 digits pattern | Quarantine: INVALID_FLIGHT_NO | 1,622 | 1,622 |
| 5 | Mixed timestamp formats (UTC and IST) | Try the three known formats in order | Store UTC; derive IST in gold; unreadable -> BAD_TIMESTAMP | 714,699 | 0 |
| 6 | Overnight flights with time-only arrival | Arrival text is HH:MM | Attach the departure date; add a day if it would be before departure | 386 | 717 |
| 7 | Arrival before departure / impossible duration | Flight time <= 0 or > 2x schedule | Quarantine: IMPOSSIBLE_DURATION | 21 | 21 |
| 8 | Status contradicts actual times | CANCELLED with times / OPERATED without | Cancelled: clear times, flag. Operated: keep, flag, leave out of punctuality | 25 | 25 |
| 9 | Zero or negative fares | fare_amount <= 0 | Quarantine: NON_POSITIVE_FARE | 1,597 | 1,597 |
| 10 | USD fares in an INR column | currency = 'USD' | Convert at that booking day's rate from the FX table | 10,676 | 10,676 |
| 11 | Fare outliers | Beyond 3 x IQR of the same route and cabin | Flag in gold, keep the row | 1,628 | 1,782 |
| 12 | Booking arrives before its flight | No matching flight in silver yet | Quarantine as waiting; retried every run; released when the flight arrives | 39 | 12,184 |
| 13 | Booking for a flight that never exists | Still no flight 3 days after its date | Rejected for good: NO_VALID_FLIGHT | 530 | 517 |
| 14 | Missing values | Required vs optional fields | Required: quarantine. Optional: documented default | 2,633 | 2,633 |
| 15 | New promo_code column appears | File header has a column bronze lacks | Add the column, log it in meta.schema_changes, warn | from 1 Oct | 1 |
| 16 | Corrected flight record a day late | Same flight key, newer updated_at | Update the silver row in place; no duplicate | 38 | see note |
<!-- /numbers -->

How to read the two count columns. They do not always measure the same thing, so they
are not meant to be equal on every row:

- **#2:** both include stale versions re-sent a day later. A few stale copies arrived
  while their booking's flight was still missing, so they were quarantined as waiting
  (and counted there) instead of as older versions: that is the small gap.
- **#3:** both count rows; they match because every variant is standardised.
- **#4:** corrupted flight records were re-sent correctly the next day (their bookings
  waited, then were released). Bookings with corrupted numbers stay rejected.
- **#5:** the generator counts timestamps written in a non-default format. The pipeline
  parses all of them, so it reports only unreadable ones (`BAD_TIMESTAMP`): zero.
- **#6:** the pipeline count includes the ~10% of same-day arrivals that were also sent
  as time only; all of them get the right date.
- **#11:** the pipeline flags a few more than were planted: with 3 x IQR, a handful of
  genuinely expensive late bookings also fall outside the range. They are flagged, not
  deleted, so the cost of a false flag is one extra row to look at.
- **#12:** the generator counts *flights* that arrived late; the pipeline counts the
  *bookings* that waited for them and were released (around 140 per flight).
- **#13:** the gap is the bookings from the last days of December, which are still
  inside their 3-day grace period and so still `waiting`.
- **#14:** both columns count missing *required* fields. Missing optional fields
  (channel, ancillary amount, email, phone) are filled with the documented defaults and
  kept, so they are not rejections.
- **#15:** the generator adds the column to every bookings file from 1 October; the
  pipeline logs it once, on the first file that has it.
- **#16:** corrections are applied by the `MERGE`; the test
  `test_correction_a_day_later_updates_without_duplicating` proves no duplicate is made.

## Did every row add up?

Per source, summed over every daily batch: rows in = loaded + exact duplicates + older
versions + quarantined.

<!-- numbers:reconciliation -->
| Source | Batches | Rows in | Loaded | Exact duplicates | Older versions | Quarantined | Batches balanced |
|---|---|---|---|---|---|---|---|
| bookings | 184 | 546,108 | 512,920 | 4,924 | 10,779 | 17,485 | 184 |
| flights | 184 | 3,864 | 3,718 | 39 | 61 | 46 | 184 |
| passengers | 184 | 363,913 | 352,286 | 3,399 | 7,172 | 1,056 | 184 |
<!-- /numbers -->

## What is in quarantine

<!-- numbers:quarantine -->
| Source | Reason | Status | Rows |
|---|---|---|---|
| bookings | WAITING_FOR_FLIGHT | released | 12,184 |
| bookings | INVALID_FLIGHT_NO | rejected | 1,597 |
| bookings | NON_POSITIVE_FARE | rejected | 1,597 |
| bookings | MISSING_REQUIRED_FIELD | rejected | 1,577 |
| bookings | NO_VALID_FLIGHT | rejected | 517 |
| bookings | WAITING_FOR_FLIGHT | waiting | 13 |
| flights | INVALID_FLIGHT_NO | rejected | 25 |
| flights | IMPOSSIBLE_DURATION | rejected | 21 |
| passengers | MISSING_REQUIRED_FIELD | rejected | 1,056 |
<!-- /numbers -->

## Which checks stop the run, and which only warn

| Check | Severity | Why |
|---|---|---|
| PII key missing or shorter than 32 characters | stop (exit 2) | Without a key, tokens would be guessable; nothing may run |
| File missing a required column | stop | No row could pass; loading it would only fill the quarantine |
| Reconciliation does not balance | stop | A row went missing silently: every number after it is suspect |
| More than 20% of a batch rejected | stop | Something systemic (wrong file, new format); publishing would be misleading |
| Duplicate key in silver or gold | stop | Joins would double count |
| Orphan key in a fact table | stop | Rows would vanish from joined reports |
| Load factor above 100% on any route-day | stop | Physically impossible: a bug, not data |
| New or vanished column | warn | Data still loads correctly; someone should know |
| 5-20% of a batch rejected | warn | Numbers are right, but a source may be degrading |
| Bookings waiting for their flight / given up | warn | Expected occasionally; a trend would mean an upstream problem |
| Status contradicts times (fixed by rule) | warn | Fixed, but the source system is sending contradictions |
| Duplicates, older versions, variants, USD converted, time-only arrivals | info | Routine cleaning; counted so you can see it |

All of these are in `meta.dq_results` (with run, batch and source) and on the dashboard's
Data health page.

## The rules, in order

Silver checks each row against its rules in a fixed order; the first failure becomes the
reason. From `sql/silver/*_check.sql`:

**Flights:** MISSING_REQUIRED_FIELD, INVALID_FLIGHT_NO, BAD_TIMESTAMP, INVALID_STATUS,
UNKNOWN_ROUTE, IMPOSSIBLE_DURATION (scheduled 20-360 minutes; actual not before
departure and not over 2x the schedule).

**Passengers:** MISSING_REQUIRED_FIELD, BAD_TIMESTAMP.

**Bookings:** MISSING_REQUIRED_FIELD, INVALID_FLIGHT_NO, BAD_TIMESTAMP, BAD_NUMBER,
INVALID_VALUE (cabin or status), UNKNOWN_CURRENCY, NON_POSITIVE_FARE, then
NO_VALID_FLIGHT (past the grace period) or WAITING_FOR_FLIGHT.

**Optional-field rules:** blank `channel` becomes `UNKNOWN`; blank `ancillary_amount`
becomes 0; blank `loyalty_tier` becomes `NONE`; blank email or phone stays NULL (the
dimension records `has_email = false`).

**Status rule:** a CANCELLED flight with actual times has them cleared
(`actuals_cleared`); an OPERATED flight without an actual time is kept for revenue and
load factor, but left out of punctuality (`actuals_missing`).
