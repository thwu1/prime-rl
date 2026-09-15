"""
Tests for MODIS MCD43A1 BRDF-to-Albedo pipeline.

Independently computes reference values using the correct RossThick-LiSparseReciprocal
kernel formulations and compares against the R pipeline output.
"""


import pytest
import csv
import math
import os

# ============================================================================
# Configuration (must match /app/config.json)
# ============================================================================
SZA_DEG = 30.0
OPTICAL_DEPTH = 0.20
FILL_VALUE = 32767
SCALE_FACTOR = 0.001
VALID_QUALITY = [0, 1]
OUTPUT_PATH = "/app/output/albedo_results.csv"

# ============================================================================
# Correct BSA polynomial coefficients (Lucht et al., 2000)
# ============================================================================
G0_ISO, G1_ISO, G2_ISO = 1.0, 0.0, 0.0
G0_VOL, G1_VOL, G2_VOL = -0.007574, -0.070987, 0.307588
G0_GEO, G1_GEO, G2_GEO = -1.284909, -0.166314, 0.041840

# Correct WSA weights
W_ISO = 1.0
W_VOL = 0.189184
W_GEO = -1.377622

# MODIS LiSparse-Reciprocal parameters
HB = 2.0
BR = 1.0

# Tolerances
ATOL_ALBEDO = 1e-5
ATOL_NBAR = 1e-4
ATOL_SCALE = 1e-6


# ============================================================================
# Reference computation functions
# ============================================================================

def ref_compute_bsa(f_iso, f_vol, f_geo, sza_deg):
    sza_rad = math.radians(sza_deg)
    sza2 = sza_rad ** 2
    sza3 = sza_rad ** 3
    return (f_iso * (G0_ISO + G1_ISO * sza2 + G2_ISO * sza3) +
            f_vol * (G0_VOL + G1_VOL * sza2 + G2_VOL * sza3) +
            f_geo * (G0_GEO + G1_GEO * sza2 + G2_GEO * sza3))


def ref_compute_wsa(f_iso, f_vol, f_geo):
    return f_iso * W_ISO + f_vol * W_VOL + f_geo * W_GEO


def ref_diffuse_fraction(tau, sza_deg, band):
    mu = math.cos(math.radians(sza_deg))
    coeff = {'vis': 3.14, 'nir': 1.75, 'shortwave': 2.44}[band]
    return 1.0 - math.exp(-tau * coeff / mu)


def ref_compute_bluesky(wsa, bsa, skyl):
    return wsa * skyl + bsa * (1.0 - skyl)


def ref_ross_thick_kernel(vza_rad, sza_rad, raa_rad):
    """RossThick volumetric scattering kernel (no hot spot)."""
    cos_vza = math.cos(vza_rad)
    cos_sza = math.cos(sza_rad)
    sin_vza = math.sin(vza_rad)
    sin_sza = math.sin(sza_rad)
    cos_raa = math.cos(raa_rad)

    cos_xi = cos_vza * cos_sza + sin_vza * sin_sza * cos_raa
    cos_xi = max(-1.0, min(1.0, cos_xi))
    xi = math.acos(cos_xi)
    sin_xi = math.sin(xi)

    ross_element = (math.pi / 2.0 - xi) * cos_xi + sin_xi
    denom = cos_vza + cos_sza
    if abs(denom) < 1e-20:
        denom = 1e-20
    return ross_element / denom


