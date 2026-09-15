"""Tests for CMOR-compliant output files."""

import pytest
import numpy as np
import netCDF4 as nc
import os
from datetime import datetime


OUTPUT_DIR = '/app/output'
RAW_FILE = '/data/raw_data/synthetic_era5_monthly_2000_2002.nc'
ANCILLARY_OROG = '/data/ancillary/orog_diff.nc'

ALL_VARS = ['tas', 'huss', 'pr', 'rsds']

EXPECTED_FILES = {
    'tas': 'OBS_ERA5syn_reanaly_v1_Amon_tas_200001-200212.nc',
    'huss': 'OBS_ERA5syn_reanaly_v1_Amon_huss_200001-200212.nc',
    'pr': 'OBS_ERA5syn_reanaly_v1_Amon_pr_200001-200212.nc',
    'rsds': 'OBS_ERA5syn_reanaly_v1_Amon_rsds_200001-200212.nc',
}


def _open_output(var_name):
    return nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name]), 'r')


def _open_raw():
    return nc.Dataset(RAW_FILE, 'r')


def _open_orog():
    return nc.Dataset(ANCILLARY_OROG, 'r')


def _find_idx(coord_vals, target):
    return int(np.argmin(np.abs(np.asarray(coord_vals) - target)))


# ============================================================
# File existence
# ============================================================

class TestFileExistence:
    def test_output_dir_exists(self):
        assert os.path.isdir(OUTPUT_DIR), f"{OUTPUT_DIR} does not exist"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_output_file_exists(self, var_name):
        fpath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        assert os.path.isfile(fpath), f"Missing: {EXPECTED_FILES[var_name]}"


# ============================================================
# Coordinate compliance
# ============================================================

class TestCoordinates:
    @pytest.fixture(params=ALL_VARS)
    def ds(self, request):
        d = _open_output(request.param)
        yield d
        d.close()

    def test_has_lat_lon_time(self, ds):
        for c in ['lat', 'lon', 'time']:
            assert c in ds.variables, f"Missing coordinate: {c}"

    def test_latitude_ascending(self, ds):
        lat = ds.variables['lat'][:]
        assert np.all(np.diff(lat) > 0), "Latitude must be ascending"

    def test_latitude_range(self, ds):
        lat = ds.variables['lat'][:]
        assert lat[0] >= -90.0 and lat[-1] <= 90.0

    def test_latitude_count(self, ds):
        assert len(ds.variables['lat'][:]) == 73

    def test_longitude_range(self, ds):
        lon = ds.variables['lon'][:]
        assert lon[0] >= 0.0, f"lon starts at {lon[0]}, expected >= 0"
        assert lon[-1] < 360.0, f"lon ends at {lon[-1]}, expected < 360"

    def test_longitude_ascending(self, ds):
        lon = ds.variables['lon'][:]
        assert np.all(np.diff(lon) > 0), "Longitude must be ascending"

    def test_longitude_count(self, ds):
        assert len(ds.variables['lon'][:]) == 144

    def test_time_units(self, ds):
        assert 'days since 1850-01-01' in ds.variables['time'].units

    def test_time_calendar(self, ds):
        cal = ds.variables['time'].calendar.lower()
        assert cal in ('gregorian', 'standard', 'proleptic_gregorian')

    def test_time_length(self, ds):
        assert len(ds.variables['time'][:]) == 36

    def test_lat_bounds_exist(self, ds):
        lv = ds.variables['lat']
        assert hasattr(lv, 'bounds'), "lat needs bounds attribute"
        assert lv.bounds in ds.variables

    def test_lon_bounds_exist(self, ds):
        lv = ds.variables['lon']
        assert hasattr(lv, 'bounds'), "lon needs bounds attribute"
        assert lv.bounds in ds.variables

    def test_time_bounds_exist(self, ds):
        tv = ds.variables['time']
        assert hasattr(tv, 'bounds'), "time needs bounds attribute"
        assert tv.bounds in ds.variables

    def test_lat_bounds_shape(self, ds):
        lat = ds.variables['lat'][:]
        b = ds.variables[ds.variables['lat'].bounds][:]
        assert b.shape == (len(lat), 2)

    def test_lon_bounds_shape(self, ds):
        lon = ds.variables['lon'][:]
        b = ds.variables[ds.variables['lon'].bounds][:]
        assert b.shape == (len(lon), 2)

    def test_time_bounds_first_month(self, ds):
        """First time bounds should span Jan 2000."""
        bname = ds.variables['time'].bounds
        tb = ds.variables[bname][:]
        base = datetime(1850, 1, 1)
        jan1 = (datetime(2000, 1, 1) - base).days
        feb1 = (datetime(2000, 2, 1) - base).days
        assert abs(tb[0, 0] - jan1) < 0.01, \
            f"Jan start bound: expected {jan1}, got {tb[0, 0]}"
        assert abs(tb[0, 1] - feb1) < 0.01, \
            f"Jan end bound: expected {feb1}, got {tb[0, 1]}"

    def test_time_bounds_last_month(self, ds):
        """Last time bounds should span Dec 2002."""
        bname = ds.variables['time'].bounds
        tb = ds.variables[bname][:]
        base = datetime(1850, 1, 1)
        dec1 = (datetime(2002, 12, 1) - base).days
        jan1_next = (datetime(2003, 1, 1) - base).days
        assert abs(tb[-1, 0] - dec1) < 0.01
        assert abs(tb[-1, 1] - jan1_next) < 0.01

    def test_time_values_mid_month(self, ds):
        """Time values should be at midpoint of bounds."""
        time = ds.variables['time'][:]
        bname = ds.variables['time'].bounds
        tb = ds.variables[bname][:]
        midpoints = (tb[:, 0] + tb[:, 1]) / 2.0
        np.testing.assert_allclose(time, midpoints, atol=0.5,
            err_msg="Time values should be at mid-month")

    def test_coordinate_dtypes(self, ds):
        for c in ['lat', 'lon', 'time']:
            assert ds.variables[c].dtype == np.float64, \
                f"{c} should be float64, got {ds.variables[c].dtype}"

    def test_lat_standard_name(self, ds):
        assert ds.variables['lat'].standard_name == 'latitude'

    def test_lon_standard_name(self, ds):
        assert ds.variables['lon'].standard_name == 'longitude'


