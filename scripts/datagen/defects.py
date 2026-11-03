"""Inject the 16 known defects at configurable rates, counting every one.

Each function changes one day's list of source records in place and adds to
`counts`. Records that should turn up on a later day go into `later`, which maps a
date to the records to append to that day's file.

A record gets at most one "main" defect, and only clean original records are
copied as duplicates or older versions, so every count means exactly one thing.
Flight-number variants are counted per written row in generate_data.py, because
copies of a varied record carry the variant too.
"""

from dataclasses import dataclass, fields
from datetime import timedelta

from .sources import IST_OFFSET


@dataclass(frozen=True)
class DefectRates:
    """Share of records hit by each defect. Use zero_rates() for clean data."""
    exact_duplicate: float = 0.01
    older_version: float = 0.02
    flight_no_variant: float = 0.15
    flight_late: float = 0.01
    flight_corrupted_flight_no: float = 0.005
    flight_impossible_duration: float = 0.005
    flight_corrected_next_day: float = 0.01
    flight_cancelled_with_actuals: float = 0.20
    flight_operated_missing_actuals: float = 0.005
    booking_ghost_flight: float = 0.001
    booking_corrupted_flight_no: float = 0.003
    booking_non_positive_fare: float = 0.003
    booking_usd_fare: float = 0.02
    booking_fare_outlier: float = 0.003
    booking_stale_resend: float = 0.002
    missing_required: float = 0.003
    missing_optional: float = 0.03


def zero_rates():
    return DefectRates(**{field.name: 0.0 for field in fields(DefectRates)})


def pick_one(rng, options):
    """Pick at most one name from (name, rate) pairs with a single random draw."""
    roll = rng.random()
    for name, rate in options:
        if roll < rate:
            return name
        roll -= rate
    return None


def flight_no_variant(rng, flight_no):
    digits = flight_no[2:]
    return rng.choice((f"NV-{digits}", f"nv{digits}", f" NV {digits} "))


def corrupt_flight_no(rng, flight_no):
    position = rng.choice((1, 3))
    return flight_no[:position] + "?" + flight_no[position + 1:]


def stamp_utc(value_ist):
    """Corrections and broken values are written as full UTC timestamps."""
    return (value_ist - IST_OFFSET).strftime("%Y-%m-%dT%H:%M:%SZ")


def defer(later, day, record):
    later.setdefault(day, []).append(record)


def resend(record, sent_at):
    """A corrected copy of a record, sent again with a newer update time."""
    return dict(record, updated_at=stamp_utc(sent_at), _updated_at=sent_at)


def add_copies(rng, records, rate, counts, name, make_copy):
    """Append a copy (identical or older) of a share of the clean records."""
    copies = []
    for record in records:
        if not record.get("_defective") and not record.get("_copy") and rng.random() < rate:
            copies.append(dict(make_copy(record), _copy=True))
            counts[name] += 1
    records.extend(copies)


def older_flight_version(record):
    """An earlier snapshot of the same flight, taken before it departed."""
    earlier = record["_truth"]["sched_dep"] - timedelta(hours=2)
    return dict(record, actual_dep=None, actual_arr=None, status="OPERATED", delay_code=None,
                updated_at=stamp_utc(earlier), _updated_at=earlier)


def inject_flight_defects(rng, records, day, last_day, later, rates, counts):
    next_day = day + timedelta(days=1)
    on_time_records = []
    for record in records:
        truth = record["_truth"]
        operated = truth["status"] == "OPERATED"
        main_defect = None
        if next_day <= last_day:
            main_defect = pick_one(rng, (
                ("late", rates.flight_late),
                ("corrupted", rates.flight_corrupted_flight_no),
                ("impossible", rates.flight_impossible_duration if operated else 0),
                ("corrected", rates.flight_corrected_next_day if operated else 0),
            ))
        resent_at = truth["sched_dep"] + timedelta(days=1)

        if main_defect == "late":
            arrives = day + timedelta(days=1 if rng.random() < 0.7 else 2)
            defer(later, min(last_day, arrives), record)
            counts["flight_arrives_late"] += 1
            continue
        if main_defect == "corrupted":
            defer(later, next_day, resend(record, resent_at))
            record.update(flight_no=corrupt_flight_no(rng, record["flight_no"]), _defective=True)
            counts["flight_corrupted_flight_no_then_resent"] += 1
        elif main_defect == "impossible":
            defer(later, next_day, resend(record, resent_at))
            broken = truth["actual_dep"] + rng.choice((timedelta(minutes=-40),
                                                       timedelta(hours=15)))
            record.update(actual_arr=stamp_utc(broken), _defective=True)
            counts["flight_impossible_duration_then_resent"] += 1
        elif main_defect == "corrected":
            better_arrival = truth["actual_arr"] + timedelta(minutes=rng.choice((-9, -5, 6, 12)))
            correction = resend(record, resent_at + timedelta(hours=10))
            correction["actual_arr"] = stamp_utc(better_arrival)
            defer(later, next_day, correction)
            counts["flight_corrected_next_day"] += 1

        if not operated and rng.random() < rates.flight_cancelled_with_actuals:
            record["actual_dep"] = stamp_utc(truth["sched_dep"] + timedelta(minutes=3))
            record["actual_arr"] = stamp_utc(truth["sched_arr"])
            counts["flight_cancelled_with_actual_times"] += 1
        if operated and not record.get("_defective") and (
                rng.random() < rates.flight_operated_missing_actuals):
            record["actual_arr"] = None
            counts["flight_operated_missing_actual_times"] += 1
        if not record.get("_defective") and rng.random() < rates.flight_no_variant:
            record.update(flight_no=flight_no_variant(rng, record["flight_no"]), _variant=True)
        on_time_records.append(record)

    add_copies(rng, on_time_records, rates.exact_duplicate, counts, "flight_exact_duplicate",
               dict)
    add_copies(rng, on_time_records, rates.older_version, counts, "flight_older_version",
               older_flight_version)
    records[:] = on_time_records