def ref_li_sparse_recip_kernel(vza_rad, sza_rad, raa_rad):
    """LiSparse-Reciprocal geometric-optical kernel (MODIS: HB=2, BR=1)."""
    NEARLY_ZERO = 1e-20

    tan_vza = math.tan(vza_rad) if abs(vza_rad) < math.pi / 2.0 - 1e-10 else 1e10
    tan_sza = math.tan(sza_rad) if abs(sza_rad) < math.pi / 2.0 - 1e-10 else 1e10

    # B/R transformation for ellipse crown shape
    tan_vza_p = BR * tan_vza
    tan_sza_p = BR * tan_sza

    vza_p = math.atan(abs(tan_vza_p))
    sza_p = math.atan(abs(tan_sza_p))

    cos_vza_p = math.cos(vza_p)
    sin_vza_p = math.sin(vza_p)
    cos_sza_p = math.cos(sza_p)
    sin_sza_p = math.sin(sza_p)
    cos_raa = math.cos(raa_rad)
    sin_raa = math.sin(raa_rad)

    if cos_vza_p == 0:
        cos_vza_p = NEARLY_ZERO
    if cos_sza_p == 0:
        cos_sza_p = NEARLY_ZERO

    # Phase angle in transformed coordinates
    cos_xi_p = cos_vza_p * cos_sza_p + sin_vza_p * sin_sza_p * cos_raa
    cos_xi_p = max(-1.0, min(1.0, cos_xi_p))

    # Distance
    D_sq = tan_vza_p ** 2 + tan_sza_p ** 2 - 2.0 * tan_vza_p * tan_sza_p * cos_raa
    if D_sq < 0:
        D_sq = 0.0
    D = math.sqrt(D_sq)

    # Overlap (H/B ratio transformation)
    temp = 1.0 / cos_vza_p + 1.0 / cos_sza_p

    cost_arg = HB * math.sqrt(D ** 2 + tan_vza_p ** 2 * tan_sza_p ** 2 * sin_raa ** 2) / temp
    cost_arg = max(-1.0, min(1.0, cost_arg))

    t_var = math.acos(cost_arg)
    sint = math.sin(t_var)
    overlap = (1.0 / math.pi) * (t_var - sint * cost_arg) * temp
    if overlap < 0:
        overlap = 0.0

    # LiSparse Reciprocal formulation
    Li = overlap - temp + 0.5 * (1.0 + cos_xi_p) / cos_vza_p / cos_sza_p
    return Li


def ref_compute_nbar(f_iso, f_vol, f_geo, sza_deg):
    """NBAR via full kernel evaluation at nadir view."""
    sza_rad = math.radians(sza_deg)

    # Evaluate kernels at (VZA=0, SZA=sza, RAA=0)
    k_vol = ref_ross_thick_kernel(0.0, sza_rad, 0.0)
    k_geo = ref_li_sparse_recip_kernel(0.0, sza_rad, 0.0)

    # Evaluate kernels at nadir-nadir for normalization
    k_vol_0 = ref_ross_thick_kernel(0.0, 0.0, 0.0)
    k_geo_0 = ref_li_sparse_recip_kernel(0.0, 0.0, 0.0)

    # Normalized kernels (zero at nadir-nadir)
    k_vol_norm = k_vol - k_vol_0
    k_geo_norm = k_geo - k_geo_0

    # K_iso = 1.0 everywhere, K_iso_norm = 1.0 - 1.0 = 0, so f_iso * 1.0
    return f_iso + f_vol * k_vol_norm + f_geo * k_geo_norm


# ============================================================================
# Input data for reference computation
# ============================================================================

