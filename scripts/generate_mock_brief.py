"""Generate a mock hackathon: a messy baggage-handling dataset and a problem statement.

    python -m scripts.generate_mock_brief            # writes data/mock_hackathon/
    python -m scripts.generate_mock_brief --seed 7   # a different but equally messy set

There is deliberately no solution in this repo. Read BRIEF.md in the output folder,
start a timer, and build it yourself.
"""

import argparse
import csv
import json
import random
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

AIRPORTS = (("BLR", "Bengaluru"), ("BOM", "Mumbai"), ("DEL", "Delhi"), ("HYD", "Hyderabad"),
            ("MAA", "Chennai"), ("CCU", "Kolkata"))
FIRST_DAY = date(2025, 11, 1)
DAYS = 14
FLIGHTS_PER_DAY = 24

BRIEF = """# Mock hackathon brief: SkyBag baggage operations

**Time allowed:** 3 hours, then a 5-minute demo.

## Background

SkyBag handles checked baggage for a domestic airline at six Indian airports. Every bag
gets a tag at check-in and is scanned as it moves: check-in, sortation, loaded onto the
aircraft, arrived at the destination, and on the arrival carousel. Bags that do not make
it onto the right flight, or never reach the carousel, are "mishandled" and cost money
in deliveries and compensation.

Operations has sent you two weeks of raw exports (1-14 November 2025):

| File | One row is... |
|---|---|
| `flights.csv` | a flight leg, with scheduled times and the number of passengers carried |
| `bags_YYYY-MM-DD.csv` | a bag checked in that day: tag, flight, weight, booking ref, phone |
| `scans_YYYY-MM-DD.json` | one scan of one bag at one scan point (a tracking system export) |
| `airports.csv` | reference data |

The exports came from different systems and nobody has cleaned them. Expect problems.

## What the business wants to know

1. What is the **mishandled bag rate per 1,000 passengers**, overall, by airport and by day?
2. Where in the journey do bags go missing (which scan point is the last one seen)?
3. Does the mishandling rate depend on the **time of day** or on **how much time the bag
   had** between check-in and departure?
4. How long do passengers wait at the carousel after the aircraft arrives, by airport?
5. Can we trust this data? Show what was wrong with it and what you did about it.

## What to deliver

- A pipeline anyone can rerun with one command, from raw files to clean reporting tables.
- A dashboard (any tool) that answers the questions above.
- A short explanation of your design: layers, grain of each table, how you handled bad
  data, and what you would do with more time.

## Rules

- Treat booking references and phone numbers as personal data.
- Do not edit the raw files.
- State every assumption you make.
"""


