"""Tests for CMOR-compliant output of the SYNOBS CMORizer.

Verifies direct variable conversions, physically derived quantities
(specific humidity and sea-level pressure), quality control masking,
coordinate transformations, metadata compliance, and data types.
"""

import os

import netCDF4 as nc
import numpy as np
import pytest

OUTPUT_DIR = "/app/output"
RAW_FILE = "/app/raw_data/SYNOBS_monthly_2000-2014.nc"

EXPECTED_FILES = {
    "tas": "OBS_SYNOBS_ground_v1_Amon_tas_200001-201412.nc",
    "pr": "OBS_SYNOBS_ground_v1_Amon_pr_200001-201412.nc",
    "psl": "OBS_SYNOBS_ground_v1_Amon_psl_200001-201412.nc",
    "huss": "OBS_SYNOBS_ground_v1_Amon_huss_200001-201412.nc",
}

ALL_VARS = ["tas", "pr", "psl", "huss"]


def _load_raw_transformed():
    """Load raw data and apply coordinate transforms (lon shift, lat flip).

    Returns dict with transformed arrays and the QC mask.
    """
    raw = nc.Dataset(RAW_FILE)
    t2m = raw.variables["t2m"][:].copy()
    td2m = raw.variables["td2m"][:].copy()
    tp = raw.variables["tp"][:].copy()
    sp = raw.variables["sp"][:].copy()
    orog = raw.variables["orog"][:].copy()
    qc = raw.variables["qc_flag"][:].copy()
    lon_raw = raw.variables["longitude"][:].copy()
    lat_raw = raw.variables["latitude"][:].copy()
    raw.close()

    # Longitude: -180..180 -> 0..360 with reordering
    new_lon = np.where(lon_raw < 0, lon_raw + 360.0, lon_raw)
    sort_idx = np.argsort(new_lon)

    # Reorder along lon axis
    t2m = t2m[:, :, sort_idx]
    td2m = td2m[:, :, sort_idx]
    tp = tp[:, :, sort_idx]
    sp = sp[:, :, sort_idx]
    orog = orog[:, sort_idx]
    qc = qc[:, :, sort_idx]

    # Flip latitude to ascending
    t2m = t2m[:, ::-1, :]
    td2m = td2m[:, ::-1, :]
    tp = tp[:, ::-1, :]
    sp = sp[:, ::-1, :]
    orog = orog[::-1, :]
    qc = qc[:, ::-1, :]

    bad_mask = qc != 0

    return {
        "t2m": t2m, "td2m": td2m, "tp": tp, "sp": sp,
        "orog": orog, "qc_mask": bad_mask,
    }


# ---------- File existence ----------

class TestOutputFilesExist:
    @pytest.mark.parametrize("var", ALL_VARS)
    def test_output_file_exists(self, var):
        path = os.path.join(OUTPUT_DIR, EXPECTED_FILES[var])
        assert os.path.exists(path), f"Missing output file: {EXPECTED_FILES[var]}"


# ---------- Variable metadata ----------

class TestVariableMetadata:
    def test_tas_metadata(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        assert "tas" in ds.variables
        v = ds.variables["tas"]
        assert v.units == "K"
        assert v.standard_name == "air_temperature"
        assert v.long_name == "Near-Surface Air Temperature"
        ds.close()

    def test_pr_metadata(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["pr"]))
        assert "pr" in ds.variables
        v = ds.variables["pr"]
        assert v.units == "kg m-2 s-1"
        assert v.standard_name == "precipitation_flux"
        assert v.long_name == "Precipitation"
        ds.close()

    def test_psl_metadata(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["psl"]))
        assert "psl" in ds.variables
        v = ds.variables["psl"]
        assert v.units == "Pa"
        assert v.standard_name == "air_pressure_at_mean_sea_level"
        assert v.long_name == "Sea Level Pressure"
        ds.close()

    def test_huss_metadata(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["huss"]))
        assert "huss" in ds.variables
        v = ds.variables["huss"]
        assert v.units == "1"
        assert v.standard_name == "specific_humidity"
        assert v.long_name == "Near-Surface Specific Humidity"
        ds.close()


