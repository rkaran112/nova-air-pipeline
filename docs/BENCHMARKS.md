# Benchmarks

Measured by `python -m scripts.benchmark` on 03 Nov 2026. Every number below was written by that script; none were typed in.

## Machine

- Windows 10.0.26200, Python 3.11.7, DuckDB 1.5.6
- 4 logical CPUs, 7.7 GB RAM
- Data folder `D:\Projects\nova-air-pipeline\data\bench` is on a disk reported as: **HDD**

## Timings

Wall-clock seconds, including Python start-up. Peak memory is the resident memory of the process and its children, sampled every 0.2 s.

| Profile | Generate (s) | Backfill 184 days (s) | Peak memory, backfill (MB) | Re-run one day (s) | Landing files (MB) | Warehouse file (MB) |
|---|---|---|---|---|---|---|
| small | 73.0 | 165.7 | 804 | 16.6 | 110 | 329 |
| medium | 429.4 | 1670.0 | 965 | 104.3 | 659 | 1732 |

Time inside each step during the backfill (seconds, from `meta.pipeline_runs`; the rest of the wall time is Python start-up, commits and the final checkpoint):

| Profile | ingest_bronze | load_silver | build_gold | check_gold | export |
|---|---|---|---|---|---|
| small | 28.0 | 70.8 | 7.3 | 0.4 | 3.2 |
| medium | 138.1 | 1009.3 | 76.4 | 12.3 | 56.9 |

## Rows

| Table | small | medium |
|---|---|---|
| bronze.flights | 3,864 | 23,252 |
| bronze.bookings | 546,108 | 3,275,470 |
| bronze.passengers | 363,913 | 2,182,068 |
| silver.flights | 3,680 | 22,080 |
| silver.bookings | 524,868 | 3,148,057 |
| silver.passengers | 343,618 | 2,060,165 |
| silver.quarantine | 18,587 | 104,670 |
| gold.fact_flight | 3,680 | 22,080 |
| gold.fact_booking | 524,868 | 3,148,057 |
| gold.mart_booking_daily | 7,360 | 7,360 |

Exit codes (generate, backfill, re-run): {'small': (0, 0, 0), 'medium': (0, 0, 0)}

## Run-to-run variation

The same small profile was also run from the SSD (in the Windows temp folder) straight
after the run above. Its rows, copied from that run's report:

| Profile | Generate (s) | Backfill 184 days (s) | Peak memory, backfill (MB) | Re-run one day (s) | Landing files (MB) | Warehouse file (MB) |
|---|---|---|---|---|---|---|
| small | 133.5 | 303.2 | 920 | 20.3 | 110 | 329 |

| Profile | ingest_bronze | load_silver | build_gold | check_gold | export |
|---|---|---|---|---|---|
| small | 46.0 | 193.6 | 5.5 | 0.9 | 4.7 |

It was slower, not faster, and the data generator (which barely touches the disk) slowed
down by the same factor, so the difference is the machine's state at the time
(background processes, antivirus scanning new files in the temp folder, power
management), not the disk. An earlier full benchmark on the HDD the same evening
measured the medium backfill at 971 s and the small one at 203 s. Treat these timings
as accurate to within about a factor of two on this laptop.

## What the step times show

- Silver dominates the medium run, and its time per day grows through the backfill
  (about 2 s a day at the start of July, about 8 s by late December, from
  `meta.pipeline_runs`). Each day's `MERGE` and the `LEFT JOIN` that checks for older
  versions scan the whole, growing `silver.bookings` table, so a backfill gets slower
  as it goes. `docs/SCALING.md` describes the fix.
- Bronze stays roughly flat per day: it only appends.
