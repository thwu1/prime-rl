"""Tests for CMOR-compliant output files from the CMORizer script."""

import subprocess
import os
import json
import calendar
from datetime import datetime, timedelta

import numpy as np
import netCDF4 as nc
import pytest

OUTPUT_DIR = "/app/output"
RAW_FILE = "/app/raw_data/SynthObs_raw.nc"
CMOR_TABLE = "/app/cmor_table.json"

EXPECTED_FILES = {
    "tas": "OBS_SynthObs_ground_v1_Amon_tas_200001-200112.nc",
    "huss": "OBS_SynthObs_ground_v1_Amon_huss_200001-200112.nc",
    "pr": "OBS_SynthObs_ground_v1_Amon_pr_200001-200112.nc",
    "psl": "OBS_SynthObs_ground_v1_Amon_psl_200001-200112.nc",
}


@pytest.fixture(scope="session", autouse=True)
def run_cmorizer():
    """Run the cmorizer script before all tests."""
    result = subprocess.run(
        ["python3", "/app/cmorize.py"],
        capture_output=True, text=True, timeout=120
    )
    yield result


@pytest.fixture
def cmor_table():
    with open(CMOR_TABLE) as f:
        return json.load(f)


# --- Output file existence ------------------------------------------------

class TestOutputFilesExist:

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_output_file_exists(self, var_name, filename):
        assert os.path.exists(os.path.join(OUTPUT_DIR, filename)), \
            f"Missing: {filename}"

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_output_is_valid_netcdf(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        ds.close()


# --- Coordinate compliance ------------------------------------------------

class TestCoordinates:

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_longitude_range_0_360(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        lon = ds.variables['longitude'][:]
        assert np.all(lon >= 0) and np.all(lon < 360), \
            f"Lon range [{lon.min()}, {lon.max()}], expected [0, 360)"
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_longitude_monotonic_increasing(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        lon = ds.variables['longitude'][:]
        assert np.all(np.diff(lon) > 0)
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_longitude_values(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        lon = ds.variables['longitude'][:]
        expected = np.arange(0, 360, 5, dtype=np.float64)
        np.testing.assert_array_almost_equal(lon, expected, decimal=4)
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_latitude_monotonic_increasing(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        lat = ds.variables['latitude'][:]
        assert np.all(np.diff(lat) > 0), "Latitude not S->N"
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_latitude_values(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        lat = ds.variables['latitude'][:]
        expected = np.linspace(-87.5, 87.5, 36)
        np.testing.assert_array_almost_equal(lat, expected, decimal=4)
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_longitude_has_bounds(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        found = False
        for name in ['longitude_bnds', 'longitude_bounds', 'lon_bnds']:
            if name in ds.variables:
                assert ds.variables[name].shape == (72, 2)
                found = True
                break
        if not found:
            lon_var = ds.variables['longitude']
            assert hasattr(lon_var, 'bounds'), "No longitude bounds attribute"
            bname = lon_var.bounds
            assert bname in ds.variables, f"Bounds var {bname} missing"
            assert ds.variables[bname].shape == (72, 2)
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_latitude_has_bounds(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        found = False
        for name in ['latitude_bnds', 'latitude_bounds', 'lat_bnds']:
            if name in ds.variables:
                assert ds.variables[name].shape == (36, 2)
                found = True
                break
        if not found:
            lat_var = ds.variables['latitude']
            assert hasattr(lat_var, 'bounds'), "No latitude bounds attribute"
            bname = lat_var.bounds
            assert bname in ds.variables
            assert ds.variables[bname].shape == (36, 2)
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_time_units_epoch(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        assert 'days since 1850-01-01' in ds.variables['time'].units
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_time_calendar(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        cal = getattr(ds.variables['time'], 'calendar', 'standard').lower()
        assert cal in ('gregorian', 'standard', 'proleptic_gregorian')
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_time_has_bounds(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        found = False
        for name in ['time_bnds', 'time_bounds']:
            if name in ds.variables:
                assert ds.variables[name].shape[1] == 2
                found = True
                break
        if not found:
            tv = ds.variables['time']
            assert hasattr(tv, 'bounds'), "No time bounds"
            bname = tv.bounds
            assert bname in ds.variables
            assert ds.variables[bname].shape[1] == 2
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_time_length_24(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        assert len(ds.variables['time'][:]) == 24
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_coordinate_dtype_float64(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        for coord in ['longitude', 'latitude', 'time']:
            assert ds.variables[coord].dtype == np.float64, \
                f"{coord} dtype {ds.variables[coord].dtype} != float64"
        ds.close()


# --- Variable metadata ----------------------------------------------------

class TestVariableMetadata:

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_cmor_variable_exists(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        assert var_name in ds.variables, \
            f"{var_name} not found; have {list(ds.variables)}"
        ds.close()

    def test_tas_standard_name(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        assert ds.variables['tas'].standard_name == 'air_temperature'
        ds.close()

    def test_huss_standard_name(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['huss']), 'r')
        assert ds.variables['huss'].standard_name == 'specific_humidity'
        ds.close()

    def test_pr_standard_name(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['pr']), 'r')
        assert ds.variables['pr'].standard_name == 'precipitation_flux'
        ds.close()

    def test_psl_standard_name(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['psl']), 'r')
        assert ds.variables['psl'].standard_name == 'air_pressure_at_mean_sea_level'
        ds.close()

    def test_tas_units_kelvin(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        assert ds.variables['tas'].units == 'K'
        ds.close()

    def test_huss_units(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['huss']), 'r')
        assert ds.variables['huss'].units == '1'
        ds.close()

    def test_pr_units_flux(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['pr']), 'r')
        assert ds.variables['pr'].units == 'kg m-2 s-1'
        ds.close()

    def test_psl_units_pascal(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['psl']), 'r')
        assert ds.variables['psl'].units == 'Pa'
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_cell_methods_present(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        v = ds.variables[var_name]
        assert hasattr(v, 'cell_methods'), f"{var_name} missing cell_methods"
        assert 'time' in v.cell_methods and 'mean' in v.cell_methods
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_data_dtype_float32(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        assert ds.variables[var_name].dtype == np.float32, \
            f"{var_name} dtype {ds.variables[var_name].dtype} != float32"
        ds.close()


# --- Scalar coordinates ---------------------------------------------------

class TestScalarCoordinates:

    def test_tas_has_height_2m(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        assert 'height' in ds.variables, "tas missing height coordinate"
        h = ds.variables['height']
        assert float(h[:]) == pytest.approx(2.0)
        assert h.units == 'm'
        assert h.positive == 'up'
        assert h.standard_name == 'height'
        ds.close()

    def test_huss_has_height_2m(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['huss']), 'r')
        assert 'height' in ds.variables, "huss missing height coordinate"
        h = ds.variables['height']
        assert float(h[:]) == pytest.approx(2.0)
        assert h.units == 'm'
        assert h.positive == 'up'
        ds.close()

    def test_pr_no_height(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['pr']), 'r')
        assert 'height' not in ds.variables
        ds.close()

    def test_psl_no_height(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['psl']), 'r')
        assert 'height' not in ds.variables
        ds.close()


# --- Standard data transformations ----------------------------------------

class TestStandardTransformations:
    """Verify unit conversions and coordinate remapping.

    Index mapping after coordinate transforms:
    - Raw lon index i  -> out lon index (i - 36) % 72
    - Raw lat index j  -> out lat index 35 - j
    """

    def test_temperature_celsius_to_kelvin(self):
        raw = nc.Dataset(RAW_FILE, 'r')
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        raw_val = float(np.array(raw.variables['t2m'][1, 18, 40]))
        out_val = float(np.array(out.variables['tas'][1, 17, 4]))
        expected = raw_val + 273.15
        assert abs(out_val - expected) < 0.1, \
            f"T conversion: raw={raw_val} C -> out={out_val} K, expected={expected} K"
        raw.close(); out.close()

    def test_pressure_hpa_to_pa(self):
        raw = nc.Dataset(RAW_FILE, 'r')
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['psl']), 'r')
        raw_val = float(np.array(raw.variables['mslp'][1, 18, 40]))
        out_val = float(np.array(out.variables['psl'][1, 17, 4]))
        expected = raw_val * 100.0
        assert abs(out_val - expected) < 1.0, \
            f"Pressure: raw={raw_val} hPa -> out={out_val} Pa, expected={expected} Pa"
        raw.close(); out.close()

    def test_longitude_wrapping_0deg(self):
        """Data at raw lon=0 deg (index 36) should appear at out lon=0 deg (index 0)."""
        raw = nc.Dataset(RAW_FILE, 'r')
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['psl']), 'r')
        raw_val = float(np.array(raw.variables['mslp'][2, 18, 36]))
        out_val = float(np.array(out.variables['psl'][2, 17, 0]))
        assert abs(out_val - raw_val * 100.0) < 1.0, \
            "Lon wrapping at 0 deg failed"
        raw.close(); out.close()

    def test_longitude_wrapping_180deg(self):
        """Data at raw lon=-180 deg (index 0) should appear at out lon=180 deg (index 36)."""
        raw = nc.Dataset(RAW_FILE, 'r')
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['psl']), 'r')
        raw_val = float(np.array(raw.variables['mslp'][2, 18, 0]))
        out_val = float(np.array(out.variables['psl'][2, 17, 36]))
        assert abs(out_val - raw_val * 100.0) < 1.0, \
            "Lon wrapping at 180 deg failed"
        raw.close(); out.close()

    def test_latitude_flip_north(self):
        """Data at raw lat[0]=87.5 deg -> out lat[35]=87.5 deg."""
        raw = nc.Dataset(RAW_FILE, 'r')
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        raw_val = float(np.array(raw.variables['t2m'][2, 0, 40]))
        out_val = float(np.array(out.variables['tas'][2, 35, 4]))
        assert abs(out_val - (raw_val + 273.15)) < 0.1, "Lat flip at north failed"
        raw.close(); out.close()

    def test_latitude_flip_south(self):
        """Data at raw lat[35]=-87.5 deg -> out lat[0]=-87.5 deg."""
        raw = nc.Dataset(RAW_FILE, 'r')
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        raw_val = float(np.array(raw.variables['t2m'][2, 35, 40]))
        out_val = float(np.array(out.variables['tas'][2, 0, 4]))
        assert abs(out_val - (raw_val + 273.15)) < 0.1, "Lat flip at south failed"
        raw.close(); out.close()


# --- Derived variable: specific humidity -----------------------------------

class TestSpecificHumidity:

    def test_huss_derivation_point1(self):
        """Verify specific humidity at a known clean grid point."""
        raw = nc.Dataset(RAW_FILE, 'r')
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['huss']), 'r')

        # Raw [1, 18, 40] -> output [1, 17, 4]
        td = float(np.array(raw.variables['d2m'][1, 18, 40]))
        p = float(np.array(raw.variables['mslp'][1, 18, 40]))

        # Magnus formula (constants from CMOR table)
        a, b, c, eps = 6.112, 17.67, 243.5, 0.622
        e = a * np.exp(b * td / (td + c))
        expected_q = eps * e / (p - (1 - eps) * e)

        out_val = float(np.array(out.variables['huss'][1, 17, 4]))
        assert abs(out_val - expected_q) / max(abs(expected_q), 1e-15) < 0.02, \
            f"huss: out={out_val}, expected={expected_q}"
        raw.close(); out.close()

    def test_huss_derivation_point2(self):
        """Verify at a second grid point with different climate."""
        raw = nc.Dataset(RAW_FILE, 'r')
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['huss']), 'r')

        # Raw [6, 30, 55] -> output [6, 5, 19]
        td = float(np.array(raw.variables['d2m'][6, 30, 55]))
        p = float(np.array(raw.variables['mslp'][6, 30, 55]))

        a, b, c, eps = 6.112, 17.67, 243.5, 0.622
        e = a * np.exp(b * td / (td + c))
        expected_q = eps * e / (p - (1 - eps) * e)

        out_val = float(np.array(out.variables['huss'][6, 5, 19]))
        assert abs(out_val - expected_q) / max(abs(expected_q), 1e-15) < 0.02, \
            f"huss: out={out_val}, expected={expected_q}"
        raw.close(); out.close()

    def test_huss_physically_reasonable(self):
        """Specific humidity should be between 0 and 0.04 kg/kg."""
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['huss']), 'r')
        data = ds.variables['huss'][:]
        if isinstance(data, np.ma.MaskedArray):
            valid = data.compressed()
        else:
            fv = getattr(ds.variables['huss'], '_FillValue', None)
            if fv is not None:
                valid = data[~np.isclose(data, fv)]
            else:
                valid = data.ravel()
        assert np.all(valid >= 0), "Negative specific humidity found"
        assert np.all(valid < 0.04), "Specific humidity > 0.04 unrealistic"
        ds.close()