# ---------- Coordinate system ----------

class TestCoordinateSystem:
    def _open(self, var="tas"):
        return nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES[var]))

    def test_longitude_range_0_360(self):
        ds = self._open()
        lon = ds.variables["lon"][:]
        assert np.all(lon >= 0) and np.all(lon <= 360)
        ds.close()

    def test_longitude_ascending(self):
        ds = self._open()
        lon = ds.variables["lon"][:]
        assert np.all(np.diff(lon) > 0)
        ds.close()

    def test_latitude_ascending(self):
        ds = self._open()
        lat = ds.variables["lat"][:]
        assert lat[0] < lat[-1]
        assert np.all(np.diff(lat) > 0)
        ds.close()

    def test_time_units_reference_1950(self):
        ds = self._open()
        t = ds.variables["time"]
        assert "days since" in t.units
        assert "1950" in t.units
        ds.close()

    def test_time_calendar_gregorian(self):
        ds = self._open()
        t = ds.variables["time"]
        cal = getattr(t, "calendar", "").lower()
        assert cal in ("gregorian", "standard")
        ds.close()

    def test_longitude_metadata(self):
        ds = self._open()
        lon = ds.variables["lon"]
        assert lon.standard_name == "longitude"
        assert "degree" in lon.units.lower()
        ds.close()

    def test_latitude_metadata(self):
        ds = self._open()
        lat = ds.variables["lat"]
        assert lat.standard_name == "latitude"
        assert "degree" in lat.units.lower()
        ds.close()


# ---------- Coordinate bounds ----------

class TestCoordinateBounds:
    def _open(self):
        return nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))

    def _get_bnds(self, ds, name):
        for suffix in ("_bnds", "_bounds"):
            if name + suffix in ds.variables:
                return ds.variables[name + suffix]
        return None

    def test_time_bounds_exist(self):
        ds = self._open()
        assert self._get_bnds(ds, "time") is not None
        ds.close()

    def test_lat_bounds_exist(self):
        ds = self._open()
        assert self._get_bnds(ds, "lat") is not None
        ds.close()

    def test_lon_bounds_exist(self):
        ds = self._open()
        assert self._get_bnds(ds, "lon") is not None
        ds.close()

    def test_time_bounds_shape(self):
        ds = self._open()
        bnds = self._get_bnds(ds, "time")
        assert bnds.shape == (180, 2)
        ds.close()

    def test_lat_bounds_shape(self):
        ds = self._open()
        bnds = self._get_bnds(ds, "lat")
        assert bnds.shape == (36, 2)
        ds.close()

    def test_lon_bounds_shape(self):
        ds = self._open()
        bnds = self._get_bnds(ds, "lon")
        assert bnds.shape == (72, 2)
        ds.close()


# ---------- Scalar coordinates ----------

class TestScalarCoordinates:
    def test_tas_height_2m(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        assert "height" in ds.variables
        h = ds.variables["height"]
        assert abs(float(h[...]) - 2.0) < 1e-6
        assert h.units == "m"
        assert h.standard_name == "height"
        ds.close()

    def test_huss_height_2m(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["huss"]))
        assert "height" in ds.variables
        h = ds.variables["height"]
        assert abs(float(h[...]) - 2.0) < 1e-6
        assert h.units == "m"
        assert h.standard_name == "height"
        ds.close()


# ---------- Quality control masking ----------

