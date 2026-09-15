"""
Tests for USGS Spectral Library mineral absorption analysis and mixture decomposition.

Verifies output files, absorption feature positions against known spectroscopy
literature values, continuum removal validity, and mixture identification.
"""


import json
import csv
import os
import pytest

OUTPUT_DIR = "/app/output"
CR_DIR = os.path.join(OUTPUT_DIR, "continuum_removed")

# Diagnostic absorption features from spectroscopy literature
# (Clark et al., 1990; Kokaly et al., 2017)
# Each entry: wavelength range (um) where a feature must be detected
DIAGNOSTIC_BANDS = {
    "Alunite": [
        {"min_wl": 1.40, "max_wl": 1.55, "min_depth": 0.02},   # OH stretch combination
        {"min_wl": 2.10, "max_wl": 2.22, "min_depth": 0.02},   # Al-OH bend
    ],
    "Calcite": [
        {"min_wl": 2.28, "max_wl": 2.38, "min_depth": 0.02},   # CO3 overtone
    ],
    "Kaolinite": [
        {"min_wl": 2.14, "max_wl": 2.24, "min_depth": 0.02},   # Al-OH doublet
    ],
    "Montmorillonite": [
        {"min_wl": 1.85, "max_wl": 1.97, "min_depth": 0.02},   # H2O combination
    ],
    "Muscovite": [
        {"min_wl": 2.17, "max_wl": 2.25, "min_depth": 0.02},   # Al-OH
    ],
}

MINERAL_NAMES = list(DIAGNOSTIC_BANDS.keys())


def find_key_for_mineral(d, mineral_name):
    """Find a key in dict that matches the mineral name (case-insensitive substring)."""
    target = mineral_name.lower()
    for key in d:
        if target in key.lower():
            return key
    # Fallback: strip separators
    target_clean = target.replace("_", "").replace("-", "").replace(" ", "")
    for key in d:
        key_clean = key.lower().replace("_", "").replace("-", "").replace(" ", "")
        if target_clean in key_clean:
            return key
    return None


def find_csv_for_mineral(directory, mineral_name):
    """Find a CSV file in directory whose name contains the mineral name."""
    target = mineral_name.lower()
    for fn in os.listdir(directory):
        if fn.lower().endswith(".csv") and target in fn.lower():
            return os.path.join(directory, fn)
    return None


# ---- absorption_features.json ----

class TestAbsorptionFeaturesFile:
    """Verify absorption_features.json exists and has valid structure."""

    @pytest.fixture(autouse=True)
    def load_features(self):
        path = os.path.join(OUTPUT_DIR, "absorption_features.json")
        assert os.path.exists(path), f"absorption_features.json not found at {path}"
        with open(path) as f:
            self.features = json.load(f)

    def test_all_five_minerals_present(self):
        for mineral in MINERAL_NAMES:
            key = find_key_for_mineral(self.features, mineral)
            assert key is not None, (
                f"'{mineral}' not found in absorption_features.json. "
                f"Keys present: {list(self.features.keys())}"
            )

    def test_features_have_required_fields(self):
        required = {"center_um", "depth", "fwhm_um", "area"}
        for mineral_key, feats in self.features.items():
            assert isinstance(feats, list), f"{mineral_key}: features should be a list"
            for i, feat in enumerate(feats):
                for field in required:
                    assert field in feat, (
                        f"{mineral_key} feature {i}: missing field '{field}'"
                    )
                    val = feat[field]
                    assert isinstance(val, (int, float)), (
                        f"{mineral_key} feature {i}: '{field}' should be numeric, "
                        f"got {type(val).__name__}"
                    )

    def test_feature_values_physically_reasonable(self):
        for mineral_key, feats in self.features.items():
            for feat in feats:
                assert 0.8 <= feat["center_um"] <= 2.6, (
                    f"{mineral_key}: center {feat['center_um']} outside 0.8-2.6 um"
                )
                assert 0 < feat["depth"] <= 1.0, (
                    f"{mineral_key}: depth {feat['depth']} outside (0, 1]"
                )
                assert 0 < feat["fwhm_um"] <= 1.0, (
                    f"{mineral_key}: FWHM {feat['fwhm_um']} outside (0, 1.0] um"
                )
                assert feat["area"] >= 0, (
                    f"{mineral_key}: area must be non-negative"
                )

    @pytest.mark.parametrize("mineral", MINERAL_NAMES)
    def test_diagnostic_absorption_bands(self, mineral):
        """Each mineral must show its known diagnostic absorption features."""
        key = find_key_for_mineral(self.features, mineral)
        assert key is not None, f"'{mineral}' not in output"
        feats = self.features[key]
        expected_bands = DIAGNOSTIC_BANDS[mineral]

        for band in expected_bands:
            found = any(
                band["min_wl"] <= f["center_um"] <= band["max_wl"]
                and f["depth"] >= band["min_depth"]
                for f in feats
            )
            assert found, (
                f"{mineral}: expected absorption feature in "
                f"{band['min_wl']}-{band['max_wl']} um "
                f"(depth >= {band['min_depth']}), not found. "
                f"Detected: {[(f['center_um'], f['depth']) for f in feats]}"
            )

    def test_alunite_has_multiple_features(self):
        key = find_key_for_mineral(self.features, "Alunite")
        assert key is not None
        sig = [f for f in self.features[key] if f["depth"] > 0.02]
        assert len(sig) >= 2, (
            f"Alunite should have >= 2 significant features, found {len(sig)}"
        )

    def test_each_mineral_has_at_least_one_feature(self):
        for mineral_key, feats in self.features.items():
            assert len(feats) >= 1, f"{mineral_key}: should have >= 1 feature"


