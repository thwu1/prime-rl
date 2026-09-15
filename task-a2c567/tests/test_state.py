
"""CMOR compliance tests for CMORized observational climate data.

Verifies four output variables (tas, pr, psl, huss) including a derived
specific humidity field, 360-day to Gregorian calendar conversion, and
full CMOR metadata compliance."""
import os

import netCDF4 as nc
import numpy as np
import pytest

OUTPUT_DIR = "/app/output"

EXPECTED_FILES = {
    "tas": "OBS_RAWSTATION_ground_v3.2_Amon_tas_200001-200212.nc",
    "pr": "OBS_RAWSTATION_ground_v3.2_Amon_pr_200001-200212.nc",
    "psl": "OBS_RAWSTATION_ground_v3.2_Amon_psl_200001-200212.nc",
    "huss": "OBS_RAWSTATION_ground_v3.2_Amon_huss_200001-200212.nc",
}

EXPECTED_METADATA = {
    "tas": {
        "standard_name": "air_temperature",
        "units": "K",
        "long_name": "Near-Surface Air Temperature",
    },
    "pr": {
        "standard_name": "precipitation_flux",
        "units": "kg m-2 s-1",
        "long_name": "Precipitation",
    },
    "psl": {
        "standard_name": "air_pressure_at_mean_sea_level",
        "units": "Pa",
        "long_name": "Sea Level Pressure",
    },
    "huss": {
        "standard_name": "specific_humidity",
        "units": "1",
        "long_name": "Near-Surface Specific Humidity",
    },
}

VALID_RANGES = {
    "tas": (150.0, 350.0),
    "pr": (0.0, 0.01),
    "psl": (85000.0, 110000.0),
    "huss": (0.0, 0.04),
}

ALL_VARS = ["tas", "pr", "psl", "huss"]

REQUIRED_GLOBAL_ATTRS = [
    "project_id",
    "dataset_id",
    "version",
    "tier",
    "source",
    "reference",
    "comment",
]


# ---- File existence ----