class TestQualityControl:
    def test_masked_count_matches_qc_flags(self):
        """Total masked count in output must match non-zero QC flag count."""
        d = _load_raw_transformed()
        expected_masked = int(np.count_nonzero(d["qc_mask"]))

        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        tas = ds.variables["tas"][:]
        ds.close()

        if isinstance(tas, np.ma.MaskedArray):
            actual = int(np.ma.count_masked(tas))
        else:
            actual = int(np.count_nonzero(
                np.isnan(tas) | (np.abs(tas) > 1e19)
            ))
        assert actual == expected_masked, \
            f"Masked count mismatch: expected {expected_masked}, got {actual}"

    def test_clean_points_have_valid_data(self):
        """Points with qc_flag==0 must contain valid (non-masked) data."""
        d = _load_raw_transformed()
        clean = ~d["qc_mask"]

        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        tas = ds.variables["tas"][:]
        ds.close()

        if isinstance(tas, np.ma.MaskedArray):
            assert not np.any(tas.mask[clean]), \
                "Some clean (unflagged) data points are masked"
        else:
            assert not np.any(np.isnan(tas[clean])), \
                "Some clean (unflagged) data points are NaN"

    def test_qc_masking_applied_to_all_variables(self):
        """All output variables must have consistent masking."""
        d = _load_raw_transformed()
        expected = int(np.count_nonzero(d["qc_mask"]))

        for var in ALL_VARS:
            ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES[var]))
            data = ds.variables[var][:]
            ds.close()

            if isinstance(data, np.ma.MaskedArray):
                actual = int(np.ma.count_masked(data))
            else:
                actual = int(np.count_nonzero(
                    np.isnan(data) | (np.abs(data) > 1e19)
                ))
            assert actual == expected, \
                f"{var}: masked count {actual} != expected {expected}"


# ---------- Direct conversions ----------

class TestDirectConversions:
    def test_tas_celsius_to_kelvin(self):
        d = _load_raw_transformed()
        expected = (d["t2m"] + 273.15).astype(np.float32)
        clean = ~d["qc_mask"]

        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        tas = ds.variables["tas"][:]
        ds.close()
        if isinstance(tas, np.ma.MaskedArray):
            tas = tas.data

        np.testing.assert_allclose(
            tas[clean], expected[clean], rtol=1e-3,
            err_msg="Temperature conversion (degC -> K) incorrect"
        )

    def test_pr_mmday_to_kgm2s(self):
        d = _load_raw_transformed()
        expected = (d["tp"] / 86400.0).astype(np.float32)
        clean = ~d["qc_mask"]

        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["pr"]))
        pr = ds.variables["pr"][:]
        ds.close()
        if isinstance(pr, np.ma.MaskedArray):
            pr = pr.data

        np.testing.assert_allclose(
            pr[clean], expected[clean], rtol=1e-3,
            err_msg="Precipitation conversion (mm/day -> kg m-2 s-1) incorrect"
        )

    def test_precipitation_nonnegative(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["pr"]))
        pr = ds.variables["pr"][:]
        ds.close()
        if isinstance(pr, np.ma.MaskedArray):
            pr = pr.compressed()
        assert np.all(pr >= 0), "Precipitation contains negative values"


# ---------- Derived variable: huss ----------

class TestDerivedHuss:
    def test_huss_values_magnus_formula(self):
        """Verify huss computed from dewpoint using saturation vapor pressure."""
        d = _load_raw_transformed()
        td = d["td2m"]
        sp = d["sp"]
        clean = ~d["qc_mask"]

        # Magnus/Tetens formula for saturation vapor pressure at dewpoint
        e = 6.112 * np.exp(17.67 * td / (td + 243.5))  # hPa
        # Specific humidity from vapor pressure and total pressure
        huss_expected = (0.622 * e / (sp - 0.378 * e)).astype(np.float32)

        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["huss"]))
        huss = ds.variables["huss"][:]
        ds.close()
        if isinstance(huss, np.ma.MaskedArray):
            huss = huss.data

        np.testing.assert_allclose(
            huss[clean], huss_expected[clean], rtol=0.02,
            err_msg="Specific humidity does not match Magnus formula derivation"
        )

    def test_huss_positive(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["huss"]))
        huss = ds.variables["huss"][:]
        ds.close()
        if isinstance(huss, np.ma.MaskedArray):
            huss = huss.compressed()
        assert np.all(huss > 0), "Specific humidity must be positive"

    def test_huss_physical_range(self):
        """Specific humidity should be between 0 and 0.04 kg/kg."""
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["huss"]))
        huss = ds.variables["huss"][:]
        ds.close()
        if isinstance(huss, np.ma.MaskedArray):
            huss = huss.compressed()
        assert np.all(huss < 0.04), "huss exceeds physical maximum"