# ---- continuum_removed/*.csv ----

class TestContinuumRemoved:
    """Verify continuum-removed spectra files."""

    def test_directory_exists(self):
        assert os.path.isdir(CR_DIR), f"{CR_DIR} directory not found"

    def test_at_least_five_csv_files(self):
        csv_files = [f for f in os.listdir(CR_DIR) if f.endswith(".csv")]
        assert len(csv_files) >= 5, (
            f"Expected >= 5 CR CSV files, got {len(csv_files)}: {csv_files}"
        )

    @pytest.mark.parametrize("mineral", MINERAL_NAMES)
    def test_mineral_csv_exists(self, mineral):
        """Each mineral should have a corresponding CR CSV file."""
        csv_path = find_csv_for_mineral(CR_DIR, mineral)
        assert csv_path is not None, (
            f"No CR CSV file found for {mineral}. "
            f"Files: {os.listdir(CR_DIR)}"
        )

    def test_csv_column_headers(self):
        for csv_file in os.listdir(CR_DIR):
            if not csv_file.endswith(".csv"):
                continue
            with open(os.path.join(CR_DIR, csv_file)) as f:
                header = next(csv.reader(f))
            assert len(header) == 2, f"{csv_file}: expected 2 columns, got {len(header)}"
            assert "wavelength" in header[0].lower(), (
                f"{csv_file}: first column should contain 'wavelength', got '{header[0]}'"
            )

    def test_csv_data_rows(self):
        for csv_file in os.listdir(CR_DIR):
            if not csv_file.endswith(".csv"):
                continue
            with open(os.path.join(CR_DIR, csv_file)) as f:
                reader = csv.reader(f)
                next(reader)  # skip header
                rows = [r for r in reader if len(r) >= 2]
            assert len(rows) > 100, (
                f"{csv_file}: expected > 100 data rows, got {len(rows)}"
            )

    def test_wavelength_range(self):
        for csv_file in os.listdir(CR_DIR):
            if not csv_file.endswith(".csv"):
                continue
            with open(os.path.join(CR_DIR, csv_file)) as f:
                reader = csv.reader(f)
                next(reader)
                wavelengths = [float(r[0]) for r in reader if len(r) >= 2]
            assert wavelengths, f"{csv_file}: no data rows"
            assert min(wavelengths) >= 0.95, (
                f"{csv_file}: min wavelength {min(wavelengths):.4f} below 0.95 um"
            )
            assert max(wavelengths) <= 2.55, (
                f"{csv_file}: max wavelength {max(wavelengths):.4f} above 2.55 um"
            )

    def test_cr_values_bounded(self):
        """Continuum-removed reflectance should be in [0, 1]."""
        for csv_file in os.listdir(CR_DIR):
            if not csv_file.endswith(".csv"):
                continue
            with open(os.path.join(CR_DIR, csv_file)) as f:
                reader = csv.reader(f)
                next(reader)
                cr_vals = [float(r[1]) for r in reader if len(r) >= 2]
            assert cr_vals, f"{csv_file}: no data"
            assert max(cr_vals) <= 1.05, (
                f"{csv_file}: max CR = {max(cr_vals):.4f}, exceeds 1.05"
            )
            assert min(cr_vals) >= -0.1, (
                f"{csv_file}: min CR = {min(cr_vals):.4f} is too negative"
            )

    def test_spectra_show_absorption(self):
        """At least some CR values should be well below 1, showing absorption."""
        for csv_file in os.listdir(CR_DIR):
            if not csv_file.endswith(".csv"):
                continue
            with open(os.path.join(CR_DIR, csv_file)) as f:
                reader = csv.reader(f)
                next(reader)
                cr_vals = [float(r[1]) for r in reader if len(r) >= 2]
            assert cr_vals, f"{csv_file}: no data"
            assert min(cr_vals) < 0.95, (
                f"{csv_file}: min CR = {min(cr_vals):.4f}, expected < 0.95 "
                f"(no absorption features detected)"
            )