# ============================================================
# Variable metadata
# ============================================================

class TestVariableMetadata:
    META = {
        'tas': {
            'standard_name': 'air_temperature',
            'units': 'K',
            'long_name': 'Near-Surface Air Temperature',
        },
        'huss': {
            'standard_name': 'specific_humidity',
            'units': '1',
            'long_name': 'Near-Surface Specific Humidity',
        },
        'pr': {
            'standard_name': 'precipitation_flux',
            'units': 'kg m-2 s-1',
            'long_name': 'Precipitation',
        },
        'rsds': {
            'standard_name': 'surface_downwelling_shortwave_flux_in_air',
            'units': 'W m-2',
            'long_name': 'Surface Downwelling Shortwave Radiation',
        },
    }

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_variable_exists(self, var_name):
        with _open_output(var_name) as ds:
            assert var_name in ds.variables

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_standard_name(self, var_name):
        with _open_output(var_name) as ds:
            actual = ds.variables[var_name].standard_name
            assert actual == self.META[var_name]['standard_name']

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_units(self, var_name):
        with _open_output(var_name) as ds:
            assert ds.variables[var_name].units == self.META[var_name]['units']

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_long_name(self, var_name):
        with _open_output(var_name) as ds:
            assert ds.variables[var_name].long_name == self.META[var_name]['long_name']

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_data_dtype(self, var_name):
        with _open_output(var_name) as ds:
            assert ds.variables[var_name].dtype == np.float32, \
                f"Data should be float32, got {ds.variables[var_name].dtype}"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_cell_methods(self, var_name):
        with _open_output(var_name) as ds:
            v = ds.variables[var_name]
            assert hasattr(v, 'cell_methods')
            assert 'time: mean' in v.cell_methods


