"""
CF-compliant climatological mean processor.

Implements weighted temporal and spatial collapse operations following
CF (Climate and Forecast) conventions for monthly climate data.

Functions to implement:
- compute_area_weights: Spherical area weights from coordinate bounds
- get_month_info: Time index to calendar (year, month)
- get_day_counts: Cell sizes from time bounds
- assign_seasons: Monthly time steps to meteorological seasons
- collapse_time_weighted: Day-weighted temporal averaging
- climatological_mean: Two-stage climatological collapse
- area_weighted_mean: Spatially-weighted mean
- format_cell_methods: CF cell method string generation
- process_field: Full pipeline orchestration
"""
import math
import json
from typing import Dict, List, Tuple, Optional


def compute_area_weights(lat_bounds: List[List[float]],
                         lon_bounds: List[List[float]]) -> List[List[float]]:
    """Compute solid angle area weights on a unit sphere from lat/lon bounds.

    Each grid cell's weight equals its solid angle (area on a unit sphere).
    For a cell bounded by latitudes [phi_1, phi_2] and longitudes [lam_1, lam_2]
    (both in degrees), the solid angle is |sin(phi_2) - sin(phi_1)| * |lam_2 - lam_1|,
    where the angles are converted to radians.

    The sum of all weights for a complete sphere equals 4*pi.

    Args:
        lat_bounds: shape (nlat, 2), each [south_deg, north_deg]
        lon_bounds: shape (nlon, 2), each [west_deg, east_deg]

    Returns:
        shape (nlat, nlon) nested list of area weights
    """
    raise NotImplementedError


def get_month_info(time_index: int, reference_year: int = 2000) -> Tuple[int, int]:
    """Convert a 0-based monthly time index to (year, month).

    Assumes consecutive months starting from January of reference_year.

    Args:
        time_index: 0-based index (0 = Jan of reference_year)
        reference_year: calendar year of the first time step

    Returns:
        (year, month) where month is 1-12
    """
    raise NotImplementedError


def get_day_counts(time_bounds: List[List[float]]) -> List[float]:
    """Extract cell sizes (day counts) from time coordinate bounds.

    Each time step's day count equals its upper bound minus its lower bound.

    Args:
        time_bounds: list of [lower, upper] for each time step

    Returns:
        list of day counts
    """
    raise NotImplementedError


def assign_seasons(n_times: int, reference_year: int = 2000) -> Dict[Tuple[int, str], List[int]]:
    """Assign monthly time indices to standard meteorological seasons.

    Season definitions:
        DJF: December, January, February
        MAM: March, April, May
        JJA: June, July, August
        SON: September, October, November

    Critical convention: December of year Y belongs to the DJF season
    of year Y+1 (i.e., the DJF season is labeled by the year of its
    January/February).

    Only complete seasons (exactly 3 contributing months) are included.
    Incomplete seasons at the start/end of the time series are excluded.

    Args:
        n_times: number of monthly time steps
        reference_year: year of the first time step (January)

    Returns:
        dict mapping (year, season_name) to list of time indices
    """
    raise NotImplementedError


def collapse_time_weighted(data: List[List[List[float]]],
                           indices: List[int],
                           day_counts: List[float]) -> List[List[float]]:
    """Compute day-count-weighted mean over selected time steps.

    At each spatial point (i, j):
        result[i][j] = sum_t (days[t] * data[t][i][j]) / sum_t days[t]
    where t iterates over the given indices.

    Args:
        data: shape (ntime, nlat, nlon) nested list of values
        indices: time indices to include in the average
        day_counts: day count for ALL time steps (not just selected)

    Returns:
        shape (nlat, nlon) nested list of weighted means
    """
    raise NotImplementedError


def climatological_mean(data: List[List[List[float]]],
                        seasons: Dict[Tuple[int, str], List[int]],
                        day_counts: List[float]) -> Dict[str, List[List[float]]]:
    """Compute two-stage climatological mean.

    Stage 1 ("within years"): For each (year, season) pair, compute the
    day-weighted mean over the 3 months in that season instance.

    Stage 2 ("over years"): For each season name, compute the unweighted
    arithmetic mean of the per-year seasonal means from Stage 1.

    This two-stage approach is NOT equivalent to pooling all months of
    a given season across years into a single weighted average, because
    different year-instances of a season may have different total day
    counts (e.g., leap years affect February's weight in DJF).

    Args:
        data: shape (ntime, nlat, nlon) nested list
        seasons: output of assign_seasons()
        day_counts: day count for each time step

    Returns:
        dict mapping season name ('DJF', 'MAM', 'JJA', 'SON') to
        (nlat, nlon) climatological mean array
    """
    raise NotImplementedError


def area_weighted_mean(data_2d: List[List[float]],
                       weights: List[List[float]]) -> float:
    """Compute area-weighted mean over latitude and longitude.

    result = sum_ij (w[i][j] * data[i][j]) / sum_ij w[i][j]

    Args:
        data_2d: shape (nlat, nlon) nested list of values
        weights: shape (nlat, nlon) nested list of area weights

    Returns:
        scalar area-weighted mean
    """
    raise NotImplementedError


def format_cell_methods(operations: List[Dict]) -> str:
    """Format a sequence of collapse operations as a CF cell_methods string.

    Each operation has:
        'axes': dimension name (e.g., 'time', 'area')
        'method': statistic (e.g., 'mean')
        'qualifiers': optional dict of qualifier key-value pairs

    Output format:
        "axes1: method1 (key1: val1) axes2: method2"

    Multiple operations are space-separated.

    Args:
        operations: ordered list of operation dicts

    Returns:
        CF-compliant cell_methods string
    """
    raise NotImplementedError


def process_field(filepath: str) -> Dict:
    """Full processing pipeline for a JSON-encoded CF field.

    Steps:
        1. Load field data from JSON file
        2. Compute area weights from latitude/longitude bounds
        3. Extract day counts from time bounds
        4. Assign time steps to meteorological seasons
        5. Compute two-stage climatological means for each season
        6. Compute area-weighted global mean for each season's climatology
        7. Generate CF cell_methods strings for the full operation chain:
           time: mean (within: years) time: mean (over: years) area: mean

    The JSON file contains:
        - 'data': 3D array [time, lat, lon]
        - 'coordinates': dict with 'time', 'latitude', 'longitude' sub-dicts
        - 'dimensions': dict with dimension sizes
        - 'reference_year': year of first time step

    Args:
        filepath: path to JSON field file

    Returns:
        dict with keys:
            'seasonal_climatologies': {season: (nlat, nlon) mean}
            'global_means': {season: scalar}
            'cell_methods': {season: cell_methods string}
            'seasons_used': {season: sorted list of years}
            'area_weights': (nlat, nlon) weights
    """
    raise NotImplementedError