def older_booking_version(record):
    """What the booking looked like a day before its latest change."""
    earlier = record["_updated_at"] - timedelta(days=1)
    if record["status"] != "CONFIRMED":
        changed = {"status": "CONFIRMED"}
    else:
        changed = {"ancillary_amount": "0.00"}
    return dict(record, **changed, updated_at=stamp_utc(earlier), _updated_at=earlier)


def inject_booking_value_defect(rng, record, fx_by_date, rates, counts):
    defect = pick_one(rng, (
        ("ghost", rates.booking_ghost_flight),
        ("corrupted", rates.booking_corrupted_flight_no),
        ("non_positive", rates.booking_non_positive_fare),
        ("usd", rates.booking_usd_fare),
        ("outlier", rates.booking_fare_outlier),
        ("missing_required", rates.missing_required),
        ("missing_optional", rates.missing_optional),
    ))
    if defect is None:
        return
    record["_defective"] = True
    if defect == "ghost":
        record["flight_no"] = f"NV{rng.randint(9000, 9999)}"
        counts["booking_flight_never_exists"] += 1
    elif defect == "corrupted":
        record["flight_no"] = corrupt_flight_no(rng, record["flight_no"])
        counts["booking_corrupted_flight_no"] += 1
    elif defect == "non_positive":
        record["fare_amount"] = rng.choice(("0.00", "-" + record["fare_amount"]))
        counts["booking_non_positive_fare"] += 1
    elif defect == "usd":
        rate = fx_by_date[record["_truth"]["booked_at"].date()]
        record["fare_amount"] = f"{float(record['fare_amount']) / rate:.2f}"
        record["ancillary_amount"] = f"{float(record['ancillary_amount']) / rate:.2f}"
        record["currency"] = "USD"
        counts["booking_usd_fare"] += 1
    elif defect == "outlier":
        record["fare_amount"] = f"{float(record['fare_amount']) * rng.uniform(8, 15):.2f}"
        counts["booking_fare_outlier"] += 1
    elif defect == "missing_required":
        record[rng.choice(("booking_id", "passenger_id", "fare_amount", "cabin"))] = None
        counts["booking_missing_required"] += 1
    else:
        record[rng.choice(("channel", "ancillary_amount"))] = None
        counts["booking_missing_optional"] += 1


def inject_booking_defects(rng, records, day, last_day, later, fx_by_date, rates, counts):
    next_day = day + timedelta(days=1)
    for record in records:
        inject_booking_value_defect(rng, record, fx_by_date, rates, counts)
        if record.get("_defective"):
            continue
        if rng.random() < rates.flight_no_variant:
            record.update(flight_no=flight_no_variant(rng, record["flight_no"]), _variant=True)
        if next_day <= last_day and rng.random() < rates.booking_stale_resend:
            defer(later, next_day, older_booking_version(record))
            counts["booking_stale_version_resent_next_day"] += 1
    add_copies(rng, records, rates.exact_duplicate, counts, "booking_exact_duplicate", dict)
    add_copies(rng, records, rates.older_version, counts, "booking_older_version",
               older_booking_version)


def older_passenger_version(record):
    earlier = record["_updated_at"] - timedelta(days=3)
    return dict(record, loyalty_tier="NONE", updated_at=stamp_utc(earlier), _updated_at=earlier)


def inject_passenger_defects(rng, records, rates, counts):
    for record in records:
        defect = pick_one(rng, (("missing_required", rates.missing_required),
                                ("missing_optional", rates.missing_optional)))
        if defect == "missing_required":
            record.update(passenger_id=None, _defective=True)
            counts["passenger_missing_required"] += 1
        elif defect == "missing_optional":
            record[rng.choice(("email", "phone"))] = None
            record["_defective"] = True
            counts["passenger_missing_optional"] += 1
    add_copies(rng, records, rates.exact_duplicate, counts, "passenger_exact_duplicate", dict)
    add_copies(rng, records, rates.older_version, counts, "passenger_older_version",
               older_passenger_version)
