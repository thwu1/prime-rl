#!/usr/bin/env python3
"""Generate synthetic environmental monitoring data for the contamination pipeline task.
Deterministic with seed 42 - produces identical output on every run.
Uses only Python standard library.
"""

import random
import json
import os
import csv
import math

random.seed(42)

os.makedirs('/app/data', exist_ok=True)

# ============================================================
# 1. Site metadata (20 monitoring sites)
# ============================================================
sites = []
base_lat, base_lon = 42.35, -71.05

for i in range(20):
    site_id = f"S{i+1:03d}"
    lat = round(base_lat + random.uniform(-0.3, 0.3), 6)
    lon = round(base_lon + random.uniform(-0.3, 0.3), 6)
    site_type = "marine" if i < 12 else "freshwater"
    ej_pct = round(random.uniform(10, 95), 1)
    community = f"District_{chr(65 + i % 5)}"
    name = f"{'Coastal' if site_type == 'marine' else 'Inland'}_Site_{i+1}"

    sites.append({
        "site_id": site_id,
        "name": name,
        "latitude": lat,
        "longitude": lon,
        "type": site_type,
        "community": community,
        "ej_population_pct": ej_pct
    })

with open('/app/data/site_metadata.json', 'w') as f:
    json.dump(sites, f, indent=2)

# ============================================================
# 2. Weather station locations (3 stations)
# ============================================================
stations = [
    {"station_id": "WX01", "name": "Harbor_Central", "latitude": 42.36, "longitude": -71.04},
    {"station_id": "WX02", "name": "North_Point",    "latitude": 42.55, "longitude": -70.88},
    {"station_id": "WX03", "name": "South_Bay",      "latitude": 42.12, "longitude": -71.22},
]

with open('/app/data/station_locations.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["station_id", "name", "latitude", "longitude"])
    for s in stations:
        writer.writerow([s["station_id"], s["name"], s["latitude"], s["longitude"]])

# ============================================================
# 3. Daily weather observations (fixed-width format)
#    Field widths: StationID(4) Date(10) TempC(7) RH%(4) PrecipMM(8) WindKph(6)
#    Total = 39 characters per data line
# ============================================================
with open('/app/data/weather_daily.fwf', 'w') as f:
    f.write("# Coastal Environmental Monitoring Network - Daily Weather Observations\n")
    f.write("# Format: Fixed-width fields. See weather_format.txt for specifications.\n")
    f.write("# Coverage: 2019-01-01 through 2022-12-31\n")
    f.write("#\n")

    for year in range(2019, 2023):
        is_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
        days_per_month = [31, 29 if is_leap else 28, 31, 30, 31, 30,
                          31, 31, 30, 31, 30, 31]

        for month_idx, ndays in enumerate(days_per_month):
            month = month_idx + 1
            for day in range(1, ndays + 1):
                date_str = f"{year}-{month:02d}-{day:02d}"
                day_of_year = sum(days_per_month[:month_idx]) + day

                for station in stations:
                    sid = station["station_id"]

                    # Seasonal patterns
                    season = math.sin(2 * math.pi * (day_of_year - 80) / 365)

                    temp = round(10 + 12 * season + random.gauss(0, 3), 1)
                    rh = int(65 + 10 * season + random.gauss(0, 8))
                    rh = max(15, min(100, rh))

                    precip_chance = 0.25 + 0.1 * abs(math.sin(
                        2 * math.pi * (day_of_year - 45) / 365))
                    if random.random() < precip_chance:
                        precip = round(random.expovariate(1 / 6.0), 1)
                    else:
                        precip = 0.0

                    wind = round(max(0.1, 4 + random.gauss(0, 2.5)), 1)

                    # Inject missing-value sentinels (~1%)
                    if random.random() < 0.01:
                        temp = -99.9
                    if random.random() < 0.01:
                        rh = -9
                    if random.random() < 0.008:
                        precip = -99.9
                    if random.random() < 0.005:
                        wind = -9.9

                    # Write fixed-width line (39 chars)
                    f.write(f"{sid:4s}{date_str:10s}{temp:7.1f}{rh:4d}{precip:8.1f}{wind:6.1f}\n")

        # Blank line between years (realistic formatting artifact)
        if year < 2022:
            f.write("\n")

# ============================================================
# 4. Water quality CSV files (schema evolves across years)
#    2019-2020: SiteID, SampleDate, BacteriaCount, WaterTemp, Notes
#               2019 dates in MM/DD/YYYY format
#               2020 dates in YYYY-MM-DD format
#    2021:      site_id, sample_date, ecoli_cfu_per_100ml, water_temp_celsius, comments
#    2022:      site_id, sample_date, ecoli_cfu_per_100ml, water_temp_celsius,
#               turbidity_ntu, comments
# ============================================================
for year in range(2019, 2023):
    rows = []
    for site in sites:
        n_samples = random.randint(8, 15)
        for _ in range(n_samples):
            month = random.choice([5, 6, 7, 8, 9])
            day = random.randint(1, 28)

            # Date format differs by year
            if year == 2019:
                date_str = f"{month:02d}/{day:02d}/{year}"
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"

            # Contamination model
            base = 80 if site["type"] == "marine" else 120
            ej_factor = site["ej_population_pct"] * 0.5
            seasonal = 30 * math.sin(2 * math.pi * (month - 4) / 12)

            # Noise with heavy tail (3% spikes)
            if random.random() < 0.03:
                noise = random.expovariate(1 / 300.0)
            else:
                noise = random.expovariate(1 / 60.0)

            bacteria = int(max(0, base + ej_factor + seasonal + noise))

            # Data-quality issues
            r = random.random()
            if r < 0.015:
                bacteria_str = "-1"        # sensor error
            elif r < 0.035:
                bacteria_str = ""          # missing
            elif year == 2019 and r < 0.065:
                bacteria_str = f">{random.choice([2419, 2420, 2419])}"
            else:
                bacteria_str = str(bacteria)

            water_temp = round(
                18 + 5 * math.sin(2 * math.pi * (month - 3) / 12)
                + random.gauss(0, 2), 1)

            if year <= 2020:
                row = {
                    "SiteID": site["site_id"],
                    "SampleDate": date_str,
                    "BacteriaCount": bacteria_str,
                    "WaterTemp": water_temp,
                    "Notes": "resampled" if random.random() < 0.08 else ""
                }
            elif year == 2021:
                row = {
                    "site_id": site["site_id"],
                    "sample_date": date_str,
                    "ecoli_cfu_per_100ml": bacteria_str,
                    "water_temp_celsius": water_temp,
                    "comments": "resampled" if random.random() < 0.08 else ""
                }
            else:
                turb = round(max(0, 5 + random.expovariate(1 / 3.0)), 1) \
                    if bacteria_str not in ("", "-1") else ""
                row = {
                    "site_id": site["site_id"],
                    "sample_date": date_str,
                    "ecoli_cfu_per_100ml": bacteria_str,
                    "water_temp_celsius": water_temp,
                    "turbidity_ntu": turb,
                    "comments": "resampled" if random.random() < 0.08 else ""
                }

            rows.append(row)

    fname = f"/app/data/water_quality_{year}.csv"
    with open(fname, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

print("Data generation complete.")
print(f"  Sites:    {len(sites)}")
print(f"  Stations: {len(stations)}")
print(f"  Years:    2019-2022")
