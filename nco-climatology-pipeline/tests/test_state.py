
"""Tests for the NCO climate data pipeline output."""
import math
import os

import numpy as np
import pytest
from netCDF4 import Dataset

OUTPUT_FILE = "/app/output/climatology.nc"


@pytest.fixture
def ds():
    """Open the output dataset."""
    assert os.path.exists(OUTPUT_FILE), "Output file {} does not exist".format(OUTPUT_FILE)
    d = Dataset(OUTPUT_FILE, "r")
    yield d
    d.close()


def _get_valid(data):
    """Extract valid (non-masked, non-NaN) values from a possibly-masked array."""
    if hasattr(data, "compressed"):
        vals = data.compressed()
    else:
        vals = np.asarray(data).ravel()
    return vals[~np.isnan(vals)]


def _get_lat_name(ds):
    if "lat" in ds.dimensions:
        return "lat"
    if "latitude" in ds.dimensions:
        return "latitude"
    raise KeyError("No lat/latitude dimension found")


def _get_lon_name(ds):
    if "lon" in ds.dimensions:
        return "lon"
    if "longitude" in ds.dimensions:
        return "longitude"
    raise KeyError("No lon/longitude dimension found")


# -------------------------------------------------------------------
# Structure tests
# -------------------------------------------------------------------
class TestFileStructure:
    def test_file_exists(self):
        assert os.path.exists(OUTPUT_FILE)

    def test_time_dimension(self, ds):
        assert "time" in ds.dimensions
        assert len(ds.dimensions["time"]) == 12

    def test_lat_dimension_exists(self, ds):
        lat_name = _get_lat_name(ds)
        assert len(ds.dimensions[lat_name]) == 36

    def test_lon_dimension_exists(self, ds):
        lon_name = _get_lon_name(ds)
        assert len(ds.dimensions[lon_name]) == 72

    def test_cf_dimension_names(self, ds):
        assert "lat" in ds.dimensions, "Spatial dimension should be 'lat', not 'latitude'"
        assert "lon" in ds.dimensions, "Spatial dimension should be 'lon', not 'longitude'"


# -------------------------------------------------------------------
# Variable existence
# -------------------------------------------------------------------
class TestVariables:
    def test_tas_exists(self, ds):
        assert "tas" in ds.variables

    def test_uas_exists(self, ds):
        assert "uas" in ds.variables

    def test_vas_exists(self, ds):
        assert "vas" in ds.variables

    def test_wsp_exists(self, ds):
        assert "wsp" in ds.variables

    def test_tas_global_mean_exists(self, ds):
        assert "tas_global_mean" in ds.variables

    def test_tas_global_mean_shape(self, ds):
        gm = ds.variables["tas_global_mean"]
        assert gm.shape == (12,), "Expected shape (12,), got {}".format(gm.shape)


# -------------------------------------------------------------------
# Data integrity
# -------------------------------------------------------------------
class TestDataIntegrity:
    def test_no_nan_in_valid_tas(self, ds):
        data = ds.variables["tas"][:]
        valid = _get_valid(data)
        assert len(valid) > 0, "No valid tas data"
        assert not np.any(np.isnan(valid)), "Found NaN in unmasked tas data"

    def test_no_nan_in_valid_wsp(self, ds):
        data = ds.variables["wsp"][:]
        valid = _get_valid(data)
        assert len(valid) > 0, "No valid wsp data"
        assert not np.any(np.isnan(valid)), "Found NaN in unmasked wsp data"

    def test_fill_value_not_nan(self, ds):
        for vname in ["tas", "uas", "vas", "wsp"]:
            if vname not in ds.variables:
                continue
            var = ds.variables[vname]
            if hasattr(var, "_FillValue"):
                fv = float(var._FillValue)
                assert not math.isnan(fv), "{} still has NaN _FillValue".format(vname)

    def test_temperature_in_kelvin(self, ds):
        valid = _get_valid(ds.variables["tas"][:])
        assert len(valid) > 0, "No valid temperature data"
        assert np.all(valid > 200), "Temperature too low ({:.1f}); expected Kelvin".format(
            float(valid.min())
        )
        assert np.all(valid < 350), "Temperature too high ({:.1f})".format(
            float(valid.max())
        )

    def test_temperature_range(self, ds):
        valid = _get_valid(ds.variables["tas"][:])
        assert float(valid.min()) > 250, "Min temperature {:.1f} K too low".format(
            float(valid.min())
        )
        assert float(valid.max()) < 320, "Max temperature {:.1f} K too high".format(
            float(valid.max())
        )


