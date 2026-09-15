"""CF-compliant seasonal climatological mean pipeline - corrected version.

All bugs from the original pipeline.py have been fixed:
1. Area weights: use spherical solid angle |sin(lat2)-sin(lat1)|*dlon
2. DJF assignment: December of year Y belongs to DJF of year Y+1
3. Two-stage collapse: within-year weighted means, then average over years
4. Incomplete season filtering: exclude seasons with < 3 months
5. Cell methods: include within/over qualifiers
6. Day counts: derive from time bounds, not hardcoded tables
"""


import json
import math


# Standard calendar month lengths (kept for API compatibility but unused)
STANDARD_MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def compute_area_weights(lat_bounds, lon_bounds):
    """Compute area weights using spherical solid angle formula.

    Weight = |sin(lat_top) - sin(lat_bottom)| * delta_lon_radians
    """
    weights = []
    for lb in lat_bounds:
        row = []
        delta_sin = abs(math.sin(math.radians(lb[1])) - math.sin(math.radians(lb[0])))
        for lonb in lon_bounds:
            dlon = math.radians(abs(lonb[1] - lonb[0]))
            row.append(delta_sin * dlon)
        weights.append(row)
    return weights


def get_month_info(time_index, reference_year):
    """Convert a time index to (year, month) tuple."""
    year = reference_year + time_index // 12
    month = (time_index % 12) + 1
    return (year, month)


def is_leap_year(year):
    """Check if a year is a leap year in the standard calendar."""
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def get_day_counts(time_bounds, calendar, reference_year, n_months):
    """Get day counts from time coordinate bounds.

    Uses the actual bounds from the data rather than hardcoded tables,
    ensuring correct day counts for all calendar types.
    """
    return [float(time_bounds[t][1] - time_bounds[t][0]) for t in range(n_months)]


def assign_seasons(n_months, reference_year):
    """Assign time indices to meteorological seasons with DJF year-shift.

    December of year Y is assigned to DJF of year Y+1.
    Incomplete seasons (fewer than 3 months) are excluded.
    """
    SEASON_MAP = {
        12: 'DJF', 1: 'DJF', 2: 'DJF',
        3: 'MAM', 4: 'MAM', 5: 'MAM',
        6: 'JJA', 7: 'JJA', 8: 'JJA',
        9: 'SON', 10: 'SON', 11: 'SON',
    }
    seasons = {}
    for t in range(n_months):
        year, month = get_month_info(t, reference_year)
        season_name = SEASON_MAP[month]
        if month == 12:
            season_year = year + 1
        else:
            season_year = year
        key = (season_year, season_name)
        if key not in seasons:
            seasons[key] = []
        seasons[key].append(t)

    return {k: v for k, v in seasons.items() if len(v) == 3}


def collapse_time_weighted(data, indices, day_counts):
    """Compute day-weighted mean over specified time indices."""
    nlat = len(data[0])
    nlon = len(data[0][0])
    total_days = sum(day_counts[i] for i in indices)
    result = [[0.0] * nlon for _ in range(nlat)]
    for idx in indices:
        w = day_counts[idx] / total_days
        for i in range(nlat):
            for j in range(nlon):
                result[i][j] += w * data[idx][i][j]
    return result


def climatological_mean(data, seasons, day_counts):
    """Compute two-stage climatological mean for each season.

    Stage 1: Compute day-weighted mean within each year's season instance.
    Stage 2: Compute unweighted average of those per-year means over years.
    """
    season_instances = {}
    for (yr, sn), indices in seasons.items():
        if sn not in season_instances:
            season_instances[sn] = []
        season_instances[sn].append(indices)

    result = {}
    for sn, instance_list in season_instances.items():
        nlat = len(data[0])
        nlon = len(data[0][0])

        year_means = []
        for indices in instance_list:
            year_means.append(collapse_time_weighted(data, indices, day_counts))

        n_years = len(year_means)
        clim = [[0.0] * nlon for _ in range(nlat)]
        for ym in year_means:
            for i in range(nlat):
                for j in range(nlon):
                    clim[i][j] += ym[i][j] / n_years
        result[sn] = clim

    return result


def area_weighted_mean(field_2d, weights):
    """Compute area-weighted mean of a 2D field."""
    nlat = len(field_2d)
    nlon = len(field_2d[0])
    total_weight = 0.0
    weighted_sum = 0.0
    for i in range(nlat):
        for j in range(nlon):
            weighted_sum += weights[i][j] * field_2d[i][j]
            total_weight += weights[i][j]
    return weighted_sum / total_weight


def format_cell_methods(operations):
    """Format CF cell_methods string with qualifier support.

    Supports optional qualifiers (within, over, etc.) per CF conventions.
    """
    parts = []
    for op in operations:
        s = f"{op['axes']}: {op['method']}"
        if 'qualifiers' in op:
            for k, v in op['qualifiers'].items():
                s += f" ({k}: {v})"
        parts.append(s)
    return ' '.join(parts)


def process_field(filepath):
    """Process a field file to produce seasonal climatological statistics."""
    with open(filepath) as f:
        field = json.load(f)

    data = field['data']
    coords = field['coordinates']
    lat_bounds = coords['latitude']['bounds']
    lon_bounds = coords['longitude']['bounds']
    time_bounds = coords['time']['bounds']
    calendar = coords['time'].get('calendar', 'standard')
    reference_year = field['reference_year']
    n_months = field['n_months']

    weights = compute_area_weights(lat_bounds, lon_bounds)
    day_counts = get_day_counts(time_bounds, calendar, reference_year, n_months)
    seasons = assign_seasons(n_months, reference_year)
    clim = climatological_mean(data, seasons, day_counts)

    global_means = {}
    for sn, field_2d in clim.items():
        global_means[sn] = area_weighted_mean(field_2d, weights)

    cell_methods = {}
    for sn in clim:
        ops = [
            {'axes': 'time', 'method': 'mean', 'qualifiers': {'within': 'years'}},
            {'axes': 'time', 'method': 'mean', 'qualifiers': {'over': 'years'}},
            {'axes': 'area', 'method': 'mean'},
        ]
        cell_methods[sn] = format_cell_methods(ops)

    seasons_used = {}
    for (yr, sn) in seasons:
        if sn not in seasons_used:
            seasons_used[sn] = []
        seasons_used[sn].append(yr)
    for sn in seasons_used:
        seasons_used[sn] = sorted(set(seasons_used[sn]))

    return {
        'seasonal_climatologies': clim,
        'global_means': global_means,
        'cell_methods': cell_methods,
        'seasons_used': seasons_used,
        'area_weights': weights,
    }
