
"""Verification tests for the netCDF climatology pipeline task."""

import os
import pytest
import numpy as np
from netCDF4 import Dataset

# ---------- Reference grid and formulas ----------

LATS = np.array([-67.5, -22.5, 22.5, 67.5])
LONS = np.array([30.0, 90.0, 150.0, 210.0, 270.0, 330.0])
NLAT, NLON = 4, 6
PI = np.pi

# Land mask (True = missing)
LAND = np.zeros((NLAT, NLON), dtype=bool)
LAND[0, 2] = True   # lat=-67.5, lon=150
LAND[2, 4] = True   # lat=22.5,  lon=270
LAND[3, 0] = True   # lat=67.5,  lon=30

# Number of valid cells per latitude row
N_VALID = np.array([NLON - int(LAND[j, :].sum()) for j in range(NLAT)])


def expected_tas_clim(month, lat):
    """Expected climatological temperature (average of 2 years)."""
    # Year-1 month m: 280 + 10*sin(2π(m+0.5)/12) + 5*(lat/90) + m*0.1
    # Year-2 month m+12: same but trend term = (m+12)*0.1
    # Average = 280 + 10*sin(...) + 5*(lat/90) + (m + m+12)*0.1/2
    #         = 280.6 + 10*sin(2π(m+0.5)/12) + 5*(lat/90) + m*0.1
    return (280.6
            + 10.0 * np.sin(2 * PI * (month + 0.5) / 12.0)
            + 5.0 * (lat / 90.0)
            + month * 0.1)


def expected_uas_clim(month, lat):
    """Expected climatological eastward wind (identical both years)."""
    return 5.0 * np.cos(lat * PI / 180.0) + 0.5 * np.sin(2 * PI * month / 12.0)


def expected_vas_clim(month, lat):
    """Expected climatological northward wind (identical both years)."""
    return 2.0 * np.sin(2 * PI * (month + 0.5) / 12.0) * np.cos(lat * PI / 180.0)


def _is_missing(val, var_obj=None):
    """Check whether a value is missing (NaN or masked)."""
    if isinstance(val, np.ma.core.MaskedConstant):
        return True
    try:
        return np.isnan(float(val))
    except (TypeError, ValueError):
        return False


# ---------- Fixtures ----------

CLIM_PATH = '/app/output/climatology.nc'
GMEAN_PATH = '/app/output/global_mean_tas.nc'


# ---------- Climatology file tests ----------

class TestClimatologyFileStructure:
    def test_file_exists(self):
        assert os.path.isfile(CLIM_PATH), f"{CLIM_PATH} not found"

    def test_has_12_time_records(self):
        with Dataset(CLIM_PATH) as ds:
            assert 'time' in ds.dimensions, "No 'time' dimension"
            assert len(ds.dimensions['time']) == 12, \
                f"Expected 12 time records, got {len(ds.dimensions['time'])}"

    def test_has_lat_lon_dims(self):
        with Dataset(CLIM_PATH) as ds:
            dim_sizes = {d: len(ds.dimensions[d]) for d in ds.dimensions}
            has_4 = any(v == NLAT for d, v in dim_sizes.items() if d != 'time')
            has_6 = any(v == NLON for d, v in dim_sizes.items() if d != 'time')
            assert has_4, f"No spatial dimension of size {NLAT} (latitude)"
            assert has_6, f"No spatial dimension of size {NLON} (longitude)"

    def test_required_variables(self):
        with Dataset(CLIM_PATH) as ds:
            for vname in ('tas', 'uas', 'vas', 'wind_speed'):
                assert vname in ds.variables, f"Variable '{vname}' not found"

    def test_wind_speed_has_metadata(self):
        with Dataset(CLIM_PATH) as ds:
            ws = ds.variables['wind_speed']
            assert hasattr(ws, 'units'), "wind_speed missing 'units' attribute"
            assert hasattr(ws, 'long_name'), "wind_speed missing 'long_name' attribute"


