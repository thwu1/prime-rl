#!/usr/bin/env python3
"""Generate 30 years of synthetic weather station data and fire occurrence records.

Creates two CSV files:
- /app/weather_data.csv: Daily noon weather observations for 5 stations
- /app/fire_events.csv: Daily fire occurrence records (binary)

Weather is generated with realistic seasonal cycles, latitude-dependent
temperature amplitudes, and stochastic precipitation/humidity/wind.
Fire occurrence uses a logistic model correlated with fire-prone weather.
"""


import csv
import math
import os
import random
from datetime import date, timedelta

random.seed(42)

os.makedirs('/app', exist_ok=True)

stations = [
    {'id': 0, 'lat': 45.0},
    {'id': 1, 'lat': 55.0},
    {'id': 2, 'lat': 65.0},
    {'id': 3, 'lat': 10.0},
    {'id': 4, 'lat': -35.0},
]

start_date = date(1990, 1, 1)
end_date = date(2019, 12, 31)

weather_rows = []
fire_rows = []

current_date = start_date
while current_date <= end_date:
    doy = (current_date - date(current_date.year, 1, 1)).days + 1

    for station in stations:
        lat = station['lat']
        sid = station['id']

        # Temperature: seasonal cycle with latitude dependence
        abs_lat = abs(lat)
        amplitude = 15.0 * (0.3 + 0.7 * abs_lat / 60.0)
        base_temp = 25.0 - abs_lat * 0.35

        if lat >= 0:
            phase = doy - 80
        else:
            phase = doy - 80 + 182

        mean_temp = amplitude * math.sin(2.0 * math.pi * phase / 365.0) + base_temp
        temp = mean_temp + random.gauss(0, 3.0)

        # Precipitation: ~30% chance of rain, exponential intensity
        if random.random() < 0.3:
            precip = random.expovariate(1.0 / 5.0)
        else:
            precip = 0.0
        precip = max(precip, 0.0)

        # Relative humidity: anti-correlated with temperature
        humidity = 65.0 - 0.5 * temp + random.gauss(0, 10.0)
        humidity = max(10.0, min(99.0, humidity))

        # Wind speed
        wind = 12.0 + random.gauss(0, 5.0)
        wind = max(0.1, wind)

        weather_rows.append({
            'date': current_date.isoformat(),
            'station_id': sid,
            'lat': f'{lat:.1f}',
            'tas_degC': f'{temp:.4f}',
            'pr_mm': f'{precip:.4f}',
            'hurs_pct': f'{humidity:.4f}',
            'sfcWind_kmh': f'{wind:.4f}',
        })

        # Fire occurrence: logistic model based on weather conditions
        # Higher temp, lower precip, higher wind → more fire-prone
        z = 0.12 * (temp - 18.0) - 0.10 * precip + 0.03 * wind - 0.015 * humidity - 1.5
        fire_prob = 1.0 / (1.0 + math.exp(-z))
        fire = 1 if random.random() < fire_prob else 0

        fire_rows.append({
            'date': current_date.isoformat(),
            'station_id': sid,
            'fire_occurred': fire,
        })

    current_date += timedelta(days=1)

with open('/app/weather_data.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'date', 'station_id', 'lat', 'tas_degC', 'pr_mm', 'hurs_pct', 'sfcWind_kmh'
    ])
    writer.writeheader()
    writer.writerows(weather_rows)

with open('/app/fire_events.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'date', 'station_id', 'fire_occurred'
    ])
    writer.writeheader()
    writer.writerows(fire_rows)

print(f"Generated {len(weather_rows)} weather rows, {len(fire_rows)} fire event rows")