# ---------- Derived variable: psl ----------

class TestDerivedPsl:
    def test_psl_barometric_reduction(self):
        """Verify psl reduced from surface pressure using barometric formula."""
        d = _load_raw_transformed()
        t2m = d["t2m"]
        sp = d["sp"]
        orog = d["orog"]
        clean = ~d["qc_mask"]

        g = 9.80665
        Rd = 287.05
        T_kelvin = t2m + 273.15
        orog_3d = orog[np.newaxis, :, :]

        # Barometric formula: psl = sp * exp(g*z / (Rd*T))
        psl_hpa = sp * np.exp(g * orog_3d / (Rd * T_kelvin))
        psl_expected = (psl_hpa * 100.0).astype(np.float32)  # hPa -> Pa

        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["psl"]))
        psl = ds.variables["psl"][:]
        ds.close()
        if isinstance(psl, np.ma.MaskedArray):
            psl = psl.data

        np.testing.assert_allclose(
            psl[clean], psl_expected[clean], rtol=0.02,
            err_msg="Sea-level pressure does not match barometric reduction"
        )

    def test_psl_physical_range(self):
        """Sea-level pressure should be 85000-115000 Pa."""
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["psl"]))
        psl = ds.variables["psl"][:]
        ds.close()
        if isinstance(psl, np.ma.MaskedArray):
            psl = psl.compressed()
        assert np.all(psl > 85000), "psl below 85000 Pa"
        assert np.all(psl < 115000), "psl above 115000 Pa"


# ---------- Data types ----------

class TestDataTypes:
    @pytest.mark.parametrize("var", ALL_VARS)
    def test_data_dtype_float32(self, var):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES[var]))
        dtype = ds.variables[var].dtype
        ds.close()
        assert dtype == np.float32, f"{var} dtype should be float32, got {dtype}"

    def test_coordinate_dtype_float64(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        for coord in ["lat", "lon"]:
            dtype = ds.variables[coord].dtype
            assert dtype == np.float64, f"{coord} dtype should be float64, got {dtype}"
        ds.close()


# ---------- Dimensions ----------

class TestDimensions:
    def test_time_length(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        assert len(ds.variables["time"]) == 180
        ds.close()

    def test_lat_length(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        assert len(ds.variables["lat"]) == 36
        ds.close()

    def test_lon_length(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        assert len(ds.variables["lon"]) == 72
        ds.close()

    @pytest.mark.parametrize("var", ALL_VARS)
    def test_data_shape(self, var):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES[var]))
        shape = ds.variables[var].shape
        ds.close()
        assert shape == (180, 36, 72), f"{var} shape {shape} != (180, 36, 72)"


# ---------- Global attributes ----------

class TestGlobalAttributes:
    def test_required_attributes_present(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        for attr in ["title", "source", "project_id", "version", "tier"]:
            assert hasattr(ds, attr), f"Missing global attribute: '{attr}'"
        ds.close()

    def test_project_id(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        assert ds.project_id == "OBS"
        ds.close()

    def test_version(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        assert ds.version == "v1"
        ds.close()

    def test_tier(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        assert str(ds.tier) == "2"
        ds.close()

    @pytest.mark.parametrize("var", ALL_VARS)
    def test_all_outputs_have_global_attrs(self, var):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES[var]))
        assert hasattr(ds, "project_id")
        assert hasattr(ds, "source")
        ds.close()


# ---------- Data integrity ----------

class TestDataIntegrity:
    def test_tas_range(self):
        ds = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        tas = ds.variables["tas"][:]
        ds.close()
        if isinstance(tas, np.ma.MaskedArray):
            tas = tas.compressed()
        assert np.all(tas > 180) and np.all(tas < 340)

    def test_data_count_preserved(self):
        raw = nc.Dataset(RAW_FILE)
        raw_size = raw.variables["t2m"][:].size
        raw.close()
        out = nc.Dataset(os.path.join(OUTPUT_DIR, EXPECTED_FILES["tas"]))
        out_size = out.variables["tas"][:].size
        out.close()
        assert raw_size == out_size
