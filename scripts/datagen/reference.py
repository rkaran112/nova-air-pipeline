"""Static reference data: airports, aircraft, delay codes and FX rates."""

import math
import string
from datetime import timedelta

# code, name, city, state, latitude, longitude
AIRPORTS = (
    ("AMD", "Sardar Vallabhbhai Patel International", "Ahmedabad", "Gujarat", 23.0772, 72.6347),
    ("BLR", "Kempegowda International", "Bengaluru", "Karnataka", 13.1986, 77.7066),
    ("BOM", "Chhatrapati Shivaji Maharaj International", "Mumbai", "Maharashtra", 19.0896, 72.8656),
    ("CCU", "Netaji Subhas Chandra Bose International", "Kolkata", "West Bengal", 22.6547, 88.4467),
    ("COK", "Cochin International", "Kochi", "Kerala", 10.1520, 76.4019),
    ("DEL", "Indira Gandhi International", "Delhi", "Delhi", 28.5562, 77.1000),
    ("GOI", "Dabolim", "Goa", "Goa", 15.3808, 73.8314),
    ("HYD", "Rajiv Gandhi International", "Hyderabad", "Telangana", 17.2403, 78.4294),
    ("MAA", "Chennai International", "Chennai", "Tamil Nadu", 12.9941, 80.1709),
    ("PNQ", "Pune International", "Pune", "Maharashtra", 18.5822, 73.9197),
)

AIRCRAFT_TYPE = "A320neo"
SEATS_PLUS = 12
SEATS_ECONOMY = 174

# IATA-style delay codes, grouped into the categories the dashboard shows.
DELAY_CODES = (
    ("15", "Boarding: passenger discrepancies or late passengers", "Passenger"),
    ("18", "Baggage processing", "Ground handling"),
    ("32", "Loading and ground handling", "Ground handling"),
    ("41", "Aircraft defect", "Technical"),
    ("63", "Late crew boarding", "Crew"),
    ("71", "Weather at departure airport", "Weather"),
    ("73", "Weather en route or at destination", "Weather"),
    ("81", "Air traffic control flow restriction", "Air traffic control"),
    ("93", "Late arrival of aircraft from previous leg", "Reactionary"),
)

FX_START_RATE = 85.8  # INR per USD at the start of the series


def coordinates(code):
    for airport in AIRPORTS:
        if airport[0] == code:
            return airport[4], airport[5]
    raise ValueError(f"unknown airport {code}")


def distance_km(origin, destination):
    """Great-circle distance: the shortest path over the Earth's surface."""
    lat1, lon1 = (math.radians(x) for x in coordinates(origin))
    lat2, lon2 = (math.radians(x) for x in coordinates(destination))
    a = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(a))


def fleet_registrations(count):
    """Indian registrations look like VT-ABC; Nova Air's all start VT-N."""
    letters = string.ascii_uppercase
    return tuple(f"VT-N{letters[i // 26]}{letters[i % 26]}" for i in range(count))


def fx_rows(rng, start_date, end_date):
    """Daily USD to INR rates as a small random walk, one row per calendar day."""
    rows = []
    rate = FX_START_RATE
    day = start_date
    while day <= end_date:
        rate = round(rate + rng.gauss(0, 0.12), 4)
        rows.append({"rate_date": day.isoformat(), "from_currency": "USD",
                     "to_currency": "INR", "rate": f"{rate:.4f}"})
        day += timedelta(days=1)
    return rows


def airport_rows():
    return [{"airport_code": a[0], "airport_name": a[1], "city": a[2], "state": a[3],
             "latitude": f"{a[4]:.4f}", "longitude": f"{a[5]:.4f}"} for a in AIRPORTS]


def aircraft_rows(registrations):
    return [{"aircraft_reg": reg, "aircraft_type": AIRCRAFT_TYPE,
             "seats_plus": str(SEATS_PLUS), "seats_economy": str(SEATS_ECONOMY),
             "seats_total": str(SEATS_PLUS + SEATS_ECONOMY)} for reg in registrations]


def delay_code_rows():
    return [{"delay_code": c[0], "description": c[1], "category": c[2]} for c in DELAY_CODES]
