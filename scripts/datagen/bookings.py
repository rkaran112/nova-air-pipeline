"""Simulate passengers and their bookings for each flight (truth values, in IST)."""

from datetime import date, timedelta

from . import patterns
from .reference import SEATS_ECONOMY, SEATS_PLUS

TIERS = ("NONE", "BLUE", "SILVER", "GOLD")
NEW_PASSENGER_TIER_WEIGHTS = (70, 20, 8, 2)
CHANNELS = ("WEB", "APP", "OTA", "AGENT")
CHANNEL_WEIGHTS = (55, 30, 10, 5)
ANCILLARY_PRICES = (199, 349, 499, 799, 1299)
EMAIL_DOMAINS = ("gmail.com", "yahoo.co.in", "outlook.com", "rediffmail.com", "hotmail.com")
PNR_CHARACTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
RETURNING_PASSENGER_SHARE = 0.35
TIER_UPGRADE_CHANCE = 0.05
PLUS_FARE_MULTIPLIER = 2.1


def new_state(max_pool):
    """Everything that has to persist from one flight to the next, in one place."""
    return {"pool": [], "max_pool": max_pool, "next_passenger": 1, "next_booking": 1}


def new_passenger(rng, fake, state, created_at):
    first, last = fake.first_name(), fake.last_name()
    handle = f"{first}.{last}".lower().replace(" ", "").replace("'", "")
    passenger = {
        "passenger_id": f"P{state['next_passenger']:08d}",
        "full_name": f"{first} {last}",
        "email": f"{handle}{rng.randint(1, 999)}@{rng.choice(EMAIL_DOMAINS)}",
        "phone": f"+91 {rng.randint(6, 9)}{rng.randint(0, 999_999_999):09d}",
        "date_of_birth": date(1950, 1, 1) + timedelta(days=rng.randint(0, 20_500)),
        "loyalty_tier": rng.choices(TIERS, NEW_PASSENGER_TIER_WEIGHTS)[0],
        "updated_at": created_at,
    }
    state["next_passenger"] += 1
    return passenger


def remember(rng, state, passenger):
    pool = state["pool"]
    if len(pool) < state["max_pool"]:
        pool.append(passenger)
    else:
        pool[rng.randrange(len(pool))] = passenger


def pick_passenger(rng, fake, state, created_at, upgraded_at, profile_updates):
    """Return a passenger for one seat; new or changed profiles go into profile_updates."""
    pool = state["pool"]
    if pool and rng.random() < RETURNING_PASSENGER_SHARE:
        passenger = rng.choice(pool)
        tier_index = TIERS.index(passenger["loyalty_tier"])
        if tier_index < len(TIERS) - 1 and rng.random() < TIER_UPGRADE_CHANCE:
            passenger["loyalty_tier"] = TIERS[tier_index + 1]
            # Upgrades are stamped on the travel day, so each new version is newer.
            passenger["updated_at"] = upgraded_at
            profile_updates.append(dict(passenger))
        return passenger
    passenger = new_passenger(rng, fake, state, created_at)
    remember(rng, state, passenger)
    profile_updates.append(dict(passenger))
    return passenger


def seats_sold(rng, flight):
    economy_lf = patterns.economy_load_factor(rng, flight["origin"], flight["destination"],
                                              flight["flight_date"])
    plus_lf = min(1.0, max(0.0, economy_lf * 0.7 + rng.gauss(0, 0.1)))
    economy = min(SEATS_ECONOMY, max(0, round(rng.gauss(economy_lf * SEATS_ECONOMY, 4))))
    return {"ECONOMY": economy, "PLUS": round(plus_lf * SEATS_PLUS)}


def booking_status(rng, flight):
    if flight["status"] == "CANCELLED":
        return "CANCELLED"
    return rng.choices(("CONFIRMED", "NO_SHOW", "CANCELLED"), (93, 4, 3))[0]


def status_time(rng, status, flight, booked_at):
    if status == "NO_SHOW":
        return flight["sched_dep"] + timedelta(hours=2)
    if status == "CANCELLED" and flight["status"] == "CANCELLED":
        return flight["sched_dep"] - timedelta(hours=3)
    if status == "CANCELLED":
        return booked_at + (flight["sched_dep"] - booked_at) * rng.random()
    return booked_at


def bookings_for_flight(rng, fake, state, flight, distance, profile_updates):
    """Return truth bookings for one flight, grouped into PNRs of one to three people."""
    bookings = []
    base_fare = patterns.economy_base_fare(flight["origin"], flight["destination"], distance)
    for cabin, seats in seats_sold(rng, flight).items():
        remaining = seats
        while remaining > 0:
            group_size = min(remaining, rng.choices((1, 2, 3), (60, 30, 10))[0])
            remaining -= group_size
            lead_days = min(90, 1 + int(rng.expovariate(1 / 18)))
            booked_at = flight["sched_dep"] - timedelta(days=lead_days,
                                                        minutes=rng.randint(0, 600))
            pnr = "".join(rng.choices(PNR_CHARACTERS, k=6))
            channel = rng.choices(CHANNELS, CHANNEL_WEIGHTS)[0]
            fare = base_fare * patterns.fare_multiplier(rng, flight["flight_date"], lead_days)
            if cabin == "PLUS":
                fare *= PLUS_FARE_MULTIPLIER
            for _ in range(group_size):
                passenger = pick_passenger(rng, fake, state, booked_at,
                                           flight["sched_dep"] - timedelta(hours=1),
                                           profile_updates)
                status = booking_status(rng, flight)
                ancillary_chance = 0.6 if cabin == "PLUS" else 0.35
                ancillary = rng.choice(ANCILLARY_PRICES) if rng.random() < ancillary_chance else 0
                bookings.append({
                    "booking_id": f"B{state['next_booking']:09d}",
                    "pnr": pnr,
                    "passenger_id": passenger["passenger_id"],
                    "flight_no": flight["flight_no"],
                    "flight_date": flight["flight_date"],
                    "origin": flight["origin"],
                    "cabin": cabin,
                    "fare_inr": round(fare),
                    "ancillary_inr": ancillary,
                    "channel": channel,
                    "status": status,
                    "booked_at": booked_at,
                    "updated_at": status_time(rng, status, flight, booked_at),
                })
                state["next_booking"] += 1
    return bookings