# --- Precipitation deaccumulation -----------------------------------------

class TestPrecipitationDeaccumulation:

    def test_pr_february_deaccumulated(self):
        """February requires differencing from January accumulation."""
        raw = nc.Dataset(RAW_FILE, 'r')
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['pr']), 'r')

        # Raw [1, 18, 40] (Feb 2000) -> output [1, 17, 4]
        tp_feb = float(np.array(raw.variables['tp_acc'][1, 18, 40]))
        tp_jan = float(np.array(raw.variables['tp_acc'][0, 18, 40]))
        monthly_m = tp_feb - tp_jan

        # Feb 2000: 29 days (leap year) = 2505600 seconds
        expected_flux = monthly_m * 1000.0 / (29 * 86400.0)

        out_val = float(np.array(out.variables['pr'][1, 17, 4]))
        assert abs(out_val - expected_flux) / max(abs(expected_flux), 1e-15) < 0.01, \
            f"pr Feb: out={out_val}, expected={expected_flux}"
        raw.close(); out.close()

    def test_pr_january_2001_reset(self):
        """January of new year: accumulation resets, value IS the monthly total."""
        raw = nc.Dataset(RAW_FILE, 'r')
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['pr']), 'r')

        # Raw [12, 18, 40] (Jan 2001) -> output [12, 17, 4]
        tp_jan2001 = float(np.array(raw.variables['tp_acc'][12, 18, 40]))
        # January: 31 days = 2678400 seconds
        expected_flux = tp_jan2001 * 1000.0 / (31 * 86400.0)

        out_val = float(np.array(out.variables['pr'][12, 17, 4]))
        assert abs(out_val - expected_flux) / max(abs(expected_flux), 1e-15) < 0.01, \
            f"pr Jan2001: out={out_val}, expected={expected_flux}"
        raw.close(); out.close()

    def test_pr_june_deaccumulated(self):
        """June deaccumulation: June accumulation minus May accumulation."""
        raw = nc.Dataset(RAW_FILE, 'r')
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['pr']), 'r')

        # Raw [5, 18, 40] (Jun 2000) -> output [5, 17, 4]
        tp_jun = float(np.array(raw.variables['tp_acc'][5, 18, 40]))
        tp_may = float(np.array(raw.variables['tp_acc'][4, 18, 40]))
        monthly_m = tp_jun - tp_may

        # June: 30 days = 2592000 seconds
        expected_flux = monthly_m * 1000.0 / (30 * 86400.0)

        out_val = float(np.array(out.variables['pr'][5, 17, 4]))
        assert abs(out_val - expected_flux) / max(abs(expected_flux), 1e-15) < 0.01
        raw.close(); out.close()

    def test_pr_month_varying_conversion(self):
        """Different months have different lengths, yielding different conversion factors."""
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['pr']), 'r')
        raw = nc.Dataset(RAW_FILE, 'r')

        # April 2000 (time idx 3, 30 days) and March 2000 (time idx 2, 31 days)
        tp_apr = float(np.array(raw.variables['tp_acc'][3, 18, 40]))
        tp_mar = float(np.array(raw.variables['tp_acc'][2, 18, 40]))
        tp_feb = float(np.array(raw.variables['tp_acc'][1, 18, 40]))

        monthly_apr = tp_apr - tp_mar
        monthly_mar = tp_mar - tp_feb

        flux_apr = monthly_apr * 1000.0 / (30 * 86400.0)
        flux_mar = monthly_mar * 1000.0 / (31 * 86400.0)

        out_apr = float(np.array(out.variables['pr'][3, 17, 4]))
        out_mar = float(np.array(out.variables['pr'][2, 17, 4]))

        assert abs(out_apr - flux_apr) / max(abs(flux_apr), 1e-15) < 0.01
        assert abs(out_mar - flux_mar) / max(abs(flux_mar), 1e-15) < 0.01
        raw.close(); out.close()

    def test_pr_non_negative(self):
        """All precipitation values should be non-negative."""
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['pr']), 'r')
        data = ds.variables['pr'][:]
        if isinstance(data, np.ma.MaskedArray):
            valid = data.compressed()
        else:
            fv = getattr(ds.variables['pr'], '_FillValue', None)
            if fv is not None:
                valid = data[~np.isclose(data, fv)]
            else:
                valid = data.ravel()
        assert np.all(valid >= 0), f"Negative pr values found: min={valid.min()}"
        ds.close()

    def test_pr_physically_reasonable(self):
        """All valid precipitation flux values should be within physical bounds."""
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['pr']), 'r')
        data = ds.variables['pr'][:]
        if isinstance(data, np.ma.MaskedArray):
            valid = data.compressed()
        else:
            fv = getattr(ds.variables['pr'], '_FillValue', None)
            if fv is not None:
                valid = data[~np.isclose(data, fv)]
            else:
                valid = data.ravel()
        assert np.all(valid < 1e-3), \
            f"Unrealistic pr values found: max={valid.max()}"
        ds.close()


