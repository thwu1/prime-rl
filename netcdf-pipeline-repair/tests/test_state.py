"""
Tests for the climate data pipeline outputs.

"""
import netCDF4 as nc
import numpy as np
import os
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_valid(var_data):
    """Return only valid (non-masked, finite) values from a netCDF variable read."""
    if isinstance(var_data, np.ma.MaskedArray):
        return var_data.compressed()
    arr = np.asarray(var_data).ravel()
    return arr[np.isfinite(arr)]


# ---------------------------------------------------------------------------
# timeseries.nc
# ---------------------------------------------------------------------------

class TestTimeseries:
    PATH = "/app/output/timeseries.nc"

    def test_file_exists(self):
        assert os.path.exists(self.PATH), "timeseries.nc not found in /app/output/"

    def test_dimensions(self):
        with nc.Dataset(self.PATH) as ds:
            assert "time" in ds.dimensions
            assert "lat" in ds.dimensions
            assert "lon" in ds.dimensions
            nt = len(ds.dimensions["time"])
            assert nt in (35, 36), f"Expected 35 or 36 time steps, got {nt}"
            assert len(ds.dimensions["lat"]) == 6
            assert len(ds.dimensions["lon"]) == 8

    def test_standard_coordinate_names(self):
        with nc.Dataset(self.PATH) as ds:
            assert "lat" in ds.variables, "Missing coordinate variable 'lat'"
            assert "lon" in ds.variables, "Missing coordinate variable 'lon'"
            assert "nav_lat" not in ds.variables, "'nav_lat' still present — not renamed"
            assert "nav_lon" not in ds.variables, "'nav_lon' still present — not renamed"

    def test_no_nan_fillvalue(self):
        with nc.Dataset(self.PATH) as ds:
            for vname in ("tas", "huss"):
                v = ds.variables[vname]
                if "_FillValue" in v.ncattrs():
                    fv = v.getncattr("_FillValue")
                    assert not np.isnan(fv), (
                        f"{vname} still has NaN as _FillValue — "
                        "must be changed to a numeric fill value"
                    )

    def test_no_corrupt_time_values(self):
        with nc.Dataset(self.PATH) as ds:
            tv = ds.variables["time"][:]
            if isinstance(tv, np.ma.MaskedArray):
                tv = tv.data
            assert np.all(tv >= 0), "Negative time values present (corrupt record not fixed)"

    def test_time_monotonic(self):
        with nc.Dataset(self.PATH) as ds:
            tv = ds.variables["time"][:]
            if isinstance(tv, np.ma.MaskedArray):
                tv = tv.data
            assert np.all(np.diff(tv) > 0), "Time values are not monotonically increasing"

    def test_has_data_variables(self):
        with nc.Dataset(self.PATH) as ds:
            assert "tas" in ds.variables, "Missing variable 'tas'"
            assert "huss" in ds.variables, "Missing variable 'huss'"

    def test_tas_physical_range(self):
        with nc.Dataset(self.PATH) as ds:
            valid = _get_valid(ds.variables["tas"][:])
            assert len(valid) > 0, "tas has no valid data at all"
            assert np.all(valid > 200) and np.all(valid < 350), (
                f"tas values out of physical range: [{valid.min():.1f}, {valid.max():.1f}]"
            )

    def test_huss_physical_range(self):
        with nc.Dataset(self.PATH) as ds:
            valid = _get_valid(ds.variables["huss"][:])
            assert len(valid) > 0, "huss has no valid data at all"
            assert np.all(valid > 0) and np.all(valid < 0.05), (
                f"huss values out of physical range: [{valid.min():.6f}, {valid.max():.6f}]"
            )


# ---------------------------------------------------------------------------
# climatology.nc
# ---------------------------------------------------------------------------