# -------------------------------------------------------------------
# Wind speed
# -------------------------------------------------------------------
class TestWindSpeed:
    def test_wsp_equals_vector_magnitude(self, ds):
        uas = ds.variables["uas"][:]
        vas = ds.variables["vas"][:]
        wsp = ds.variables["wsp"][:]

        if hasattr(uas, "compressed"):
            # Build combined valid mask
            u_mask = np.ma.getmaskarray(uas)
            v_mask = np.ma.getmaskarray(vas)
            w_mask = np.ma.getmaskarray(wsp)
            valid = ~u_mask & ~v_mask & ~w_mask
            expected = np.sqrt(uas.data[valid] ** 2 + vas.data[valid] ** 2)
            actual = wsp.data[valid]
        else:
            valid = ~np.isnan(uas) & ~np.isnan(vas) & ~np.isnan(wsp)
            expected = np.sqrt(uas[valid] ** 2 + vas[valid] ** 2)
            actual = wsp[valid]

        np.testing.assert_allclose(
            actual, expected, rtol=1e-3, err_msg="wsp != sqrt(uas^2 + vas^2)"
        )

    def test_wsp_non_negative(self, ds):
        valid = _get_valid(ds.variables["wsp"][:])
        assert np.all(valid >= 0), "Wind speed has negative values"


# -------------------------------------------------------------------
# Corrupt record handling
# -------------------------------------------------------------------
class TestCorruptRecordHandling:
    def test_august_climatology_excludes_corrupt_year(self, ds):
        """August 2011 was all-NaN.

        Year offsets: 2010=0.0, 2011=1.0, 2012=0.5
        Non-August months: mean offset = (0+1+0.5)/3 = 0.5
        August (2011 excluded): mean offset = (0+0.5)/2 = 0.25

        Verify the August climatology reflects the 2-year average.
        """
        tas = ds.variables["tas"][:]
        # Get mask as array (handles scalar False case)
        mask = np.ma.getmaskarray(tas) if hasattr(tas, "mask") else np.isnan(np.asarray(tas))
        values = np.where(mask, np.nan, np.asarray(tas.data if hasattr(tas, "data") else tas))

        # Find a grid cell valid in all 12 months
        all_valid = ~np.any(mask, axis=0)
        if not np.any(all_valid):
            pytest.skip("No grid cell valid in all 12 months")

        iy, ix = np.where(all_valid)
        y, x = int(iy[0]), int(ix[0])

        lat_name = _get_lat_name(ds)
        lat_val = float(ds.variables[lat_name][y])
        lat_r = math.radians(lat_val)

        aug_idx = 7
        jan_idx = 0

        base_aug = 273.15 + 15.0 + 20.0 * math.cos(lat_r) + 5.0 * math.cos(
            2.0 * math.pi * aug_idx / 12.0
        )
        base_jan = 273.15 + 15.0 + 20.0 * math.cos(lat_r) + 5.0 * math.cos(
            2.0 * math.pi * jan_idx / 12.0
        )

        aug_val = float(values[aug_idx, y, x])
        jan_val = float(values[jan_idx, y, x])

        aug_offset = aug_val - base_aug
        jan_offset = jan_val - base_jan

        assert abs(aug_offset - 0.25) < 0.2, (
            "August offset {:.3f} not near 0.25 — "
            "corrupt 2011 record may not have been excluded".format(aug_offset)
        )
        assert abs(jan_offset - 0.50) < 0.2, (
            "January offset {:.3f} not near 0.50".format(jan_offset)
        )


# -------------------------------------------------------------------
# CF compliance
# -------------------------------------------------------------------
class TestCFCompliance:
    def test_tas_units_kelvin(self, ds):
        tas = ds.variables["tas"]
        assert hasattr(tas, "units"), "tas missing 'units' attribute"
        assert tas.units == "K", "tas units should be 'K', got '{}'".format(tas.units)

    def test_tas_standard_name(self, ds):
        tas = ds.variables["tas"]
        assert hasattr(tas, "standard_name"), "tas missing 'standard_name'"
        assert tas.standard_name == "air_temperature"

    def test_wsp_units(self, ds):
        wsp = ds.variables["wsp"]
        assert hasattr(wsp, "units"), "wsp missing 'units'"
        assert wsp.units == "m s-1", "wsp units should be 'm s-1', got '{}'".format(
            wsp.units
        )

    def test_wsp_long_name(self, ds):
        wsp = ds.variables["wsp"]
        assert hasattr(wsp, "long_name"), "wsp missing 'long_name'"
        assert "ind" in wsp.long_name.lower(), (
            "wsp long_name should mention wind, got '{}'".format(wsp.long_name)
        )

    def test_tas_global_mean_units(self, ds):
        gm = ds.variables["tas_global_mean"]
        assert hasattr(gm, "units"), "tas_global_mean missing 'units'"
        assert gm.units == "K", "tas_global_mean units should be 'K', got '{}'".format(
            gm.units
        )

    def test_global_mean_reasonable(self, ds):
        gm = ds.variables["tas_global_mean"][:]
        valid = _get_valid(gm)
        assert len(valid) == 12, "Expected 12 global mean values, got {}".format(
            len(valid)
        )
        assert np.all(valid > 275), "Global mean too low: {:.1f} K".format(
            float(valid.min())
        )
        assert np.all(valid < 315), "Global mean too high: {:.1f} K".format(
            float(valid.max())
        )
