"""Utility functions for CMORization pipeline."""
import numpy as np
import netCDF4 as nc
import cftime
from datetime import datetime


def shift_longitude(lon_values, data, lon_axis):
    """Shift longitude from [-180, 180] to [0, 360] range.

    Transforms negative longitudes to positive and sorts the result.
    """
    new_lon = np.where(lon_values < 0, lon_values + 360, lon_values)
    sort_idx = np.argsort(new_lon)
    new_lon = new_lon[sort_idx]
    # Note: data array must be reordered to match the new longitude order
    return new_lon, data


def flip_latitudes(lat_values, data, lat_axis):
    """Ensure latitudes are in ascending order."""
    if lat_values[0] > lat_values[-1]:
        lat_values = lat_values[::-1]
        data = np.flip(data, axis=lat_axis)
    return lat_values, data


def compute_bounds(coord_values):
    """Compute bounds for a coordinate array.

    For N coordinate values, produces an (N, 2) bounds array where each
    row gives [lower_bound, upper_bound]. Interior bounds are midpoints
    between adjacent coordinate values. Edge bounds are extrapolated using
    the spacing of the nearest interior midpoint.
    """
    n = len(coord_values)
    bounds = np.zeros((n, 2))

    midpoints = (coord_values[:-1] + coord_values[1:]) / 2.0

    first_spacing = midpoints[0] - coord_values[0]
    last_spacing = coord_values[-1] - midpoints[-1]

    bounds[0, 0] = coord_values[0] - first_spacing
    bounds[0, 1] = midpoints[0]
    bounds[-1, 0] = midpoints[-1]
    bounds[-1, 1] = coord_values[-1] + last_spacing

    for i in range(1, n - 1):
        bounds[i, 0] = midpoints[i - 1]
        bounds[i, 1] = midpoints[i]

    return bounds


def standardize_time(time_values, time_units, calendar,
                     target_units, target_calendar):
    """Convert time values to target units and calendar.

    Handles calendar conversion from 360-day to standard gregorian.
    Returns (time_values, time_bounds) in target encoding.
    """
    source_dates = cftime.num2date(time_values, time_units, calendar)

    if calendar == '360_day' and target_calendar in ('standard', 'gregorian'):
        converted_dates = []
        for d in source_dates:
            try:
                new_date = datetime(d.year, d.month, min(d.day, 28))
            except ValueError:
                new_date = datetime(d.year, d.month, 28)
            converted_dates.append(new_date)
    else:
        converted_dates = []
        for d in source_dates:
            converted_dates.append(
                datetime(d.year, d.month, d.day,
                         d.hour, d.minute, d.second)
            )

    target_values = cftime.date2num(converted_dates, target_units,
                                     target_calendar)

    return target_values, None


def convert_units(data, source_units, target_units):
    """Convert data between unit systems."""
    if source_units == 'degC' and target_units == 'K':
        return data + 273.15
    elif source_units == 'mm/day' and target_units == 'kg m-2 s-1':
        # mm/day = kg m-2 day-1; convert to per-second
        return data * 86400.0
    elif source_units == target_units:
        return data
    elif source_units == 'W/m2' and target_units == 'W m-2':
        return data
    else:
        raise ValueError(
            f"Unknown unit conversion: {source_units} -> {target_units}"
        )


def handle_missing_values(data, fill_value, target_fill=1.0e20):
    """Replace missing/fill values with the target fill value.

    Identifies cells matching fill_value and replaces them.
    """
    mask = (data == fill_value)
    data[mask] = target_fill
    return data, mask