class TestClimatology:
    PATH = "/app/output/climatology.nc"

    def test_file_exists(self):
        assert os.path.exists(self.PATH), "climatology.nc not found in /app/output/"

    def test_time_dimension(self):
        with nc.Dataset(self.PATH) as ds:
            assert "time" in ds.dimensions
            assert len(ds.dimensions["time"]) == 12, (
                f"Expected 12 months, got {len(ds.dimensions['time'])}"
            )

    def test_spatial_dimensions(self):
        with nc.Dataset(self.PATH) as ds:
            assert len(ds.dimensions["lat"]) == 6
            assert len(ds.dimensions["lon"]) == 8

    def test_has_vpd_variable(self):
        with nc.Dataset(self.PATH) as ds:
            assert "vpd" in ds.variables, "Derived variable 'vpd' not found"

    def test_vpd_units(self):
        with nc.Dataset(self.PATH) as ds:
            v = ds.variables["vpd"]
            assert "units" in v.ncattrs(), "vpd missing 'units' attribute"
            assert v.getncattr("units") == "Pa", (
                f"vpd units should be 'Pa', got '{v.getncattr('units')}'"
            )

    def test_vpd_non_negative(self):
        with nc.Dataset(self.PATH) as ds:
            valid = _get_valid(ds.variables["vpd"][:])
            assert len(valid) > 0, "vpd has no valid data"
            assert np.all(valid >= -10), (
                "vpd has significantly negative values — formula error"
            )

    def test_vpd_upper_bound(self):
        with nc.Dataset(self.PATH) as ds:
            valid = _get_valid(ds.variables["vpd"][:])
            assert np.all(valid < 10000), (
                f"vpd values unreasonably large (max={valid.max():.1f})"
            )

    def test_all_months_have_valid_tas(self):
        """Each calendar month should have at least some valid tas data.

        If NaN fill values were not fixed, months that include 2018 data
        will be contaminated and this test will fail.
        """
        with nc.Dataset(self.PATH) as ds:
            tas = ds.variables["tas"][:]
            for m in range(12):
                month_slice = tas[m]
                if isinstance(month_slice, np.ma.MaskedArray):
                    valid_count = int(np.sum(~month_slice.mask))
                else:
                    valid_count = int(np.sum(np.isfinite(month_slice)))
                assert valid_count > 0, (
                    f"Month {m} climatology has no valid data — "
                    "NaN fill value likely not properly repaired"
                )

    def test_all_months_have_valid_vpd(self):
        with nc.Dataset(self.PATH) as ds:
            vpd = ds.variables["vpd"][:]
            for m in range(12):
                month_slice = vpd[m]
                if isinstance(month_slice, np.ma.MaskedArray):
                    valid_count = int(np.sum(~month_slice.mask))
                else:
                    valid_count = int(np.sum(np.isfinite(month_slice)))
                assert valid_count > 0, (
                    f"Month {m} vpd has no valid data"
                )


# ---------------------------------------------------------------------------
# global_means.nc
# ---------------------------------------------------------------------------

class TestGlobalMeans:
    PATH = "/app/output/global_means.nc"

    def test_file_exists(self):
        assert os.path.exists(self.PATH), "global_means.nc not found in /app/output/"

    def test_time_dimension(self):
        with nc.Dataset(self.PATH) as ds:
            assert "time" in ds.dimensions
            assert len(ds.dimensions["time"]) == 12

    def test_spatial_dimensions_collapsed(self):
        with nc.Dataset(self.PATH) as ds:
            for dname in ("lat", "lon", "y", "x"):
                if dname in ds.dimensions:
                    assert len(ds.dimensions[dname]) <= 1, (
                        f"Spatial dimension '{dname}' should be collapsed, "
                        f"has size {len(ds.dimensions[dname])}"
                    )

    def test_has_all_variables(self):
        with nc.Dataset(self.PATH) as ds:
            for vname in ("tas", "huss", "vpd"):
                assert vname in ds.variables, f"Missing variable '{vname}'"

    def test_tas_global_mean_range(self):
        with nc.Dataset(self.PATH) as ds:
            valid = _get_valid(ds.variables["tas"][:])
            assert len(valid) == 12, f"Expected 12 values, got {len(valid)}"
            assert np.all(valid > 250) and np.all(valid < 310), (
                f"Global mean tas out of range: [{valid.min():.1f}, {valid.max():.1f}]"
            )

    def test_huss_global_mean_range(self):
        with nc.Dataset(self.PATH) as ds:
            valid = _get_valid(ds.variables["huss"][:])
            assert len(valid) == 12
            assert np.all(valid > 0) and np.all(valid < 0.03), (
                f"Global mean huss out of range: "
                f"[{valid.min():.6f}, {valid.max():.6f}]"
            )

    def test_vpd_global_mean_range(self):
        with nc.Dataset(self.PATH) as ds:
            valid = _get_valid(ds.variables["vpd"][:])
            assert len(valid) == 12
            assert np.all(valid >= 0) and np.all(valid < 5000), (
                f"Global mean vpd out of range: [{valid.min():.1f}, {valid.max():.1f}]"
            )

    def test_tas_seasonal_cycle(self):
        """Global mean temperature should exhibit a clear seasonal cycle."""
        with nc.Dataset(self.PATH) as ds:
            valid = _get_valid(ds.variables["tas"][:])
            seasonal_range = float(valid.max() - valid.min())
            assert seasonal_range > 5.0, (
                f"Global mean tas seasonal range is only {seasonal_range:.1f} K — "
                "expected >5 K"
            )

    def test_values_are_finite(self):
        """All global mean values should be finite (catches unfixed NaN propagation)."""
        with nc.Dataset(self.PATH) as ds:
            for vname in ("tas", "huss", "vpd"):
                data = ds.variables[vname][:]
                if isinstance(data, np.ma.MaskedArray):
                    raw = data.data[~data.mask] if data.mask.any() else data.data
                else:
                    raw = np.asarray(data)
                assert np.all(np.isfinite(raw)), (
                    f"{vname} has non-finite values — "
                    "NaN fill values likely propagated through averaging"
                )
