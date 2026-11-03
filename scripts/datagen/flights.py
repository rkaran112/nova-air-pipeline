"""Simulate what actually happened to each scheduled flight on one day.

The output is the "truth": clean Python values in IST. Formatting into messy
source records happens later, in sources.py.
"""

from datetime import datetime, timedelta

from . import patterns


def simulate_day(rng, plan, day, fleet):
    """Return one truth record per leg in the plan for this date."""
    flights = []
    lateness_by_aircraft = {}
    for leg in plan:
        aircraft = leg["aircraft_index"]
        midnight = datetime(day.year, day.month, day.day)
        sched_dep = midnight + timedelta(minutes=leg["departure_minute"])
        sched_arr = sched_dep + timedelta(minutes=leg["block_minutes"])

        flight = {
            "flight_no": leg["flight_no"],
            "flight_date": day,
            "origin": leg["origin"],
            "destination": leg["destination"],
            "aircraft_reg": fleet[aircraft],
            "leg_number": leg["leg_number"],
            "sched_dep": sched_dep,
            "sched_arr": sched_arr,
            "actual_dep": None,
            "actual_arr": None,
            "status": "OPERATED",
            "delay_code": None,
        }

        cancel_chance = patterns.cancellation_probability(leg["origin"], leg["destination"],
                                                          sched_dep)
        if rng.random() < cancel_chance:
            flight["status"] = "CANCELLED"
            flight["delay_code"] = patterns.primary_delay(
                rng, leg["origin"], leg["destination"], sched_dep, sched_arr,
                leg["leg_number"])[1] or "41"
            # The next leg is flown by a stand-by aircraft, so lateness doesn't carry over.
            lateness_by_aircraft[aircraft] = 0
            flights.append(flight)
            continue

        own_minutes, own_code = patterns.primary_delay(
            rng, leg["origin"], leg["destination"], sched_dep, sched_arr, leg["leg_number"])
        inherited = max(0, lateness_by_aircraft.get(aircraft, 0)
                        - patterns.TURNAROUND_SLACK_MINUTES)
        if inherited > own_minutes:
            departure_delay, code = inherited, "93"
        else:
            departure_delay, code = own_minutes, own_code
        if departure_delay < 5:
            departure_delay = rng.randint(-4, 4)

        actual_block = leg["block_minutes"] + rng.randint(-8, 10)
        flight["actual_dep"] = sched_dep + timedelta(minutes=departure_delay)
        flight["actual_arr"] = flight["actual_dep"] + timedelta(minutes=actual_block)
        arrival_delay = (flight["actual_arr"] - sched_arr).total_seconds() / 60
        flight["delay_code"] = code if departure_delay > 15 else None
        lateness_by_aircraft[aircraft] = max(0, arrival_delay)
        flights.append(flight)
    return flights
