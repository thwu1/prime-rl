"""Generate input data files for the climate pipeline task.

Creates three variants of a monthly gridded temperature field
using different CF calendar conventions.
"""

import json
import math
import os


def is_leap_year(year):
    """Check if a year is a leap year in the Gregorian calendar."""
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def standard_month_days(year, month):
    """Get days in a month for the standard (Gregorian) calendar."""
    base = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    d = base[month - 1]
    if month == 2 and is_leap_year(year):
        d = 29
    return d


def generate_field(calendar, reference_year=2003, n_months=48):
    """Generate a synthetic temperature field with the given calendar.

    Data formula: T(t, i, j) = 250.0 + 0.5*t + 0.1*i + 0.01*j
    Grid: 4 latitudes x 6 longitudes
    Time: n_months consecutive months starting from January of reference_year
    """
    lat_bounds = [[-90, -45], [-45, 0], [0, 45], [45, 90]]
    lon_bounds = [
        [0, 60], [60, 120], [120, 180],
        [180, 240], [240, 300], [300, 360],
    ]

    # Compute time bounds based on calendar
    time_bounds = []
    cumulative = 0.0
    for t in range(n_months):
        year = reference_year + t // 12
        month = (t % 12) + 1

        if calendar == 'standard':
            days = standard_month_days(year, month)
        elif calendar == '360_day':
            days = 30
        elif calendar == 'noleap':
            noleap_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            days = noleap_days[month - 1]
        else:
            raise ValueError(f"Unknown calendar: {calendar}")

        time_bounds.append([cumulative, cumulative + days])
        cumulative += days

    # Generate data: T(t, i, j) = 250.0 + 0.5*t + 0.1*i + 0.01*j
    nlat = len(lat_bounds)
    nlon = len(lon_bounds)
    data = []
    for t in range(n_months):
        grid = []
        for i in range(nlat):
            row = []
            for j in range(nlon):
                row.append(250.0 + 0.5 * t + 0.1 * i + 0.01 * j)
            grid.append(row)
        data.append(grid)

    return {
        'properties': {
            'standard_name': 'air_temperature',
            'units': 'K',
        },
        'coordinates': {
            'time': {
                'units': f'days since {reference_year}-01-01',
                'calendar': calendar,
                'bounds': time_bounds,
            },
            'latitude': {
                'units': 'degrees_north',
                'bounds': lat_bounds,
            },
            'longitude': {
                'units': 'degrees_east',
                'bounds': lon_bounds,
            },
        },
        'reference_year': reference_year,
        'n_months': n_months,
        'data': data,
    }


def main():
    os.makedirs('/app/data', exist_ok=True)

    for calendar, filename in [
        ('standard', 'field_standard.json'),
        ('360_day', 'field_360day.json'),
        ('noleap', 'field_noleap.json'),
    ]:
        field = generate_field(calendar)
        with open(f'/app/data/{filename}', 'w') as f:
            json.dump(field, f, indent=2)
        print(f"Generated {filename}")


if __name__ == '__main__':
    main()