# --- Quality flag masking -------------------------------------------------

class TestQualityFlagMasking:

    def _is_masked_or_fill(self, ds, var_name, t, lat, lon):
        """Check if a value is masked or fill."""
        val = ds.variables[var_name][t, lat, lon]
        if isinstance(val, np.ma.core.MaskedConstant):
            return True
        if isinstance(val, np.ma.MaskedArray) and val.mask:
            return True
        fv = getattr(ds.variables[var_name], '_FillValue', None)
        if fv is not None:
            val_f = float(np.array(val))
            if abs(val_f - float(fv)) < 1e15:
                return True
        return False

    def test_tas_bit0_masked(self):
        """Quality flag bit 0 (sensor malfunction) should mask the value."""
        # Raw [2, 5, 10] qf_t2m=0x01 -> output [2, 30, 46]
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        assert self._is_masked_or_fill(ds, 'tas', 2, 30, 46), \
            "bit 0 flagged point not masked in tas"
        ds.close()

    def test_tas_bit1_masked(self):
        """Quality flag bit 1 (out-of-range) should mask the value."""
        # Raw [4, 20, 50] qf_t2m=0x02 -> output [4, 15, 14]
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        assert self._is_masked_or_fill(ds, 'tas', 4, 15, 14), \
            "bit 1 flagged point not masked in tas"
        ds.close()

    def test_tas_bit2_NOT_masked(self):
        """Quality flag bit 2 (interpolated) should NOT be masked."""
        # Raw [3, 8, 16] qf_t2m=0x04 -> output [3, 27, 52]
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        assert not self._is_masked_or_fill(ds, 'tas', 3, 27, 52), \
            "bit 2 flagged point incorrectly masked in tas"
        ds.close()

    def test_tas_combined_bits_masked(self):
        """Quality flag 0x05 (bits 0+2) should be masked (bit 0 triggers mask)."""
        # Raw [10, 22, 45] qf_t2m=0x05 -> output [10, 13, 9]
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        assert self._is_masked_or_fill(ds, 'tas', 10, 13, 9), \
            "combined bit 0+2 flagged point not masked in tas"
        ds.close()

    def test_tas_bit3_NOT_masked(self):
        """Quality flag bit 3 (suspect) should NOT be masked."""
        # Raw [16, 28, 55] qf_t2m=0x08 -> output [16, 7, 19]
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        assert not self._is_masked_or_fill(ds, 'tas', 16, 7, 19), \
            "bit 3 flagged point incorrectly masked in tas"
        ds.close()

    def test_huss_masked_from_d2m_flag(self):
        """huss should be masked when d2m has mask bit set (union mode)."""
        # qf_d2m[3, 10, 20]=0x01 -> output [3, 25, 56]
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['huss']), 'r')
        assert self._is_masked_or_fill(ds, 'huss', 3, 25, 56), \
            "huss not masked despite d2m quality flag"
        ds.close()

    def test_huss_masked_from_mslp_flag(self):
        """huss should be masked when mslp has mask bit set (union mode)."""
        # qf_mslp[9, 15, 40]=0x02 -> output [9, 20, 4]
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['huss']), 'r')
        assert self._is_masked_or_fill(ds, 'huss', 9, 20, 4), \
            "huss not masked despite mslp quality flag"
        ds.close()

    def test_huss_bit2_NOT_masked(self):
        """huss should NOT be masked when only bit 2 (interpolated) is set on an input."""
        # qf_d2m[5, 14, 28]=0x04 -> output [5, 21, 64]
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['huss']), 'r')
        assert not self._is_masked_or_fill(ds, 'huss', 5, 21, 64), \
            "huss incorrectly masked for bit 2 flag"
        ds.close()

    def test_pr_bit0_masked(self):
        """pr should be masked when quality flag bit 0 is set."""
        # qf_tp[5, 20, 35]=0x01 -> output [5, 15, 71]
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['pr']), 'r')
        assert self._is_masked_or_fill(ds, 'pr', 5, 15, 71), \
            "pr not masked despite quality flag bit 0"
        ds.close()

    def test_psl_bit1_masked(self):
        """psl should be masked when quality flag bit 1 is set."""
        # qf_mslp[6, 12, 25]=0x02 -> output [6, 23, 61]
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['psl']), 'r')
        assert self._is_masked_or_fill(ds, 'psl', 6, 23, 61), \
            "psl not masked despite quality flag bit 1"
        ds.close()


