"""Generate Nova Air's messy daily source files into data/landing/.

    python -m scripts.generate_data                     # small profile, seed 42
    python -m scripts.generate_data --profile medium
    python -m scripts.generate_data --no-defects        # clean data, for comparison

The same seed always produces byte-identical files. The defects injected are
counted in data/generator_manifest.json, which the pipeline never reads: it exists
so you can check the pipeline found what was planted.
"""

import argparse
import json
import random
import shutil
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

from scripts.datagen import bookings, defects, flights, reference, schedule, sources, writers

FIRST_DAY = date(2025, 7, 1)
LAST_DAY = date(2025, 12, 31)
SCHEMA_CHANGE_DAY = date(2025, 10, 1)  # promo_code starts appearing in bookings
FX_HISTORY_DAYS = 120  # bookings can be made up to 90 days before the flight

BOOKING_COLUMNS = ("booking_id", "pnr", "passenger_id", "flight_no", "flight_date", "origin",
                   "cabin", "fare_amount", "currency", "ancillary_amount", "channel", "status",
                   "booked_at", "updated_at")
PASSENGER_COLUMNS = ("passenger_id", "full_name", "email", "phone", "date_of_birth",
                     "loyalty_tier", "updated_at")


@dataclass(frozen=True)
class Profile:
    name: str
    waves: int  # how many times each rotation flies per day
    max_passenger_pool: int  # how many past passengers can return


PROFILES = (Profile("small", 1, 60_000), Profile("medium", 6, 250_000))


def find_profile(name):
    return next(p for p in PROFILES if p.name == name)


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", choices=[p.name for p in PROFILES], default="small")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--start", type=date.fromisoformat, default=FIRST_DAY)
    parser.add_argument("--end", type=date.fromisoformat, default=LAST_DAY)
    parser.add_argument("--no-defects", action="store_true")
    return parser.parse_args(argv)


def write_reference(landing, rng, fleet, start, end):
    folder = landing / "reference"
    fx = reference.fx_rows(rng, start - timedelta(days=FX_HISTORY_DAYS), end)
    writers.write_csv(folder / "airports.csv", reference.airport_rows(),
                      ("airport_code", "airport_name", "city", "state", "latitude", "longitude"))
    writers.write_csv(folder / "aircraft.csv", reference.aircraft_rows(fleet),
                      ("aircraft_reg", "aircraft_type", "seats_plus", "seats_economy",
                       "seats_total"))
    writers.write_csv(folder / "delay_codes.csv", reference.delay_code_rows(),
                      ("delay_code", "description", "category"))
    writers.write_csv(folder / "fx_rates.csv", fx,
                      ("rate_date", "from_currency", "to_currency", "rate"))
    return {date.fromisoformat(row["rate_date"]): float(row["rate"]) for row in fx}


def generate_day(rng, fake, day, plan, fleet, state, counts):
    """Return (flight records, booking records, passenger records) for one day."""
    flight_truths = flights.simulate_day(rng, plan, day, fleet)
    flight_records = []
    booking_records = []
    passenger_records = []
    include_promo = day >= SCHEMA_CHANGE_DAY
    for flight in flight_truths:
        flight_records.append(sources.flight_record(rng, flight, counts))
        distance = reference.distance_km(flight["origin"], flight["destination"])
        profile_updates = []
        for booking in bookings.bookings_for_flight(rng, fake, state, flight, distance,
                                                    profile_updates):
            booking_records.append(sources.booking_record(rng, booking, include_promo, counts))
        for passenger in profile_updates:
            passenger_records.append(sources.passenger_record(rng, passenger, counts))
    counts["truth_flights"] += len(flight_truths)
    counts["truth_cancelled_flights"] += sum(f["status"] == "CANCELLED" for f in flight_truths)
    counts["truth_bookings"] += len(booking_records)
    counts["truth_passenger_profiles"] += len(passenger_records)
    return flight_records, booking_records, passenger_records


def write_day(landing, day, flight_records, booking_records, passenger_records, counts):
    stamp = day.isoformat()
    columns = BOOKING_COLUMNS + (("promo_code",) if day >= SCHEMA_CHANGE_DAY else ())
    writers.write_json(landing / "flights" / f"flights_{stamp}.json", flight_records)
    writers.write_csv(landing / "bookings" / f"bookings_{stamp}.csv", booking_records, columns)
    writers.write_csv(landing / "passengers" / f"passengers_{stamp}.csv", passenger_records,
                      PASSENGER_COLUMNS)
    # Counted per row written, because copies of a record share its quirks.
    counts["flight_no_variant"] += sum(1 for r in flight_records if r.get("_variant"))
    counts["booking_flight_no_variant"] += sum(1 for r in booking_records if r.get("_variant"))
    counts["flight_overnight_time_only_arrival"] += sum(
        1 for r in flight_records if r.get("_overnight"))
    counts["rows_written_flights"] += len(flight_records)
    counts["rows_written_bookings"] += len(booking_records)
    counts["rows_written_passengers"] += len(passenger_records)


def generate(profile, seed, data_dir, start, end, rates):
    rng = random.Random(seed)
    fake = Faker("en_IN")
    fake.seed_instance(seed)
    landing = data_dir / "landing"
    if landing.exists():
        shutil.rmtree(landing)  # landing is fully generated, so start clean every time

    fleet = reference.fleet_registrations(schedule.aircraft_count(profile.waves))
    plan = schedule.daily_plan(profile.waves)
    fx_by_date = write_reference(landing, rng, fleet, start, end)
    state = bookings.new_state(profile.max_passenger_pool)
    counts = Counter()
    later = {}  # date -> records that arrive on that day instead of their own

    day = start
    while day <= end:
        flight_records, booking_records, passenger_records = generate_day(
            rng, fake, day, plan, fleet, state, counts)
        defects.inject_flight_defects(rng, flight_records, day, end, later, rates, counts)
        defects.inject_booking_defects(rng, booking_records, day, end, later, fx_by_date,
                                       rates, counts)
        defects.inject_passenger_defects(rng, passenger_records, rates, counts)
        for record in later.pop(day, []):
            target = flight_records if "aircraft_reg" in record else booking_records
            target.append(record)
        rng.shuffle(flight_records)
        rng.shuffle(booking_records)
        rng.shuffle(passenger_records)
        write_day(landing, day, flight_records, booking_records, passenger_records, counts)
        day += timedelta(days=1)
    return counts


def main(argv=None):
    args = parse_args(argv)
    profile = find_profile(args.profile)
    rates = defects.zero_rates() if args.no_defects else defects.DefectRates()
    started = time.perf_counter()
    counts = generate(profile, args.seed, args.data_dir, args.start, args.end, rates)
    seconds = round(time.perf_counter() - started, 1)

    manifest = {
        "profile": profile.name,
        "seed": args.seed,
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "defect_rates": asdict(rates),
        "counts": dict(sorted(counts.items())),
        "seconds": seconds,
    }
    manifest_path = args.data_dir / "generator_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"profile={profile.name} seed={args.seed} days={args.start}..{args.end} "
          f"seconds={seconds}")
    for name in ("rows_written_flights", "rows_written_bookings", "rows_written_passengers"):
        print(f"{name}={counts[name]}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
