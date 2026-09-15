"""CF-compliant seasonal climatological mean pipeline.

Processes monthly gridded climate data following CF conventions to compute
area-weighted seasonal climatological means.
"""

import json
import math


# Standard calendar month lengths
STANDARD_MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def compute_area_weights(lat_bounds, lon_bounds):
    """Compute area weights for a latitude-longitude grid.

    Args:
        lat_bounds: list of [south, north] pairs in degrees
        lon_bounds: list of [west, east] pairs in degrees

    Returns:
        2D list of weights, shape [nlat][nlon]
    """
    weights = []
    for lb in lat_bounds:
        row = []
        lat_center = math.radians((lb[0] + lb[1]) / 2.0)
        dlat = math.radians(abs(lb[1] - lb[0]))
        for lonb in lon_bounds:
            dlon = math.radians(abs(lonb[1] - lonb[0]))
            w = math.cos(lat_center) * dlat * dlon
            row.append(w)
        weights.append(row)
    return weights


def get_month_info(time_index, reference_year):
    """Convert a time index to (year, month) tuple.

    Args:
        time_index: 0-based month index from start of data
        reference_year: year corresponding to time_index=0

    Returns:
        (year, month) where month is 1-12
    """
    year = reference_year + time_index // 12
    month = (time_index % 12) + 1
    return (year, month)


def is_leap_year(year):
    """Check if a year is a leap year in the standard calendar."""
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def get_day_counts(time_bounds, calendar, reference_year, n_months):
    """Get the number of days in each month.

    Args:
        time_bounds: list of [start, end] day pairs from coordinate bounds
        calendar: CF calendar type string
        reference_year: starting year
        n_months: number of months

    Returns:
        list of day counts per month
    """
    result = []
    for t in range(n_months):
        year, month = get_month_info(t, reference_year)
        days = STANDARD_MONTH_DAYS[month - 1]
        if month == 2 and is_leap_year(year):
            days = 29
        result.append(float(days))
    return result


def assign_seasons(n_months, reference_year):
    """Assign time indices to meteorological seasons.

    Seasons: DJF (Dec-Jan-Feb), MAM (Mar-Apr-May),
             JJA (Jun-Jul-Aug), SON (Sep-Oct-Nov)

    Args:
        n_months: total number of months in the data
        reference_year: starting year

    Returns:
        dict mapping (year, season_name) to list of time indices
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
        season_year = year
        key = (season_year, season_name)
        if key not in seasons:
            seasons[key] = []
        seasons[key].append(t)
    return seasons


def collapse_time_weighted(data, indices, day_counts):
    """Compute day-weighted mean over specified time indices.

    Args:
        data: 3D list [time][lat][lon]
        indices: list of time indices to average
        day_counts: list of days per month for all time steps

    Returns:
        2D list [lat][lon] of weighted means
    """
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
    """Compute climatological mean for each season.

    Args:
        data: 3D list [time][lat][lon]
        seasons: dict mapping (year, season_name) to time indices
        day_counts: list of days per month

    Returns:
        dict mapping season_name to 2D climatological field
    """
    season_groups = {}
    for (yr, sn), indices in seasons.items():
        if sn not in season_groups:
            season_groups[sn] = []
        season_groups[sn].extend(indices)

    result = {}
    for sn, all_indices in season_groups.items():
        result[sn] = collapse_time_weighted(data, all_indices, day_counts)
    return result


def area_weighted_mean(field_2d, weights):
    """Compute area-weighted mean of a 2D field.

    Args:
        field_2d: 2D list [lat][lon]
        weights: 2D list [lat][lon] of area weights

    Returns:
        scalar weighted mean
    """
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
    """Format CF cell_methods string from a list of operations.

    Args:
        operations: list of dicts with 'axes' and 'method' keys

    Returns:
        formatted cell_methods string
    """
    parts = []
    for op in operations:
        parts.append(f"{op['axes']}: {op['method']}")
    return ' '.join(parts)


def process_field(filepath):
    """Process a field file to produce seasonal climatological statistics.

    Reads a JSON field file, computes seasonal climatological means using
    day-weighted temporal averaging and area-weighted spatial averaging,
    and returns structured results with CF metadata.

    Args:
        filepath: path to input JSON field file

    Returns:
        dict with keys: seasonal_climatologies, global_means, cell_methods,
        seasons_used, area_weights
    """
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
            {'axes': 'time', 'method': 'mean'},
            {'axes': 'time', 'method': 'mean'},
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