# --- Missing value handling -----------------------------------------------

class TestMissingValues:

    def test_tas_missing_value_masked(self):
        """Raw t2m[0,0,0]=-9999 -> out tas[0,35,36] must be masked/fill."""
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        val = out.variables['tas'][0, 35, 36]
        is_masked = isinstance(val, np.ma.core.MaskedConstant) or \
                    (isinstance(val, np.ma.MaskedArray) and val.mask)
        if not is_masked:
            fv = getattr(out.variables['tas'], '_FillValue', None)
            val_f = float(np.array(val))
            is_fill = (fv is not None and abs(val_f - float(fv)) < 1e10)
            is_nan = np.isnan(val_f)
            assert is_fill or is_nan, \
                f"Missing value not handled at [0,35,36]: {val_f}"
        out.close()

    def test_fill_value_1e20(self):
        for var_name, filename in EXPECTED_FILES.items():
            ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
            fv = getattr(ds.variables[var_name], '_FillValue', None)
            if fv is not None:
                assert abs(float(fv) - 1e20) < 1e15, \
                    f"{var_name} fill={fv}, expected ~1e20"
            ds.close()

    def test_data_mostly_valid(self):
        for var_name, filename in EXPECTED_FILES.items():
            ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
            data = ds.variables[var_name][:]
            if isinstance(data, np.ma.MaskedArray):
                frac = 1.0 - data.mask.sum() / data.size
            else:
                fv = getattr(ds.variables[var_name], '_FillValue', None)
                if fv is not None:
                    frac = 1.0 - (np.isclose(data, fv)).sum() / data.size
                else:
                    frac = 1.0 - np.isnan(data).sum() / data.size
            assert frac > 0.99, f"{var_name}: only {frac*100:.1f}% valid"
            ds.close()


