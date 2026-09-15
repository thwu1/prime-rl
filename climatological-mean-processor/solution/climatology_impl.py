"""
CF-compliant climatological mean processor — reference implementation.

"""
import math
import json
from collections import defaultdict
from typing import Dict, List, Tuple, Optional


def compute_area_weights(lat_bounds: List[List[float]],
                         lon_bounds: List[List[float]]) -> List[List[float]]:
    """Compute solid angle area weights on a unit sphere from lat/lon bounds."""
    nlat = len(lat_bounds)
    nlon = len(lon_bounds)
    weights = []
    for i in range(nlat):
        row = []
        lat_s_rad = math.radians(lat_bounds[i][0])
        lat_n_rad = math.radians(lat_bounds[i][1])
        delta_sin_lat = abs(math.sin(lat_n_rad) - math.sin(lat_s_rad))
        for j in range(nlon):
            lon_w_rad = math.radians(lon_bounds[j][0])
            lon_e_rad = math.radians(lon_bounds[j][1])
            delta_lon = abs(lon_e_rad - lon_w_rad)
            row.append(delta_sin_lat * delta_lon)
        weights.append(row)
    return weights


def get_month_info(time_index: int, reference_year: int = 2000) -> Tuple[int, int]:
    """Convert a 0-based monthly time index to (year, month)."""
    year = reference_year + time_index // 12
    month = (time_index % 12) + 1
    return (year, month)


def get_day_counts(time_bounds: List[List[float]]) -> List[float]:
    """Extract cell sizes (day counts) from time coordinate bounds."""
    return [b[1] - b[0] for b in time_bounds]


def assign_seasons(n_times: int, reference_year: int = 2000) -> Dict[Tuple[int, str], List[int]]:
    """Assign monthly time indices to standard meteorological seasons.

    December of year Y belongs to DJF of year Y+1.
    Only complete seasons (3 months) are included.
    """
    SEASON_MAP = {
        12: 'DJF', 1: 'DJF', 2: 'DJF',
        3: 'MAM', 4: 'MAM', 5: 'MAM',
        6: 'JJA', 7: 'JJA', 8: 'JJA',
        9: 'SON', 10: 'SON', 11: 'SON',
    }

    season_groups = {}
    for t in range(n_times):
        year, month = get_month_info(t, reference_year)
        season_name = SEASON_MAP[month]
        # For DJF: December belongs to the NEXT year's DJF
        if month == 12:
            season_year = year + 1
        else:
            season_year = year
        key = (season_year, season_name)
        if key not in season_groups:
            season_groups[key] = []
        season_groups[key].append(t)

    # Keep only complete seasons (exactly 3 months)
    return {k: v for k, v in season_groups.items() if len(v) == 3}


def collapse_time_weighted(data: List[List[List[float]]],
                           indices: List[int],
                           day_counts: List[float]) -> List[List[float]]:
    """Compute day-count-weighted mean over selected time steps."""
    nlat = len(data[0])
    nlon = len(data[0][0])
    total_days = sum(day_counts[t] for t in indices)

    result = [[0.0] * nlon for _ in range(nlat)]
    for t in indices:
        w = day_counts[t] / total_days
        for i in range(nlat):
            for j in range(nlon):
                result[i][j] += w * data[t][i][j]
    return result


def climatological_mean(data: List[List[List[float]]],
                        seasons: Dict[Tuple[int, str], List[int]],
                        day_counts: List[float]) -> Dict[str, List[List[float]]]:
    """Compute two-stage climatological mean.

    Stage 1: within-year day-weighted seasonal means
    Stage 2: over-years unweighted average of the seasonal means
    """
    # Stage 1: compute within-year seasonal means
    by_season = defaultdict(list)
    for (year, season_name), indices in seasons.items():
        seasonal_mean = collapse_time_weighted(data, indices, day_counts)
        by_season[season_name].append(seasonal_mean)

    # Stage 2: average over years (equal weight per year)
    clim = {}
    for season_name, year_means in by_season.items():
        n_years = len(year_means)
        nlat = len(year_means[0])
        nlon = len(year_means[0][0])
        avg = [[0.0] * nlon for _ in range(nlat)]
        for ym in year_means:
            for i in range(nlat):
                for j in range(nlon):
                    avg[i][j] += ym[i][j] / n_years
        clim[season_name] = avg

    return clim


def area_weighted_mean(data_2d: List[List[float]],
                       weights: List[List[float]]) -> float:
    """Compute area-weighted mean over latitude and longitude."""
    total_w = 0.0
    total_wv = 0.0
    for i in range(len(data_2d)):
        for j in range(len(data_2d[0])):
            w = weights[i][j]
            total_w += w
            total_wv += w * data_2d[i][j]
    return total_wv / total_w


def format_cell_methods(operations: List[Dict]) -> str:
    """Format a sequence of collapse operations as a CF cell_methods string."""
    parts = []
    for op in operations:
        s = f"{op['axes']}: {op['method']}"
        if op.get('qualifiers'):
            quals = " ".join(f"{k}: {v}" for k, v in op['qualifiers'].items())
            s += f" ({quals})"
        parts.append(s)
    return " ".join(parts)


def process_field(filepath: str) -> Dict:
    """Full processing pipeline for a JSON-encoded CF field."""
    with open(filepath) as f:
        field_data = json.load(f)

    data = field_data['data']
    lat_bounds = field_data['coordinates']['latitude']['bounds']
    lon_bounds = field_data['coordinates']['longitude']['bounds']
    time_bounds = field_data['coordinates']['time']['bounds']
    ref_year = field_data.get('reference_year', 2000)
    n_times = field_data['dimensions']['time']

    # Compute components
    area_weights = compute_area_weights(lat_bounds, lon_bounds)
    day_counts = get_day_counts(time_bounds)
    seasons = assign_seasons(n_times, ref_year)
    clim = climatological_mean(data, seasons, day_counts)

    # Build results
    global_means = {}
    cell_methods = {}
    seasons_used = {}

    # Collect which years contribute to each season
    season_years = defaultdict(list)
    for (year, sname) in seasons:
        season_years[sname].append(year)

    for sname, clim_data in clim.items():
        global_means[sname] = area_weighted_mean(clim_data, area_weights)
        cell_methods[sname] = format_cell_methods([
            {'axes': 'time', 'method': 'mean', 'qualifiers': {'within': 'years'}},
            {'axes': 'time', 'method': 'mean', 'qualifiers': {'over': 'years'}},
            {'axes': 'area', 'method': 'mean'},
        ])
        seasons_used[sname] = sorted(season_years[sname])

    return {
        'seasonal_climatologies': clim,
        'global_means': global_means,
        'cell_methods': cell_methods,
        'seasons_used': seasons_used,
        'area_weights': area_weights,
    }