# ============================================================
# Special attributes
# ============================================================

class TestSpecialAttributes:
    def test_tas_height_coordinate(self):
        """tas must have a scalar height coordinate at 2.0 m."""
        with _open_output('tas') as ds:
            assert 'height' in ds.variables, "tas needs scalar height coordinate"
            h = ds.variables['height']
            assert h.dimensions == (), "height must be scalar"
            assert abs(float(h[...]) - 2.0) < 0.01
            assert h.units == 'm'
            assert h.standard_name == 'height'
            assert h.positive == 'up'
            assert h.axis == 'Z'

    def test_tas_coordinates_attr(self):
        """tas variable should reference height in coordinates attribute."""
        with _open_output('tas') as ds:
            v = ds.variables['tas']
            assert hasattr(v, 'coordinates'), \
                "tas should have coordinates attribute listing height"
            assert 'height' in v.coordinates

    def test_huss_height_coordinate(self):
        """huss must have a scalar height coordinate at 2.0 m."""
        with _open_output('huss') as ds:
            assert 'height' in ds.variables, "huss needs scalar height coordinate"
            h = ds.variables['height']
            assert h.dimensions == (), "height must be scalar"
            assert abs(float(h[...]) - 2.0) < 0.01
            assert h.units == 'm'
            assert h.standard_name == 'height'
            assert h.positive == 'up'
            assert h.axis == 'Z'

    def test_huss_coordinates_attr(self):
        """huss variable should reference height in coordinates attribute."""
        with _open_output('huss') as ds:
            v = ds.variables['huss']
            assert hasattr(v, 'coordinates'), \
                "huss should have coordinates attribute listing height"
            assert 'height' in v.coordinates

    def test_rsds_positive_attribute(self):
        with _open_output('rsds') as ds:
            assert ds.variables['rsds'].positive == 'down'


# ============================================================
# Global attributes
# ============================================================

class TestGlobalAttributes:
    REQUIRED = ['Conventions', 'source', 'institution', 'title']

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_required_global_attrs(self, var_name):
        with _open_output(var_name) as ds:
            for attr in self.REQUIRED:
                assert attr in ds.ncattrs(), f"Missing global attr: {attr}"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_conventions_cf(self, var_name):
        with _open_output(var_name) as ds:
            assert 'CF' in ds.Conventions


# ============================================================
# Data value correctness — tas
# ============================================================