# --- Time conversion ------------------------------------------------------

class TestTimeConversion:

    def test_time_conversion_first_step(self):
        raw = nc.Dataset(RAW_FILE, 'r')
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        raw_hours = float(raw.variables['time'][0])
        raw_dt = datetime(2000, 1, 1) + timedelta(hours=raw_hours)
        expected_days = (raw_dt - datetime(1850, 1, 1)).total_seconds() / 86400.0
        out_days = float(out.variables['time'][0])
        assert abs(out_days - expected_days) < 0.01
        raw.close(); out.close()

    def test_time_bounds_first_month(self):
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        tv = out.variables['time']
        bname = getattr(tv, 'bounds', None)
        bounds = None
        if bname and bname in out.variables:
            bounds = out.variables[bname][:]
        else:
            for name in ['time_bnds', 'time_bounds']:
                if name in out.variables:
                    bounds = out.variables[name][:]
                    break
        assert bounds is not None, "Cannot find time bounds"
        ref = datetime(1850, 1, 1)
        jan1 = (datetime(2000, 1, 1) - ref).days
        feb1 = (datetime(2000, 2, 1) - ref).days
        assert abs(bounds[0, 0] - jan1) < 0.01
        assert abs(bounds[0, 1] - feb1) < 0.01
        out.close()

    def test_time_bounds_last_month(self):
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES['tas']), 'r')
        tv = out.variables['time']
        bname = getattr(tv, 'bounds', None)
        bounds = None
        if bname and bname in out.variables:
            bounds = out.variables[bname][:]
        else:
            for name in ['time_bnds', 'time_bounds']:
                if name in out.variables:
                    bounds = out.variables[name][:]
                    break
        assert bounds is not None
        ref = datetime(1850, 1, 1)
        dec1 = (datetime(2001, 12, 1) - ref).days
        jan1_2002 = (datetime(2002, 1, 1) - ref).days
        assert abs(bounds[23, 0] - dec1) < 0.01
        assert abs(bounds[23, 1] - jan1_2002) < 0.01
        out.close()


# --- Global attributes ----------------------------------------------------

class TestGlobalAttributes:

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_conventions_cf(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        conv = getattr(ds, 'Conventions', '')
        assert 'CF' in conv, f"Conventions='{conv}', expected CF"
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_has_project_id(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        attrs = ds.ncattrs()
        assert any(a in attrs for a in ['project_id', 'project']), \
            "Missing project_id"
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_frequency_mon(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        assert getattr(ds, 'frequency', '') == 'mon'
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_has_institute(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        attrs = ds.ncattrs()
        assert any(a in attrs for a in
                   ['institute_id', 'institution_id', 'institution'])
        ds.close()

    @pytest.mark.parametrize("var_name,filename", list(EXPECTED_FILES.items()))
    def test_has_source(self, var_name, filename):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, filename), 'r')
        assert hasattr(ds, 'source'), "Missing source attribute"
        ds.close()