INPUT_ROWS = [
    {"pixel_id": "P001", "band": "vis", "lat": 40.0, "lon": -105.0, "date": "2020-06-15", "f_iso_raw": 350, "f_vol_raw": 200, "f_geo_raw": 50, "quality": 0},
    {"pixel_id": "P001", "band": "nir", "lat": 40.0, "lon": -105.0, "date": "2020-06-15", "f_iso_raw": 480, "f_vol_raw": 150, "f_geo_raw": 30, "quality": 0},
    {"pixel_id": "P001", "band": "shortwave", "lat": 40.0, "lon": -105.0, "date": "2020-06-15", "f_iso_raw": 280, "f_vol_raw": 180, "f_geo_raw": 45, "quality": 0},
    {"pixel_id": "P002", "band": "vis", "lat": 35.0, "lon": -90.0, "date": "2020-06-15", "f_iso_raw": 120, "f_vol_raw": 60, "f_geo_raw": 15, "quality": 0},
    {"pixel_id": "P002", "band": "nir", "lat": 35.0, "lon": -90.0, "date": "2020-06-15", "f_iso_raw": 250, "f_vol_raw": 80, "f_geo_raw": 20, "quality": 1},
    {"pixel_id": "P002", "band": "shortwave", "lat": 35.0, "lon": -90.0, "date": "2020-06-15", "f_iso_raw": 160, "f_vol_raw": 70, "f_geo_raw": 25, "quality": 0},
    # P003 vis: fill values -> excluded
    {"pixel_id": "P003", "band": "nir", "lat": 50.0, "lon": -120.0, "date": "2020-06-15", "f_iso_raw": 500, "f_vol_raw": 100, "f_geo_raw": 25, "quality": 0},
    {"pixel_id": "P003", "band": "shortwave", "lat": 50.0, "lon": -120.0, "date": "2020-06-15", "f_iso_raw": 400, "f_vol_raw": 120, "f_geo_raw": 35, "quality": 0},
    # P004 vis: quality=2 -> excluded
    {"pixel_id": "P004", "band": "nir", "lat": 25.0, "lon": -80.0, "date": "2020-06-15", "f_iso_raw": 320, "f_vol_raw": 110, "f_geo_raw": 45, "quality": 0},
    # P004 shortwave: quality=3 -> excluded
    {"pixel_id": "P005", "band": "vis", "lat": 45.0, "lon": -100.0, "date": "2020-12-15", "f_iso_raw": 150, "f_vol_raw": 80, "f_geo_raw": 20, "quality": 0},
    {"pixel_id": "P005", "band": "nir", "lat": 45.0, "lon": -100.0, "date": "2020-12-15", "f_iso_raw": 380, "f_vol_raw": 130, "f_geo_raw": 35, "quality": 0},
    {"pixel_id": "P005", "band": "shortwave", "lat": 45.0, "lon": -100.0, "date": "2020-12-15", "f_iso_raw": 220, "f_vol_raw": 110, "f_geo_raw": 28, "quality": 0},
    {"pixel_id": "P006", "band": "vis", "lat": 60.0, "lon": -150.0, "date": "2020-06-15", "f_iso_raw": 100, "f_vol_raw": 50, "f_geo_raw": 10, "quality": 0},
    {"pixel_id": "P006", "band": "nir", "lat": 60.0, "lon": -150.0, "date": "2020-06-15", "f_iso_raw": 450, "f_vol_raw": 160, "f_geo_raw": 40, "quality": 0},
    {"pixel_id": "P006", "band": "shortwave", "lat": 60.0, "lon": -150.0, "date": "2020-06-15", "f_iso_raw": 320, "f_vol_raw": 140, "f_geo_raw": 32, "quality": 1},
    {"pixel_id": "P007", "band": "vis", "lat": 10.0, "lon": -60.0, "date": "2020-06-15", "f_iso_raw": 80, "f_vol_raw": 40, "f_geo_raw": 8, "quality": 0},
    {"pixel_id": "P007", "band": "nir", "lat": 10.0, "lon": -60.0, "date": "2020-06-15", "f_iso_raw": 550, "f_vol_raw": 90, "f_geo_raw": 15, "quality": 0},
    {"pixel_id": "P007", "band": "shortwave", "lat": 10.0, "lon": -60.0, "date": "2020-06-15", "f_iso_raw": 270, "f_vol_raw": 65, "f_geo_raw": 18, "quality": 0},
    {"pixel_id": "P008", "band": "vis", "lat": 55.0, "lon": -110.0, "date": "2020-06-15", "f_iso_raw": 180, "f_vol_raw": 95, "f_geo_raw": 25, "quality": 0},
    {"pixel_id": "P008", "band": "nir", "lat": 55.0, "lon": -110.0, "date": "2020-06-15", "f_iso_raw": 410, "f_vol_raw": 140, "f_geo_raw": 38, "quality": 0},
    {"pixel_id": "P008", "band": "shortwave", "lat": 55.0, "lon": -110.0, "date": "2020-06-15", "f_iso_raw": 290, "f_vol_raw": 115, "f_geo_raw": 30, "quality": 0},
]