class TestTasValues:
    """Verify combined bias and lapse rate correction for temperature."""

    def test_tas_combined_correction_equator(self):
        """tas = raw t2m - 0.5 + 0.0065 * orog_diff at equatorial point."""
        raw = _open_raw()
        orog = _open_orog()
        out = _open_output('tas')
        rlat, rlon = raw.variables['latitude'][:], raw.variables['longitude'][:]
        olat, olon = out.variables['lat'][:], out.variables['lon'][:]
        orog_lat = orog.variables['latitude'][:]
        orog_lon = orog.variables['longitude'][:]

        ri, rj = _find_idx(rlat, 0.0), _find_idx(rlon, 90.0)
        oi, oj = _find_idx(olat, 0.0), _find_idx(olon, 90.0)
        ori, orj = _find_idx(orog_lat, 0.0), _find_idx(orog_lon, 90.0)

        raw_val = float(raw.variables['t2m'][0, ri, rj])
        orog_val = float(orog.variables['orog_diff'][ori, orj])
        out_val = float(out.variables['tas'][0, oi, oj])
        expected = float(np.float32(raw_val - 0.5 + 0.0065 * orog_val))
        np.testing.assert_allclose(out_val, expected, rtol=1e-5)
        raw.close(); orog.close(); out.close()

    def test_tas_combined_correction_high_lat(self):
        """Check combined correction at high latitude."""
        raw = _open_raw()
        orog = _open_orog()
        out = _open_output('tas')
        rlat = raw.variables['latitude'][:]
        rlon = raw.variables['longitude'][:]
        olat = out.variables['lat'][:]
        olon = out.variables['lon'][:]
        orog_lat = orog.variables['latitude'][:]
        orog_lon = orog.variables['longitude'][:]

        ri, rj = _find_idx(rlat, -60.0), _find_idx(rlon, 0.0)
        oi, oj = _find_idx(olat, -60.0), _find_idx(olon, 0.0)
        ori, orj = _find_idx(orog_lat, -60.0), _find_idx(orog_lon, 0.0)

        raw_val = float(raw.variables['t2m'][5, ri, rj])
        orog_val = float(orog.variables['orog_diff'][ori, orj])
        out_val = float(out.variables['tas'][5, oi, oj])
        expected = float(np.float32(raw_val - 0.5 + 0.0065 * orog_val))
        np.testing.assert_allclose(out_val, expected, rtol=1e-5)
        raw.close(); orog.close(); out.close()

    def test_tas_lapse_rate_not_ignored(self):
        """Verify the lapse rate correction is actually applied (not just constant bias)."""
        raw = _open_raw()
        orog = _open_orog()
        out = _open_output('tas')
        rlat = raw.variables['latitude'][:]
        rlon = raw.variables['longitude'][:]
        olat = out.variables['lat'][:]
        olon = out.variables['lon'][:]
        orog_lat = orog.variables['latitude'][:]
        orog_lon = orog.variables['longitude'][:]

        # Pick a point where orog_diff is significant
        ri, rj = _find_idx(rlat, 20.0), _find_idx(rlon, -90.0)
        oi, oj = _find_idx(olat, 20.0), _find_idx(olon, 270.0)
        ori, orj = _find_idx(orog_lat, 20.0), _find_idx(orog_lon, -90.0)

        raw_val = float(raw.variables['t2m'][0, ri, rj])
        orog_val = float(orog.variables['orog_diff'][ori, orj])
        out_val = float(out.variables['tas'][0, oi, oj])

        # Value with only constant bias correction (no lapse rate)
        constant_only = float(np.float32(raw_val - 0.5))
        # Value with full correction
        full_correction = float(np.float32(raw_val - 0.5 + 0.0065 * orog_val))

        # Output should match full correction, not constant-only
        if abs(orog_val) > 5.0:  # Only test if orog_diff is meaningful
            np.testing.assert_allclose(out_val, full_correction, rtol=1e-5)
            # Should differ from constant-only by the lapse rate amount
            assert abs(out_val - constant_only) > 0.01, \
                "Lapse rate correction appears to not be applied"

        raw.close(); orog.close(); out.close()

    def test_tas_physical_range(self):
        with _open_output('tas') as ds:
            tas = ds.variables['tas'][:]
            assert np.nanmin(tas) > 180, "Temperature too low"
            assert np.nanmax(tas) < 340, "Temperature too high"


# ============================================================
# Data value correctness — huss (derived variable)
# ============================================================