class TestClimatologyValues:
    """Verify that climatological data values match the analytical expectation."""

    @staticmethod
    def _read_3d(path, varname):
        """Read a 3-D variable and return as a filled numpy array (NaN for missing)."""
        with Dataset(path) as ds:
            v = ds.variables[varname][:]
            if hasattr(v, 'filled'):
                return v.filled(np.nan)
            return np.asarray(v, dtype=np.float64)

    def test_tas_values(self):
        tas = self._read_3d(CLIM_PATH, 'tas')
        assert tas.shape == (12, NLAT, NLON), f"Unexpected shape {tas.shape}"
        for i in range(12):
            for j in range(NLAT):
                for k in range(NLON):
                    if LAND[j, k]:
                        assert _is_missing(tas[i, j, k]), \
                            f"tas({i},{j},{k}) should be missing but is {tas[i,j,k]}"
                    else:
                        exp = expected_tas_clim(i, LATS[j])
                        assert abs(tas[i, j, k] - exp) < 0.05, \
                            f"tas({i},{j},{k}): got {tas[i,j,k]:.6f}, expected {exp:.6f}"

    def test_uas_values(self):
        uas = self._read_3d(CLIM_PATH, 'uas')
        assert uas.shape == (12, NLAT, NLON), f"Unexpected shape {uas.shape}"
        for i in range(12):
            for j in range(NLAT):
                for k in range(NLON):
                    if LAND[j, k]:
                        assert _is_missing(uas[i, j, k]), \
                            f"uas({i},{j},{k}) should be missing"
                    else:
                        exp = expected_uas_clim(i, LATS[j])
                        assert abs(uas[i, j, k] - exp) < 0.05, \
                            f"uas({i},{j},{k}): got {uas[i,j,k]:.6f}, expected {exp:.6f}"

    def test_vas_values(self):
        vas = self._read_3d(CLIM_PATH, 'vas')
        assert vas.shape == (12, NLAT, NLON), f"Unexpected shape {vas.shape}"
        for i in range(12):
            for j in range(NLAT):
                for k in range(NLON):
                    if LAND[j, k]:
                        assert _is_missing(vas[i, j, k]), \
                            f"vas({i},{j},{k}) should be missing"
                    else:
                        exp = expected_vas_clim(i, LATS[j])
                        assert abs(vas[i, j, k] - exp) < 0.05, \
                            f"vas({i},{j},{k}): got {vas[i,j,k]:.6f}, expected {exp:.6f}"

    def test_wind_speed_is_correct(self):
        """wind_speed must equal sqrt(uas² + vas²) at every non-missing cell."""
        ws = self._read_3d(CLIM_PATH, 'wind_speed')
        uas = self._read_3d(CLIM_PATH, 'uas')
        vas = self._read_3d(CLIM_PATH, 'vas')
        assert ws.shape == (12, NLAT, NLON)
        for i in range(12):
            for j in range(NLAT):
                for k in range(NLON):
                    if LAND[j, k]:
                        assert _is_missing(ws[i, j, k]), \
                            f"wind_speed({i},{j},{k}) should be missing"
                    else:
                        exp = np.sqrt(uas[i, j, k] ** 2 + vas[i, j, k] ** 2)
                        assert abs(ws[i, j, k] - exp) < 0.01, \
                            f"wind_speed({i},{j},{k}): got {ws[i,j,k]:.6f}, expected {exp:.6f}"


class TestGlobalMean:
    """Verify the area-weighted global mean of the tas climatology."""

    def test_file_exists(self):
        assert os.path.isfile(GMEAN_PATH), f"{GMEAN_PATH} not found"

    def test_dimensions(self):
        with Dataset(GMEAN_PATH) as ds:
            assert 'time' in ds.dimensions
            assert len(ds.dimensions['time']) == 12
            assert 'tas' in ds.variables
            tas = ds.variables['tas']
            # tas should have only 1 dimension (time), lat/lon collapsed
            assert len(tas.dimensions) == 1, \
                f"tas should have 1 dim (time), got {len(tas.dimensions)}: {tas.dimensions}"

    def test_values(self):
        with Dataset(GMEAN_PATH) as ds:
            gmean = ds.variables['tas'][:]
            if hasattr(gmean, 'filled'):
                gmean = gmean.filled(np.nan)
            else:
                gmean = np.asarray(gmean, dtype=np.float64)

        cos_lat = np.cos(LATS * PI / 180.0)

        for i in range(12):
            numerator = 0.0
            denominator = 0.0
            for j in range(NLAT):
                for k in range(NLON):
                    if not LAND[j, k]:
                        val = expected_tas_clim(i, LATS[j])
                        numerator += val * cos_lat[j]
                        denominator += cos_lat[j]
            expected_mean = numerator / denominator

            assert abs(gmean[i] - expected_mean) < 0.05, \
                f"Global mean month {i}: got {gmean[i]:.6f}, expected {expected_mean:.6f}"