def compute_reference_values():
    """Compute all expected output values from input data."""
    ref = {}
    for row in INPUT_ROWS:
        f_iso = row["f_iso_raw"] * SCALE_FACTOR
        f_vol = row["f_vol_raw"] * SCALE_FACTOR
        f_geo = row["f_geo_raw"] * SCALE_FACTOR
        band = row["band"]

        bsa = ref_compute_bsa(f_iso, f_vol, f_geo, SZA_DEG)
        wsa = ref_compute_wsa(f_iso, f_vol, f_geo)
        skyl = ref_diffuse_fraction(OPTICAL_DEPTH, SZA_DEG, band)
        bluesky = ref_compute_bluesky(wsa, bsa, skyl)
        nbar = ref_compute_nbar(f_iso, f_vol, f_geo, SZA_DEG)

        key = (row["pixel_id"], row["band"])
        ref[key] = {
            "f_iso": f_iso,
            "f_vol": f_vol,
            "f_geo": f_geo,
            "bsa": bsa,
            "wsa": wsa,
            "bluesky": bluesky,
            "nbar": nbar,
        }
    return ref


# ============================================================================
# Helper to load output
# ============================================================================

def load_output():
    assert os.path.exists(OUTPUT_PATH), f"Output file {OUTPUT_PATH} does not exist. Run the pipeline first."
    with open(OUTPUT_PATH, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows


# ============================================================================
# Tests
# ============================================================================

class TestDataFiltering:

    def test_output_exists(self):
        assert os.path.exists(OUTPUT_PATH), "Output CSV not found"

    def test_row_count(self):
        rows = load_output()
        assert len(rows) == 21, f"Expected 21 valid observations, got {len(rows)}"

    def test_fill_values_excluded(self):
        rows = load_output()
        for row in rows:
            assert not (row["pixel_id"] == "P003" and row["band"] == "vis"), \
                "P003 vis should be excluded (fill values = 32767)"

    def test_bad_quality_vis_excluded(self):
        rows = load_output()
        for row in rows:
            assert not (row["pixel_id"] == "P004" and row["band"] == "vis"), \
                "P004 vis should be excluded (quality=2 not in valid_quality)"

    def test_bad_quality_sw_excluded(self):
        rows = load_output()
        for row in rows:
            assert not (row["pixel_id"] == "P004" and row["band"] == "shortwave"), \
                "P004 shortwave should be excluded (quality=3 not in valid_quality)"

    def test_marginal_quality_retained(self):
        rows = load_output()
        found_p002_nir = any(r["pixel_id"] == "P002" and r["band"] == "nir" for r in rows)
        found_p006_sw = any(r["pixel_id"] == "P006" and r["band"] == "shortwave" for r in rows)
        assert found_p002_nir, "P002 nir (quality=1) should be retained"
        assert found_p006_sw, "P006 shortwave (quality=1) should be retained"

    def test_expected_pixels_present(self):
        rows = load_output()
        expected_keys = set((r["pixel_id"], r["band"]) for r in INPUT_ROWS)
        actual_keys = set((r["pixel_id"], r["band"]) for r in rows)
        assert expected_keys == actual_keys, \
            f"Mismatch in retained observations.\nMissing: {expected_keys - actual_keys}\nExtra: {actual_keys - expected_keys}"


class TestScaleFactor:

    def test_f_iso_scaled(self):
        rows = load_output()
        ref = compute_reference_values()
        for row in rows:
            key = (row["pixel_id"], row["band"])
            assert abs(float(row["f_iso"]) - ref[key]["f_iso"]) < ATOL_SCALE, \
                f"{key}: f_iso should be {ref[key]['f_iso']}, got {row['f_iso']}"

    def test_f_vol_scaled(self):
        rows = load_output()
        ref = compute_reference_values()
        for row in rows:
            key = (row["pixel_id"], row["band"])
            assert abs(float(row["f_vol"]) - ref[key]["f_vol"]) < ATOL_SCALE, \
                f"{key}: f_vol should be {ref[key]['f_vol']}, got {row['f_vol']}"

    def test_f_geo_scaled(self):
        rows = load_output()
        ref = compute_reference_values()
        for row in rows:
            key = (row["pixel_id"], row["band"])
            assert abs(float(row["f_geo"]) - ref[key]["f_geo"]) < ATOL_SCALE, \
                f"{key}: f_geo should be {ref[key]['f_geo']}, got {row['f_geo']}"


class TestBSA:

    def test_bsa_all_rows(self):
        rows = load_output()
        ref = compute_reference_values()
        for row in rows:
            key = (row["pixel_id"], row["band"])
            actual = float(row["bsa"])
            expected = ref[key]["bsa"]
            assert abs(actual - expected) < ATOL_ALBEDO, \
                f"{key}: BSA expected {expected:.8f}, got {actual:.8f}"

    def test_bsa_physically_valid(self):
        rows = load_output()
        for row in rows:
            bsa = float(row["bsa"])
            assert -0.1 < bsa < 1.0, \
                f"({row['pixel_id']}, {row['band']}): BSA={bsa} outside physically valid range"


class TestWSA:

    def test_wsa_all_rows(self):
        rows = load_output()
        ref = compute_reference_values()
        for row in rows:
            key = (row["pixel_id"], row["band"])
            actual = float(row["wsa"])
            expected = ref[key]["wsa"]
            assert abs(actual - expected) < ATOL_ALBEDO, \
                f"{key}: WSA expected {expected:.8f}, got {actual:.8f}"


class TestBlueSky:

    def test_bluesky_all_rows(self):
        rows = load_output()
        ref = compute_reference_values()
        for row in rows:
            key = (row["pixel_id"], row["band"])
            actual = float(row["bluesky"])
            expected = ref[key]["bluesky"]
            assert abs(actual - expected) < ATOL_ALBEDO, \
                f"{key}: Blue-sky expected {expected:.8f}, got {actual:.8f}"

    def test_bluesky_between_bsa_and_wsa(self):
        """Blue-sky albedo should be between BSA and WSA (or very close)."""
        rows = load_output()
        for row in rows:
            bsa = float(row["bsa"])
            wsa = float(row["wsa"])
            bluesky = float(row["bluesky"])
            lo = min(bsa, wsa) - 1e-6
            hi = max(bsa, wsa) + 1e-6
            assert lo <= bluesky <= hi, \
                f"({row['pixel_id']}, {row['band']}): bluesky={bluesky} not between BSA={bsa} and WSA={wsa}"


class TestNBAR:

    def test_nbar_not_na(self):
        rows = load_output()
        for row in rows:
            val = row["nbar"].strip()
            assert val.upper() != "NA" and val != "", \
                f"({row['pixel_id']}, {row['band']}): NBAR is NA or empty"

    def test_nbar_all_rows(self):
        rows = load_output()
        ref = compute_reference_values()
        for row in rows:
            key = (row["pixel_id"], row["band"])
            actual = float(row["nbar"])
            expected = ref[key]["nbar"]
            assert abs(actual - expected) < ATOL_NBAR, \
                f"{key}: NBAR expected {expected:.8f}, got {actual:.8f}"

    def test_nbar_physically_valid(self):
        rows = load_output()
        for row in rows:
            nbar = float(row["nbar"])
            assert -0.1 < nbar < 1.0, \
                f"({row['pixel_id']}, {row['band']}): NBAR={nbar} outside valid range"


class TestOutputFormat:

    def test_required_columns(self):
        rows = load_output()
        required = {"pixel_id", "band", "lat", "lon", "date",
                     "f_iso", "f_vol", "f_geo", "bsa", "wsa", "bluesky", "nbar"}
        actual = set(rows[0].keys())
        missing = required - actual
        assert not missing, f"Missing columns: {missing}"