class TestHussValues:
    """Verify specific humidity derivation from dewpoint and surface pressure."""

    @staticmethod
    def _reference_huss(d2m_val, sp_val):
        """Compute reference huss using Tetens/Magnus formula."""
        T_c = d2m_val - 273.15
        e = 611.2 * np.exp(17.67 * T_c / (T_c + 243.5))
        q = 0.622 * e / (sp_val - 0.378 * e)
        return q

    def test_huss_derivation_equator(self):
        """huss derived from d2m and sp at equatorial point."""
        raw = _open_raw()
        out = _open_output('huss')
        rlat, rlon = raw.variables['latitude'][:], raw.variables['longitude'][:]
        olat, olon = out.variables['lat'][:], out.variables['lon'][:]

        ri, rj = _find_idx(rlat, 0.0), _find_idx(rlon, 90.0)
        oi, oj = _find_idx(olat, 0.0), _find_idx(olon, 90.0)

        d2m_val = float(raw.variables['d2m'][0, ri, rj])
        sp_val = float(raw.variables['sp'][0, ri, rj])

        expected = float(np.float32(self._reference_huss(d2m_val, sp_val)))
        out_val = float(out.variables['huss'][0, oi, oj])
        np.testing.assert_allclose(out_val, expected, rtol=0.02,
            err_msg="huss derivation incorrect at equator")
        raw.close(); out.close()

    def test_huss_derivation_midlatitude(self):
        """huss derived from d2m and sp at midlatitude point."""
        raw = _open_raw()
        out = _open_output('huss')
        rlat, rlon = raw.variables['latitude'][:], raw.variables['longitude'][:]
        olat, olon = out.variables['lat'][:], out.variables['lon'][:]

        ri, rj = _find_idx(rlat, 45.0), _find_idx(rlon, 135.0)
        oi, oj = _find_idx(olat, 45.0), _find_idx(olon, 135.0)

        d2m_val = float(raw.variables['d2m'][3, ri, rj])
        sp_val = float(raw.variables['sp'][3, ri, rj])

        expected = float(np.float32(self._reference_huss(d2m_val, sp_val)))
        out_val = float(out.variables['huss'][3, oi, oj])
        np.testing.assert_allclose(out_val, expected, rtol=0.02,
            err_msg="huss derivation incorrect at midlatitude")
        raw.close(); out.close()

    def test_huss_derivation_cold_region(self):
        """huss derived from d2m and sp at cold high-latitude point."""
        raw = _open_raw()
        out = _open_output('huss')
        rlat, rlon = raw.variables['latitude'][:], raw.variables['longitude'][:]
        olat, olon = out.variables['lat'][:], out.variables['lon'][:]

        ri, rj = _find_idx(rlat, -70.0), _find_idx(rlon, 0.0)
        oi, oj = _find_idx(olat, -70.0), _find_idx(olon, 0.0)

        d2m_val = float(raw.variables['d2m'][6, ri, rj])
        sp_val = float(raw.variables['sp'][6, ri, rj])

        expected = float(np.float32(self._reference_huss(d2m_val, sp_val)))
        out_val = float(out.variables['huss'][6, oi, oj])
        np.testing.assert_allclose(out_val, expected, rtol=0.02,
            err_msg="huss derivation incorrect at high latitude")
        raw.close(); out.close()

    def test_huss_spatial_gradient(self):
        """Equatorial huss should be substantially higher than polar huss."""
        out = _open_output('huss')
        lat = out.variables['lat'][:]
        ei = _find_idx(lat, 0.0)
        pi = _find_idx(lat, -70.0)

        huss_eq = float(np.nanmean(out.variables['huss'][0, ei, :]))
        huss_pole = float(np.nanmean(out.variables['huss'][0, pi, :]))

        assert huss_eq > huss_pole * 1.5, \
            f"Equatorial huss ({huss_eq:.6f}) should be much larger than polar ({huss_pole:.6f})"
        out.close()

    def test_huss_physical_range(self):
        """Specific humidity should be in realistic range."""
        with _open_output('huss') as ds:
            huss = ds.variables['huss'][:]
            assert np.nanmin(huss) > 0, "Specific humidity must be positive"
            assert np.nanmax(huss) < 0.04, "Specific humidity too high (>40 g/kg)"
            assert np.nanmin(huss) < 0.005, \
                "Minimum specific humidity unrealistically high — cold regions should have low huss"

    def test_huss_not_constant(self):
        """huss should not be a constant field (must vary in space and time)."""
        with _open_output('huss') as ds:
            huss = ds.variables['huss'][:]
            spatial_std = np.nanstd(huss[0, :, :])
            temporal_std = np.nanstd(huss[:, 36, 72])
            assert spatial_std > 1e-5, "huss appears spatially constant"
            assert temporal_std > 1e-6, "huss appears temporally constant"


# ============================================================
# Data value correctness — pr
# ============================================================