def stamp(rng, value):
    """Three systems, three formats; one of them sends local time with no zone."""
    roll = rng.random()
    if roll < 0.5:
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if roll < 0.8:
        return (value - timedelta(hours=5, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return value.strftime("%d-%m-%Y %I:%M %p")


def make_flights(rng):
    flights = []
    for offset in range(DAYS):
        day = FIRST_DAY + timedelta(days=offset)
        for number in range(FLIGHTS_PER_DAY):
            origin, destination = rng.sample([a[0] for a in AIRPORTS], 2)
            departure = datetime(day.year, day.month, day.day, 5) + timedelta(
                minutes=rng.randint(0, 17 * 60))
            flights.append({
                "flight_no": f"SB{200 + number}",
                "flight_date": day.isoformat(),
                "origin": origin,
                "destination": destination,
                "sched_dep": departure,
                "sched_arr": departure + timedelta(minutes=rng.randint(70, 170)),
                "passengers": rng.randint(90, 186),
            })
    return flights


def bag_journey(rng, flight, check_in):
    """Return the scans a bag really gets, and whether it was mishandled."""
    minutes_to_departure = (flight["sched_dep"] - check_in).total_seconds() / 60
    late_check_in = minutes_to_departure < 45
    evening = flight["sched_dep"].hour >= 18
    risk = 0.004 + (0.03 if late_check_in else 0) + (0.006 if evening else 0)
    if flight["origin"] == "DEL":
        risk += 0.006
    scans = [("CHECKIN", check_in),
             ("SORTATION", check_in + timedelta(minutes=rng.randint(5, 25)))]
    if rng.random() < risk:
        return scans, True  # never loaded
    scans.append(("LOADED", flight["sched_dep"] - timedelta(minutes=rng.randint(8, 30))))
    arrival = flight["sched_arr"] + timedelta(minutes=rng.randint(-10, 40))
    scans.append(("ARRIVED", arrival + timedelta(minutes=rng.randint(3, 12))))
    if rng.random() < 0.003:
        return scans, True  # lost between aircraft and carousel
    wait = rng.randint(8, 35) + (15 if flight["destination"] == "BOM" else 0)
    scans.append(("CAROUSEL", arrival + timedelta(minutes=wait)))
    return scans, False


def write_day(folder, rng, day, flights, next_bag):
    bags, scans = [], []
    for flight in (f for f in flights if f["flight_date"] == day.isoformat()):
        for _ in range(int(flight["passengers"] * rng.uniform(0.5, 0.9))):
            check_in = flight["sched_dep"] - timedelta(minutes=rng.randint(25, 240))
            bag_id = f"BG{next_bag:07d}"
            next_bag += 1
            weight = round(rng.uniform(6, 26), 1)
            unit = "kg"
            if rng.random() < 0.03:
                weight, unit = round(weight * 2.2046, 1), "lb"  # a US-built scale
            flight_no = flight["flight_no"]
            if rng.random() < 0.05:
                flight_no = rng.choice((flight_no.lower(), flight_no[:2] + "-" + flight_no[2:]))
            bags.append({
                "bag_id": bag_id,
                "tag_number": "" if rng.random() < 0.01 else f"0{rng.randint(10**8, 10**9)}",
                "flight_no": flight_no,
                "flight_date": flight["flight_date"],
                "booking_ref": "".join(rng.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=6)),
                "passenger_phone": f"+91 9{rng.randint(10**8, 10**9 - 1)}",
                "weight": weight if rng.random() > 0.01 else -weight,
                "weight_unit": unit,
                "checked_in_at": stamp(rng, check_in),
            })
            journey, _ = bag_journey(rng, flight, check_in)
            for point, when in journey:
                airport = flight["origin"] if point in ("CHECKIN", "SORTATION", "LOADED") \
                    else flight["destination"]
                scan = {"bag_id": bag_id, "scan_point": point, "airport": airport,
                        "scanned_at": stamp(rng, when), "device_id": f"D{rng.randint(1, 60):02d}"}
                scans.append(scan)
                if rng.random() < 0.02:
                    scans.append(dict(scan))  # scanner double-read
            if rng.random() < 0.004:
                scans.append({"bag_id": bag_id, "scan_point": "LOADED", "airport": "XXX",
                              "scanned_at": stamp(rng, check_in - timedelta(hours=3)),
                              "device_id": "D00"})
            if rng.random() < 0.01:
                bags.append(dict(bags[-1]))  # the bag file repeats a row
    rng.shuffle(scans)
    # Some scans reach the export a day late.
    on_time, late = [], []
    for scan in scans:
        (late if rng.random() < 0.01 else on_time).append(scan)
    stamp_day = day.isoformat()
    with (folder / f"bags_{stamp_day}.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(bags[0]))
        writer.writeheader()
        writer.writerows(bags)
    return on_time, late, next_bag


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=Path("data") / "mock_hackathon")
    args = parser.parse_args(argv)
    rng = random.Random(args.seed)
    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    flights = make_flights(rng)
    with (args.out / "flights.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(flights[0]))
        writer.writeheader()
        for flight in flights:
            writer.writerow({**flight, "sched_dep": flight["sched_dep"].strftime("%Y-%m-%d %H:%M"),
                             "sched_arr": flight["sched_arr"].strftime("%H:%M")})
    with (args.out / "airports.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(("airport_code", "city"))
        writer.writerows(AIRPORTS)

    next_bag = 1
    carried_over = []
    for offset in range(DAYS):
        day = FIRST_DAY + timedelta(days=offset)
        scans, late, next_bag = write_day(args.out, rng, day, flights, next_bag)
        (args.out / f"scans_{day.isoformat()}.json").write_text(
            json.dumps(scans + carried_over, indent=1), encoding="utf-8")
        carried_over = late
    (args.out / "BRIEF.md").write_text(BRIEF, encoding="utf-8")
    files = sorted(p.name for p in args.out.iterdir())
    print(f"wrote {len(files)} files to {args.out}: read {args.out / 'BRIEF.md'} first")
    return 0


if __name__ == "__main__":
    sys.exit(main())