# ---- mixture_identification.json ----

class TestMixtureIdentification:
    """Verify mixture identification results."""

    @pytest.fixture(autouse=True)
    def load_mixture(self):
        path = os.path.join(OUTPUT_DIR, "mixture_identification.json")
        assert os.path.exists(path), f"mixture_identification.json not found"
        with open(path) as f:
            self.mixture = json.load(f)

    def test_required_keys_present(self):
        for key in ("identified_minerals", "spectral_angles", "mixing_proportions"):
            assert key in self.mixture, f"Missing key '{key}'"

    def test_two_minerals_identified(self):
        ident = self.mixture["identified_minerals"]
        assert isinstance(ident, list), "identified_minerals should be a list"
        assert len(ident) == 2, f"Expected 2 identified minerals, got {len(ident)}"

    def test_kaolinite_identified(self):
        ident_lower = [m.lower() for m in self.mixture["identified_minerals"]]
        assert any("kaolinite" in m or "kaolin" in m for m in ident_lower), (
            f"Kaolinite not identified. Found: {self.mixture['identified_minerals']}"
        )

    def test_montmorillonite_identified(self):
        ident_lower = [m.lower() for m in self.mixture["identified_minerals"]]
        assert any("montmorillonite" in m or "mont" in m for m in ident_lower), (
            f"Montmorillonite not identified. Found: {self.mixture['identified_minerals']}"
        )

    def test_spectral_angles_for_all_minerals(self):
        angles = self.mixture["spectral_angles"]
        assert isinstance(angles, dict), "spectral_angles should be a dict"
        assert len(angles) >= 5, (
            f"Spectral angles for >= 5 minerals expected, got {len(angles)}: {list(angles.keys())}"
        )

    def test_spectral_angles_valid_range(self):
        for mineral, angle in self.mixture["spectral_angles"].items():
            assert isinstance(angle, (int, float)), (
                f"{mineral}: spectral angle should be numeric, got {type(angle).__name__}"
            )
            assert 0 <= angle <= 3.15, (
                f"{mineral}: spectral angle {angle} outside [0, pi]"
            )

    def test_kaolinite_has_smallest_or_near_smallest_angle(self):
        """Kaolinite (60% component) should be in top 2 by spectral angle."""
        angles = self.mixture["spectral_angles"]
        sorted_by_angle = sorted(angles.items(), key=lambda x: x[1])
        top2_keys = [m[0].lower() for m in sorted_by_angle[:2]]
        assert any("kaolinite" in k or "kaolin" in k for k in top2_keys), (
            f"Kaolinite not in top 2 by spectral angle. Ranking: "
            f"{[(m, round(a, 4)) for m, a in sorted_by_angle]}"
        )

    def test_proportions_structure(self):
        props = self.mixture["mixing_proportions"]
        assert isinstance(props, dict), "mixing_proportions should be a dict"
        assert len(props) == 2, f"Expected 2 proportion entries, got {len(props)}"
        for k, v in props.items():
            assert isinstance(v, (int, float)), (
                f"Proportion for {k} should be numeric, got {type(v).__name__}"
            )

    def test_proportions_sum_near_one(self):
        props = self.mixture["mixing_proportions"]
        total = sum(props.values())
        assert 0.8 <= total <= 1.2, (
            f"Proportions sum to {total:.4f}, expected near 1.0"
        )

    def test_dominant_component_proportion(self):
        """The dominant component (Kaolinite at 60%) should have higher proportion."""
        props = self.mixture["mixing_proportions"]
        kao_prop = None
        for key, val in props.items():
            if "kaolinite" in key.lower() or "kaolin" in key.lower():
                kao_prop = val
                break
        if kao_prop is not None:
            assert 0.35 <= kao_prop <= 0.85, (
                f"Kaolinite proportion {kao_prop:.4f} not near expected 0.6 "
                f"(tolerance: 0.35-0.85)"
            )