class TestPrValues:
    def test_pr_unit_conversion(self):
        """pr (kg m-2 s-1) = raw tp (m/month) * 1000 / seconds_in_month."""
        raw = _open_raw()
        out = _open_output('pr')
        rlat, rlon = raw.variables['latitude'][:], raw.variables['longitude'][:]
        olat, olon = out.variables['lat'][:], out.variables['lon'][:]

        ri, rj = _find_idx(rlat, 0.0), _find_idx(rlon, 90.0)
        oi, oj = _find_idx(olat, 0.0), _find_idx(olon, 90.0)

        raw_val = float(raw.variables['tp'][0, ri, rj])
        if raw_val == -9999.0:
            raw.close(); out.close()
            pytest.skip("Test point is a fill value")

        secs_jan = 31 * 86400
        expected = float(np.float32(raw_val * 1000.0 / secs_jan))
        out_val = float(out.variables['pr'][0, oi, oj])
        np.testing.assert_allclose(out_val, expected, rtol=1e-4)
        raw.close(); out.close()

    def test_pr_fill_masked(self):
        """Raw fill values (-9999) must not appear as converted data."""
        out = _open_output('pr')
        pr = out.variables['pr'][:]
        if isinstance(pr, np.ma.MaskedArray):
            arr = np.ma.filled(pr, np.nan)
        else:
            arr = np.asarray(pr, dtype=np.float64)
        valid = arr[np.isfinite(arr)]
        assert len(valid) > 0, "No valid data found"
        assert np.all(valid >= -1e-10), \
            "Negative precipitation found (likely unconverted fill values)"
        out.close()

    def test_pr_physical_range(self):
        out = _open_output('pr')
        pr = out.variables['pr'][:]
        if isinstance(pr, np.ma.MaskedArray):
            arr = np.ma.filled(pr, np.nan)
        else:
            arr = np.asarray(pr, dtype=np.float64)
        valid = arr[np.isfinite(arr)]
        assert len(valid) > 0
        assert np.all(valid >= 0), "Precipitation must be non-negative"
        assert np.max(valid) < 0.01, "Precipitation flux too high"
        out.close()


# ============================================================
# Data value correctness — rsds
# ============================================================

class TestRsdsValues:
    def test_rsds_unit_conversion(self):
        """rsds (W m-2) = raw ssrd (J m-2) / seconds_in_month."""
        raw = _open_raw()
        out = _open_output('rsds')
        rlat, rlon = raw.variables['latitude'][:], raw.variables['longitude'][:]
        olat, olon = out.variables['lat'][:], out.variables['lon'][:]

        ri, rj = _find_idx(rlat, 30.0), _find_idx(rlon, 45.0)
        oi, oj = _find_idx(olat, 30.0), _find_idx(olon, 45.0)

        secs_jan = 31 * 86400
        raw_val = float(raw.variables['ssrd'][0, ri, rj])
        expected = float(np.float32(raw_val / secs_jan))
        out_val = float(out.variables['rsds'][0, oi, oj])
        np.testing.assert_allclose(out_val, expected, rtol=1e-4)
        raw.close(); out.close()

    def test_month_varying_conversion(self):
        """Accumulated-to-flux conversion must use per-month seconds."""
        raw = _open_raw()
        out = _open_output('rsds')
        rlat, rlon = raw.variables['latitude'][:], raw.variables['longitude'][:]
        olat, olon = out.variables['lat'][:], out.variables['lon'][:]

        ri, rj = _find_idx(rlat, 30.0), _find_idx(rlon, 45.0)
        oi, oj = _find_idx(olat, 30.0), _find_idx(olon, 45.0)

        # Jan 2000 (31d), Feb 2000 (29d, leap), Apr 2000 (30d)
        for t, days in [(0, 31), (1, 29), (3, 30)]:
            secs = days * 86400
            raw_val = float(raw.variables['ssrd'][t, ri, rj])
            expected = float(np.float32(raw_val / secs))
            out_val = float(out.variables['rsds'][t, oi, oj])
            np.testing.assert_allclose(out_val, expected, rtol=1e-4,
                err_msg=f"t={t}, {days}-day month")
        raw.close(); out.close()

    def test_rsds_physical_range(self):
        with _open_output('rsds') as ds:
            rsds = ds.variables['rsds'][:]
            assert np.nanmin(rsds) >= -10, "Shortwave radiation too negative"
            assert np.nanmax(rsds) < 500, "Shortwave radiation too high"
