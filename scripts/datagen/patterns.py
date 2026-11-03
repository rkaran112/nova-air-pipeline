"""SPOILER: the hidden business patterns. Don't read this before doing the practice drills.

Everything here shapes what really happened (delays, cancellations, demand, fares).
The answer key is docs/GENERATOR_ANSWER_KEY.md.
"""

from datetime import date

# Pattern 1: Mumbai monsoon, July to September.
MONSOON_AIRPORT = "BOM"
MONSOON_MONTHS = (7, 8, 9)

# Pattern 2: Delhi winter fog, December mornings (local time).
FOG_AIRPORT = "DEL"
FOG_MONTH = 12
FOG_LAST_HOUR = 10

# Pattern 4: a busy route with a fare war: full planes, cheap seats.
FARE_WAR_ROUTES = (("DEL", "BOM"), ("BOM", "DEL"))
FARE_WAR_LOAD_FACTOR = 0.93
FARE_WAR_PRICE_FACTOR = 0.55

# Pattern 5: a route that never fills.
WEAK_ROUTES = (("BLR", "COK"), ("COK", "BLR"))
WEAK_LOAD_FACTOR = 0.50

NORMAL_LOAD_FACTOR = 0.80

# Pattern 6: festival demand. Diwali fell on 20 Oct 2025.
FESTIVALS = (
    (date(2025, 10, 14), date(2025, 10, 24), 0.08, 1.30),  # Diwali: +LF, x fare
    (date(2025, 12, 20), date(2025, 12, 31), 0.05, 1.15),  # Christmas and New Year
)

ROUTINE_DELAY_CODES = ("15", "18", "32", "41", "63", "81")

# Pattern 3: delays build up through the day. Each aircraft passes most of its
# lateness on to its next leg (flights.py), and small problems get more likely
# as the day gets busier.
TURNAROUND_SLACK_MINUTES = 5
ROUTINE_DELAY_CHANCE_FIRST_LEG = 0.08
ROUTINE_DELAY_CHANCE_PER_LATER_LEG = 0.05


def primary_delay(rng, origin, destination, departure_ist, arrival_ist, leg_number):
    """Return (minutes, delay_code) for the leg's own problems, before knock-on delay."""
    candidates = [(0, None)]
    routine_chance = (ROUTINE_DELAY_CHANCE_FIRST_LEG
                      + ROUTINE_DELAY_CHANCE_PER_LATER_LEG * (leg_number - 1))
    if rng.random() < routine_chance:
        candidates.append((10 + rng.expovariate(1 / 20), rng.choice(ROUTINE_DELAY_CODES)))

    month = departure_ist.month
    if month in MONSOON_MONTHS and MONSOON_AIRPORT in (origin, destination):
        if rng.random() < 0.35:
            code = "71" if origin == MONSOON_AIRPORT else "73"
            candidates.append((20 + rng.expovariate(1 / 40), code))

    fog_at_departure = origin == FOG_AIRPORT and departure_ist.hour < FOG_LAST_HOUR
    fog_at_arrival = destination == FOG_AIRPORT and arrival_ist.hour < FOG_LAST_HOUR + 1
    if month == FOG_MONTH and (fog_at_departure or fog_at_arrival):
        if rng.random() < 0.55:
            code = "71" if fog_at_departure else "73"
            candidates.append((30 + rng.expovariate(1 / 60), code))

    minutes, code = max(candidates, key=lambda c: c[0])
    return round(minutes), code


def cancellation_probability(origin, destination, departure_ist):
    probability = 0.008
    month = departure_ist.month
    if month in MONSOON_MONTHS and MONSOON_AIRPORT in (origin, destination):
        probability += 0.02
    if month == FOG_MONTH and FOG_AIRPORT in (origin, destination) and departure_ist.hour < 11:
        probability += 0.03
    return probability


def festival_effect(day):
    """Return (extra load factor, fare multiplier) for the flight date."""
    for start, end, extra_load, fare_multiplier in FESTIVALS:
        if start <= day <= end:
            return extra_load, fare_multiplier
    return 0.0, 1.0


def base_load_factor(origin, destination):
    if (origin, destination) in FARE_WAR_ROUTES:
        return FARE_WAR_LOAD_FACTOR
    if (origin, destination) in WEAK_ROUTES:
        return WEAK_LOAD_FACTOR
    return NORMAL_LOAD_FACTOR


def economy_load_factor(rng, origin, destination, day):
    weekday_effect = {4: 0.05, 6: 0.05, 1: -0.05, 2: -0.05}.get(day.weekday(), 0.0)
    extra_load, _ = festival_effect(day)
    value = (base_load_factor(origin, destination) + weekday_effect + extra_load
             + rng.gauss(0, 0.05))
    return min(1.0, max(0.2, value))


def economy_base_fare(origin, destination, distance):
    fare = 1800 + 3.0 * distance
    if (origin, destination) in FARE_WAR_ROUTES:
        fare *= FARE_WAR_PRICE_FACTOR
    return fare


def fare_multiplier(rng, day, lead_days):
    """Late bookings cost more; festivals cost more; plus some random spread."""
    lead_effect = 1.6 - 0.6 * min(lead_days, 45) / 45
    _, festival_multiplier = festival_effect(day)
    return lead_effect * festival_multiplier * rng.lognormvariate(0, 0.15)