class TestOutputFilesExist:
    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_output_file_exists(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        assert os.path.isfile(filepath), f"Output file not found: {filepath}"


# ---- Variable metadata ----


class TestVariableMetadata:
    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_variable_name_exists(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert var_name in ds.variables, (
                f"Variable '{var_name}' not found in {list(ds.variables.keys())}"
            )

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_standard_name(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            actual = ds[var_name].standard_name
            expected = EXPECTED_METADATA[var_name]["standard_name"]
            assert actual == expected, f"standard_name: expected '{expected}', got '{actual}'"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_units(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            actual = ds[var_name].units
            expected = EXPECTED_METADATA[var_name]["units"]
            assert actual == expected, f"units: expected '{expected}', got '{actual}'"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_long_name(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            actual = ds[var_name].long_name
            expected = EXPECTED_METADATA[var_name]["long_name"]
            assert actual == expected, f"long_name: expected '{expected}', got '{actual}'"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_data_dtype_is_float32(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert ds[var_name].dtype == np.float32, (
                f"Data dtype should be float32, got {ds[var_name].dtype}"
            )

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_fill_value(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            fv = float(ds[var_name]._FillValue)
            assert np.isclose(fv, 1e20, rtol=1e-5), (
                f"fill_value should be ~1e20, got {fv}"
            )


# ---- Coordinate metadata ----


class TestLongitude:
    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_longitude_range_0_360(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            lon = ds["longitude"][:]
            assert np.all(lon >= 0) and np.all(lon < 360), (
                f"Longitude must be in [0, 360), got range [{lon.min()}, {lon.max()}]"
            )

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_longitude_monotonically_increasing(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            lon = ds["longitude"][:]
            assert np.all(np.diff(lon) > 0), "Longitude not monotonically increasing"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_longitude_units(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert ds["longitude"].units == "degrees_east"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_longitude_standard_name(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert ds["longitude"].standard_name == "longitude"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_longitude_dtype_float64(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert ds["longitude"].dtype == np.float64, (
                f"Longitude dtype should be float64, got {ds['longitude'].dtype}"
            )

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_longitude_count(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert len(ds["longitude"][:]) == 144


class TestLatitude:
    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_latitude_monotonic(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            lat = ds["latitude"][:]
            increasing = np.all(np.diff(lat) > 0)
            decreasing = np.all(np.diff(lat) < 0)
            assert increasing or decreasing, "Latitude must be monotonic"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_latitude_units(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert ds["latitude"].units == "degrees_north"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_latitude_standard_name(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert ds["latitude"].standard_name == "latitude"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_latitude_dtype_float64(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert ds["latitude"].dtype == np.float64

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_latitude_count(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert len(ds["latitude"][:]) == 73


# ---- Calendar conversion from 360-day to Gregorian ----


class TestCalendarConversion:
    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_output_uses_gregorian_calendar(self, var_name):
        """Output must use gregorian/standard calendar, not 360_day."""
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            cal = ds["time"].calendar.lower()
            assert cal in ("gregorian", "standard"), (
                f"Output uses '{cal}' calendar. The raw 360_day calendar must be "
                f"converted to gregorian in the output."
            )

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_time_not_naive_360_scaling(self, var_name):
        """Time values must reflect proper Gregorian conversion, not naive scaling.

        A common mistake is to linearly scale 360-day time values to 365.25-day,
        which gives uniform month-to-month spacing. Proper Gregorian conversion
        produces variable spacing because months have different lengths (28-31 days).
        """
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            time = ds["time"][:]
            diffs = np.diff(time)
            # Gregorian months have variable lengths: 28, 29, 30, 31 days
            # Naive 360->365.25 scaling gives uniform ~30.4 day gaps
            unique_diffs = np.unique(np.round(diffs, 0))
            assert len(unique_diffs) > 1, (
                f"All time steps have the same spacing ({diffs[0]:.1f} days). "
                f"This suggests naive 360->365.25 scaling instead of proper "
                f"calendar conversion. Gregorian months have different lengths."
            )

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_february_bounds_leap_year(self, var_name):
        """February 2000 (leap year) bounds should span 29 days."""
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            bounds_name = getattr(ds["time"], "bounds", "time_bnds")
            if bounds_name not in ds.variables:
                for name in ("time_bnds", "time_bounds"):
                    if name in ds.variables:
                        bounds_name = name
                        break
            bnds = ds[bounds_name][:]
            # Index 1 = February 2000 (leap year)
            feb_2000_span = bnds[1, 1] - bnds[1, 0]
            assert abs(feb_2000_span - 29.0) < 0.5, (
                f"February 2000 (leap year) should span 29 days, got {feb_2000_span:.1f}. "
                f"Calendar-aware bounds must account for leap years."
            )

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_february_bounds_non_leap_year(self, var_name):
        """February 2001 (non-leap year) bounds should span 28 days."""
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            bounds_name = getattr(ds["time"], "bounds", "time_bnds")
            if bounds_name not in ds.variables:
                for name in ("time_bnds", "time_bounds"):
                    if name in ds.variables:
                        bounds_name = name
                        break
            bnds = ds[bounds_name][:]
            # Index 13 = February 2001 (non-leap year)
            feb_2001_span = bnds[13, 1] - bnds[13, 0]
            assert abs(feb_2001_span - 28.0) < 0.5, (
                f"February 2001 (non-leap year) should span 28 days, got {feb_2001_span:.1f}. "
                f"Calendar-aware bounds must distinguish leap from non-leap years."
            )


class TestTime:
    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_time_units_reference_epoch(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            units = ds["time"].units
            assert "days since 1950" in units, (
                f"Time units must reference 1950 epoch, got '{units}'"
            )

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_time_calendar_gregorian(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            cal = ds["time"].calendar.lower()
            assert cal in ("gregorian", "standard"), (
                f"Time calendar must be gregorian/standard, got '{cal}'"
            )

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_time_dtype_float64(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert ds["time"].dtype == np.float64

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_time_unlimited_dimension(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert ds.dimensions["time"].isunlimited(), (
                "Time dimension must be unlimited"
            )

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_time_length_36_months(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert len(ds["time"][:]) == 36

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_time_values_in_expected_range(self, var_name):
        """First time step ~Jan 2000 (~18276 days since 1950), last ~Dec 2002."""
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            time = ds["time"][:]
            assert time[0] > 18250 and time[0] < 18300, (
                f"First time value {time[0]} not in expected range for Jan 2000"
            )
            assert time[-1] > 19300 and time[-1] < 19370, (
                f"Last time value {time[-1]} not in expected range for Dec 2002"
            )

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_time_monotonically_increasing(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            time = ds["time"][:]
            assert np.all(np.diff(time) > 0), "Time not monotonically increasing"


# ---- Coordinate bounds ----


class TestBounds:
    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_longitude_bounds_exist(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            lon_var = ds["longitude"]
            bounds_name = getattr(lon_var, "bounds", None)
            if bounds_name and bounds_name in ds.variables:
                bnds = ds[bounds_name][:]
                assert bnds.shape == (len(ds["longitude"][:]), 2)
            else:
                found = False
                for name in ("longitude_bnds", "lon_bnds", "longitude_bounds"):
                    if name in ds.variables:
                        bnds = ds[name][:]
                        assert bnds.shape == (len(ds["longitude"][:]), 2)
                        found = True
                        break
                assert found, "No longitude bounds variable found"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_latitude_bounds_exist(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            lat_var = ds["latitude"]
            bounds_name = getattr(lat_var, "bounds", None)
            if bounds_name and bounds_name in ds.variables:
                bnds = ds[bounds_name][:]
                assert bnds.shape == (len(ds["latitude"][:]), 2)
            else:
                found = False
                for name in ("latitude_bnds", "lat_bnds", "latitude_bounds"):
                    if name in ds.variables:
                        bnds = ds[name][:]
                        assert bnds.shape == (len(ds["latitude"][:]), 2)
                        found = True
                        break
                assert found, "No latitude bounds variable found"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_time_bounds_exist(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            time_var = ds["time"]
            bounds_name = getattr(time_var, "bounds", None)
            if bounds_name and bounds_name in ds.variables:
                bnds = ds[bounds_name][:]
                assert bnds.shape == (len(ds["time"][:]), 2)
            else:
                found = False
                for name in ("time_bnds", "time_bounds"):
                    if name in ds.variables:
                        bnds = ds[name][:]
                        assert bnds.shape == (len(ds["time"][:]), 2)
                        found = True
                        break
                assert found, "No time bounds variable found"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_time_bounds_span_months(self, var_name):
        """Time bounds should span full calendar months (28-31 days in Gregorian)."""
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            bounds_name = getattr(ds["time"], "bounds", "time_bnds")
            if bounds_name not in ds.variables:
                for name in ("time_bnds", "time_bounds"):
                    if name in ds.variables:
                        bounds_name = name
                        break
            bnds = ds[bounds_name][:]
            assert np.all(bnds[:, 1] > bnds[:, 0]), (
                "Time bounds upper must exceed lower for each month"
            )
            spans = bnds[:, 1] - bnds[:, 0]
            assert np.all(spans >= 27) and np.all(spans <= 32), (
                f"Time bound spans should be 28-31 days, got range "
                f"[{spans.min():.1f}, {spans.max():.1f}]"
            )


# ---- Height2m scalar coordinate ----


class TestHeight2m:
    def test_height2m_scalar_coordinate_exists_for_tas(self):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"])
        with nc.Dataset(filepath) as ds:
            found = False
            for vname in ds.variables:
                v = ds[vname]
                if v.ndim == 0 and hasattr(v, "standard_name"):
                    if v.standard_name == "height":
                        val = float(v[()])
                        assert abs(val - 2.0) < 0.01, (
                            f"height2m value should be 2.0, got {val}"
                        )
                        assert v.units == "m", (
                            f"height2m units should be 'm', got '{v.units}'"
                        )
                        assert hasattr(v, "positive") and v.positive == "up", (
                            "height2m must have positive='up'"
                        )
                        found = True
                        break
            assert found, (
                "Scalar height coordinate (standard_name='height', value=2.0m) "
                "not found for tas"
            )

    def test_height2m_scalar_coordinate_exists_for_huss(self):
        """huss also requires height2m per CMOR table dimensions."""
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["huss"])
        with nc.Dataset(filepath) as ds:
            found = False
            for vname in ds.variables:
                v = ds[vname]
                if v.ndim == 0 and hasattr(v, "standard_name"):
                    if v.standard_name == "height":
                        val = float(v[()])
                        assert abs(val - 2.0) < 0.01
                        found = True
                        break
            assert found, (
                "Scalar height coordinate not found for huss. "
                "CMOR table specifies 'height2m' in huss dimensions."
            )

    def test_no_height2m_for_pr(self):
        """pr should NOT have a height2m coordinate."""
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["pr"])
        with nc.Dataset(filepath) as ds:
            for vname in ds.variables:
                v = ds[vname]
                if v.ndim == 0 and hasattr(v, "standard_name"):
                    if v.standard_name == "height":
                        pytest.fail("pr should not have a height2m coordinate")

    def test_no_height2m_for_psl(self):
        """psl should NOT have a height2m coordinate."""
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["psl"])
        with nc.Dataset(filepath) as ds:
            for vname in ds.variables:
                v = ds[vname]
                if v.ndim == 0 and hasattr(v, "standard_name"):
                    if v.standard_name == "height":
                        pytest.fail("psl should not have a height2m coordinate")


# ---- Global attributes ----


class TestGlobalAttributes:
    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_required_global_attrs_present(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            attrs = ds.ncattrs()
            for attr in REQUIRED_GLOBAL_ATTRS:
                assert attr in attrs, f"Missing required global attribute: '{attr}'"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_project_id_value(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert ds.project_id == "OBS"

    @pytest.mark.parametrize("var_name", ALL_VARS)
    def test_dataset_id_value(self, var_name):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
        with nc.Dataset(filepath) as ds:
            assert ds.dataset_id == "RAWSTATION"


# ---- Data value validation ----


class TestDataValues:
    def test_tas_values_in_valid_range(self):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"])
        with nc.Dataset(filepath) as ds:
            data = ds["tas"][:]
            valid = data.compressed() if hasattr(data, "compressed") else data[data < 9e19]
            assert len(valid) > 0, "All tas values are fill values"
            vmin, vmax = VALID_RANGES["tas"]
            assert np.all(valid >= vmin) and np.all(valid <= vmax), (
                f"tas values out of range [{vmin}, {vmax}]: "
                f"got [{valid.min()}, {valid.max()}]"
            )

    def test_tas_mean_indicates_correct_conversion(self):
        """Mean tas should be ~275 K (not ~309 which would indicate degF+273)."""
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"])
        with nc.Dataset(filepath) as ds:
            data = ds["tas"][:]
            valid = data.compressed() if hasattr(data, "compressed") else data[data < 9e19]
            mean_val = float(np.mean(valid))
            assert 250 < mean_val < 300, (
                f"Mean tas is {mean_val:.1f} K, expected ~275 K. "
                f"Check unit conversion from degF."
            )

    def test_pr_non_negative(self):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["pr"])
        with nc.Dataset(filepath) as ds:
            data = ds["pr"][:]
            valid = data.compressed() if hasattr(data, "compressed") else data[data < 9e19]
            assert len(valid) > 0, "All pr values are fill values"
            assert np.all(valid >= 0), (
                f"Precipitation contains negative values (min={valid.min():.2e}). "
                f"Physically invalid precipitation must be clipped."
            )

    def test_pr_values_in_valid_range(self):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["pr"])
        with nc.Dataset(filepath) as ds:
            data = ds["pr"][:]
            valid = data.compressed() if hasattr(data, "compressed") else data[data < 9e19]
            vmin, vmax = VALID_RANGES["pr"]
            assert np.all(valid <= vmax), (
                f"pr max {valid.max():.2e} exceeds valid_max {vmax}. "
                f"Check mm/day to kg m-2 s-1 conversion."
            )

    def test_psl_values_in_valid_range(self):
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["psl"])
        with nc.Dataset(filepath) as ds:
            data = ds["psl"][:]
            valid = data.compressed() if hasattr(data, "compressed") else data[data < 9e19]
            assert len(valid) > 0, "All psl values are fill values"
            vmin, vmax = VALID_RANGES["psl"]
            assert np.all(valid >= vmin) and np.all(valid <= vmax), (
                f"psl values out of range [{vmin}, {vmax}]: "
                f"got [{valid.min():.0f}, {valid.max():.0f}]. "
                f"Check hPa to Pa conversion."
            )

    def test_no_extra_variables_from_raw(self):
        """Output should not contain raw-only variables like quality_flag."""
        for var_name in ALL_VARS:
            filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var_name])
            with nc.Dataset(filepath) as ds:
                assert "quality_flag" not in ds.variables, (
                    "quality_flag from raw data should not appear in output"
                )
                assert "t2m" not in ds.variables
                assert "precip" not in ds.variables
                assert "mslp" not in ds.variables
                assert "rh2m" not in ds.variables


# ---- Derived variable (huss) tests ----


class TestDerivedHumidity:
    def test_huss_values_in_valid_range(self):
        """Specific humidity must be in [0, 0.04] kg/kg."""
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["huss"])
        with nc.Dataset(filepath) as ds:
            data = ds["huss"][:]
            valid = data.compressed() if hasattr(data, "compressed") else data[data < 9e19]
            assert len(valid) > 0, "All huss values are fill values"
            assert np.all(valid >= 0), (
                f"Negative specific humidity: min={valid.min():.6f}"
            )
            assert np.all(valid <= 0.04), (
                f"Specific humidity too high: max={valid.max():.6f}. "
                f"Valid range is [0, 0.04] kg/kg."
            )

    def test_huss_tropical_higher_than_polar(self):
        """Physical consistency: tropical humidity should exceed polar humidity.

        Warmer air holds more moisture (Clausius-Clapeyron). If the derivation
        formula is wrong, this spatial relationship will be violated.
        """
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["huss"])
        with nc.Dataset(filepath) as ds:
            data = ds["huss"][:]
            lat = ds["latitude"][:]
            tropical_idx = np.where(np.abs(lat) < 20)[0]
            polar_idx = np.where(np.abs(lat) > 60)[0]
            tropical_data = data[:, tropical_idx, :]
            polar_data = data[:, polar_idx, :]
            # Handle masked arrays
            if hasattr(tropical_data, "compressed"):
                tropical_mean = float(np.mean(tropical_data.compressed()))
                polar_mean = float(np.mean(polar_data.compressed()))
            else:
                tropical_mean = float(
                    np.mean(tropical_data[tropical_data < 9e19])
                )
                polar_mean = float(np.mean(polar_data[polar_data < 9e19]))
            assert tropical_mean > polar_mean, (
                f"Tropical mean huss ({tropical_mean:.6f}) should exceed "
                f"polar mean ({polar_mean:.6f}). The derivation formula "
                f"must produce physically consistent spatial patterns."
            )

    def test_huss_mean_reasonable(self):
        """Global mean specific humidity should be ~0.005-0.015 kg/kg."""
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["huss"])
        with nc.Dataset(filepath) as ds:
            data = ds["huss"][:]
            valid = data.compressed() if hasattr(data, "compressed") else data[data < 9e19]
            mean_val = float(np.mean(valid))
            assert 0.003 < mean_val < 0.020, (
                f"Global mean huss is {mean_val:.6f}, expected ~0.005-0.015. "
                f"This suggests the derivation formula may be incorrect."
            )

    def test_huss_mask_propagation(self):
        """huss must have at least as many fill values as any single source variable.

        Since huss is derived from t2m, rh2m, and mslp, any grid cell where
        ANY source variable is missing must also be missing in huss (union of masks).
        """
        raw_filepath = "/app/raw_data/station_obs_monthly_2000-2002.nc"
        huss_filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["huss"])

        with nc.Dataset(raw_filepath) as ds_raw:
            t2m_fill = int(np.sum(np.ma.getmaskarray(ds_raw["t2m"][:])))
            rh_fill = int(np.sum(np.ma.getmaskarray(ds_raw["rh2m"][:])))
            psl_fill = int(np.sum(np.ma.getmaskarray(ds_raw["mslp"][:])))
            max_single_fill = max(t2m_fill, rh_fill, psl_fill)

        with nc.Dataset(huss_filepath) as ds:
            huss_data = ds["huss"][:]
            if hasattr(huss_data, "compressed"):
                huss_fill = int(np.sum(np.ma.getmaskarray(huss_data)))
            else:
                huss_fill = int(np.sum(huss_data[:] > 9e19))

        assert huss_fill >= max_single_fill, (
            f"huss has {huss_fill} fill values but should have at least "
            f"{max_single_fill} (from the most-masked source variable). "
            f"Derived variables must propagate the union of source masks."
        )

    def test_huss_supersaturation_clipped(self):
        """Raw RH values exceeding 100% should be clipped before deriving huss.

        If supersaturation is not clipped, some huss values will be physically
        unrealistic (too high for the given temperature).
        """
        raw_filepath = "/app/raw_data/station_obs_monthly_2000-2002.nc"

        with nc.Dataset(raw_filepath) as ds_raw:
            rh = ds_raw["rh2m"][:]
            valid_rh = rh.compressed() if hasattr(rh, "compressed") else rh[rh > -9000]
            has_supersaturation = np.any(valid_rh > 100.0)

        assert has_supersaturation, (
            "Test precondition: raw RH should contain values > 100%"
        )

        # If supersaturation exists, verify huss doesn't exceed what RH=100% would give
        # at the warmest temperatures in the dataset
        filepath = os.path.join(OUTPUT_DIR, EXPECTED_FILES["huss"])
        with nc.Dataset(filepath) as ds:
            data = ds["huss"][:]
            valid = data.compressed() if hasattr(data, "compressed") else data[data < 9e19]
            # At T=350K (max valid) and P=85000Pa (min valid) with RH=100%:
            # es = 611.2 * exp(17.67*76.85/320.35) ≈ huge, q_max ≈ 0.04
            # Values should not exceed valid_max
            assert np.all(valid <= 0.04), (
                f"huss max={valid.max():.6f} exceeds 0.04. "
                f"Supersaturated RH values (>100%) must be clipped before derivation."
            )
