"""Nova Air's daily timetable: which aircraft flies which legs, and when.

Each rotation is one aircraft's day: it leaves its base, flies out and back twice,
and ends at base. Flying every rotation once a day gives 20 flights. The medium
profile repeats each rotation in several "waves", each with its own aircraft,
spaced out through the day.
"""

from .reference import distance_km

# base airport, airports visited in order, first departure (IST), minutes between waves
ROTATIONS = (
    ("BOM", ("DEL", "BOM", "GOI", "BOM"), "06:00", 50),
    ("DEL", ("BLR", "DEL", "HYD", "DEL"), "06:10", 50),
    ("BLR", ("BOM", "BLR", "CCU", "BLR"), "14:30", -60),
    ("DEL", ("MAA", "DEL", "PNQ", "DEL"), "06:30", 50),
    ("BLR", ("COK", "BLR", "AMD", "BLR"), "16:30", -60),
)

TURNAROUND_MINUTES = 45
MINUTES_PER_DAY = 24 * 60


def block_minutes(origin, destination):
    """Scheduled gate-to-gate time: 30 minutes of taxiing plus about 750 km/h cruise."""
    raw = 30 + distance_km(origin, destination) / 12.5
    return int(5 * round(raw / 5))


def to_minutes(hhmm):
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def daily_plan(waves):
    """Return the legs flown every day, as dicts, ordered by aircraft then leg."""
    legs = []
    for rotation_index, (base, stops, first_departure, wave_gap) in enumerate(ROTATIONS):
        for wave in range(waves):
            aircraft_index = rotation_index * waves + wave
            departure = to_minutes(first_departure) + wave * wave_gap
            origin = base
            for leg_number, destination in enumerate(stops, start=1):
                block = block_minutes(origin, destination)
                # A leg departing after midnight would belong to tomorrow's timetable.
                if departure < MINUTES_PER_DAY:
                    legs.append({
                        "flight_no": f"NV{1000 + wave * 100 + rotation_index * 10 + leg_number}",
                        "aircraft_index": aircraft_index,
                        "leg_number": leg_number,
                        "origin": origin,
                        "destination": destination,
                        "departure_minute": departure,
                        "block_minutes": block,
                    })
                departure += block + TURNAROUND_MINUTES
                origin = destination
    return legs


def aircraft_count(waves):
    return len(ROTATIONS) * waves
