"""Turn truth values into source records shaped like the real feeds.

Every value becomes text, the way it would arrive from another system. Keys that
start with "_" carry truth values for defects.py and are dropped before writing.
"""

from datetime import timedelta

IST_OFFSET = timedelta(hours=5, minutes=30)
TIME_ONLY_ARRIVAL_SHARE = 0.10
PROMO_CODES = ("NOVA10", "FESTIVE15", "FLYNOW", "STUDENT5")
PROMO_SHARE = 0.12


def format_timestamp(rng, ist_value, counts):
    """Write one IST timestamp in one of three formats, as different systems do."""
    roll = rng.random()
    if roll < 0.5:
        return ist_value.strftime("%Y-%m-%d %H:%M:%S+05:30")
    if roll < 0.8:
        counts["timestamp_written_as_utc"] += 1
        return (ist_value - IST_OFFSET).strftime("%Y-%m-%dT%H:%M:%SZ")
    counts["timestamp_written_day_first_no_zone"] += 1
    return ist_value.strftime("%d/%m/%Y %H:%M")


def flight_record(rng, flight, counts):
    overnight = flight["sched_arr"].date() > flight["sched_dep"].date()
    # The ops system drops the arrival date on overnight legs, and sometimes on others.
    time_only = overnight or rng.random() < TIME_ONLY_ARRIVAL_SHARE

    def arrival(value):
        if value is None:
            return None
        return value.strftime("%H:%M") if time_only else format_timestamp(rng, value, counts)

    def stamp(value):
        return None if value is None else format_timestamp(rng, value, counts)

    exported_at = flight["sched_dep"].replace(hour=23, minute=50) + timedelta(
        minutes=rng.randint(0, 60))
    return {
        "flight_no": flight["flight_no"],
        "flight_date": flight["flight_date"].isoformat(),
        "origin": flight["origin"],
        "destination": flight["destination"],
        "sched_dep": stamp(flight["sched_dep"]),
        "sched_arr": arrival(flight["sched_arr"]),
        "actual_dep": stamp(flight["actual_dep"]),
        "actual_arr": arrival(flight["actual_arr"]),
        "aircraft_reg": flight["aircraft_reg"],
        "status": flight["status"],
        "delay_code": flight["delay_code"],
        "updated_at": stamp(exported_at),
        "_truth": flight,
        "_updated_at": exported_at,
        "_overnight": overnight,
    }


def money(value):
    return f"{value:.2f}"


def booking_record(rng, booking, include_promo, counts):
    record = {
        "booking_id": booking["booking_id"],
        "pnr": booking["pnr"],
        "passenger_id": booking["passenger_id"],
        "flight_no": booking["flight_no"],
        "flight_date": booking["flight_date"].isoformat(),
        "origin": booking["origin"],
        "cabin": booking["cabin"],
        "fare_amount": money(booking["fare_inr"]),
        "currency": "INR",
        "ancillary_amount": money(booking["ancillary_inr"]),
        "channel": booking["channel"],
        "status": booking["status"],
        "booked_at": format_timestamp(rng, booking["booked_at"], counts),
        "updated_at": format_timestamp(rng, booking["updated_at"], counts),
        "_truth": booking,
        "_updated_at": booking["updated_at"],
    }
    if include_promo:
        record["promo_code"] = rng.choice(PROMO_CODES) if rng.random() < PROMO_SHARE else None
    return record


def passenger_record(rng, passenger, counts):
    return {
        "passenger_id": passenger["passenger_id"],
        "full_name": passenger["full_name"],
        "email": passenger["email"],
        "phone": passenger["phone"],
        "date_of_birth": passenger["date_of_birth"].isoformat(),
        "loyalty_tier": passenger["loyalty_tier"],
        "updated_at": format_timestamp(rng, passenger["updated_at"], counts),
        "_updated_at": passenger["updated_at"],
    }
