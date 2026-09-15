
"""Tests for permafrost analysis pipeline output."""

import json
import math
import os
import struct
import subprocess

import pytest


@pytest.fixture(scope="session", autouse=True)
def run_solver():
    """Run the pipeline before any tests."""
    subprocess.run(
        ["python3", "/app/pipeline.py"],
        cwd="/app",
        timeout=120,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def output():
    """Load the output JSON file."""
    output_path = "/app/output.json"
    assert os.path.exists(output_path), "output.json was not created"
    with open(output_path) as f:
        data = json.load(f)
    return data


# ============================================================
# Structural tests
# ============================================================

class TestOutputStructure:
    def test_output_is_dict(self, output):
        assert isinstance(output, dict)

    def test_all_sites_present(self, output):
        for site in ["arctic", "subarctic", "warm"]:
            assert site in output, f"Site '{site}' missing from output"

    def test_required_keys(self, output):
        required = [
            "air_frost_number",
            "ground_surface_temperature",
            "ground_surface_amplitude",
            "has_permafrost",
            "permafrost_temperature",
            "active_layer_thickness",
        ]
        for site_name, site_data in output.items():
            for key in required:
                assert key in site_data, f"Key '{key}' missing from site '{site_name}'"


# ============================================================
# Frost number tests
# ============================================================

class TestFrostNumber:
    def test_arctic_frost_number(self, output):
        """Ta=-5, Aa=15 -> T_cold=-20, T_hot=10 -> F_air ~ 0.6327"""
        fn = output["arctic"]["air_frost_number"]
        assert abs(fn - 0.6327) < 0.005, f"Arctic frost number {fn} not near 0.6327"

    def test_subarctic_frost_number(self, output):
        """Ta=-3, Aa=18 -> T_cold=-21, T_hot=15 -> F_air ~ 0.5657"""
        fn = output["subarctic"]["air_frost_number"]
        assert abs(fn - 0.5657) < 0.005, f"Subarctic frost number {fn} not near 0.5657"

    def test_warm_frost_number(self, output):
        """Ta=2, Aa=12 -> T_cold=-10, T_hot=14 -> F_air ~ 0.4343"""
        fn = output["warm"]["air_frost_number"]
        assert abs(fn - 0.4343) < 0.005, f"Warm frost number {fn} not near 0.4343"

    def test_frost_number_range(self, output):
        """All frost numbers must be in [0, 1]."""
        for site_name, site_data in output.items():
            fn = site_data["air_frost_number"]
            assert 0.0 <= fn <= 1.0, f"Frost number {fn} out of range for {site_name}"

    def test_frost_number_ordering(self, output):
        """Colder sites should have higher frost numbers."""
        assert output["arctic"]["air_frost_number"] > output["subarctic"]["air_frost_number"]
        assert output["subarctic"]["air_frost_number"] > output["warm"]["air_frost_number"]


# ============================================================
# Arctic site tests (no snow, no vegetation -> simplified)
# ============================================================

class TestArcticSite:
    def test_ground_surface_temp(self, output):
        """With no snow and no vegetation, Tgs = Ta = -5.0."""
        tgs = output["arctic"]["ground_surface_temperature"]
        assert abs(tgs - (-5.0)) < 0.01, f"Arctic Tgs {tgs} should be -5.0 (no snow/veg)"

    def test_ground_surface_amplitude(self, output):
        """With no snow and no vegetation, Ags = Aa = 15.0."""
        ags = output["arctic"]["ground_surface_amplitude"]
        assert abs(ags - 15.0) < 0.01, f"Arctic Ags {ags} should be 15.0 (no snow/veg)"

    def test_has_permafrost(self, output):
        """Arctic site should have permafrost."""
        assert output["arctic"]["has_permafrost"] is True

    def test_permafrost_temperature(self, output):
        """Tps ~ -5.98 degC (standard formulation)."""
        tps = output["arctic"]["permafrost_temperature"]
        assert tps is not None, "Arctic Tps should not be null"
        assert -6.2 < tps < -5.8, f"Arctic Tps {tps} not in expected range [-6.2, -5.8]"

    def test_permafrost_colder_than_surface(self, output):
        """Tps should be colder than Tgs due to conductivity asymmetry (Kf > Kt)."""
        tps = output["arctic"]["permafrost_temperature"]
        tgs = output["arctic"]["ground_surface_temperature"]
        assert tps < tgs, f"Tps ({tps}) should be colder than Tgs ({tgs})"

    def test_active_layer_thickness(self, output):
        """ALT ~ 1.05 m."""
        alt = output["arctic"]["active_layer_thickness"]
        assert alt is not None, "Arctic ALT should not be null"
        assert 0.95 < alt < 1.15, f"Arctic ALT {alt} not in expected range [0.95, 1.15]"

    def test_alt_positive(self, output):
        """ALT must be positive."""
        alt = output["arctic"]["active_layer_thickness"]
        assert alt > 0, f"Arctic ALT {alt} should be positive"


# ============================================================
# Subarctic site tests (snow + vegetation + mixed soils)
# ============================================================

class TestSubarcticSite:
    def test_snow_warms_surface(self, output):
        """Snow insulation should warm ground relative to air (-3.0 degC)."""
        tgs = output["subarctic"]["ground_surface_temperature"]
        ta = -3.0
        assert tgs > ta, f"Subarctic Tgs {tgs} should be warmer than Ta {ta} due to snow"

    def test_ground_surface_temp(self, output):
        """Tgs ~ 0.42 degC."""
        tgs = output["subarctic"]["ground_surface_temperature"]
        assert abs(tgs - 0.42) < 0.15, f"Subarctic Tgs {tgs} not near 0.42"

    def test_snow_reduces_amplitude(self, output):
        """Snow should reduce ground surface amplitude below Aa=18."""
        ags = output["subarctic"]["ground_surface_amplitude"]
        assert ags < 18.0, f"Subarctic Ags {ags} should be < 18.0 due to snow damping"
        assert ags > 12.0, f"Subarctic Ags {ags} implausibly low"

    def test_ground_surface_amplitude(self, output):
        """Ags ~ 15.38 degC."""
        ags = output["subarctic"]["ground_surface_amplitude"]
        assert abs(ags - 15.38) < 0.2, f"Subarctic Ags {ags} not near 15.38"

    def test_has_permafrost(self, output):
        """Subarctic site should have permafrost despite Tgs > 0."""
        assert output["subarctic"]["has_permafrost"] is True

    def test_permafrost_temperature(self, output):
        """Tps ~ -1.9 degC."""
        tps = output["subarctic"]["permafrost_temperature"]
        assert tps is not None
        assert -2.2 < tps < -1.6, f"Subarctic Tps {tps} not in expected range [-2.2, -1.6]"

    def test_active_layer_thickness(self, output):
        """ALT ~ 1.43 m."""
        alt = output["subarctic"]["active_layer_thickness"]
        assert alt is not None
        assert 1.3 < alt < 1.6, f"Subarctic ALT {alt} not in expected range [1.3, 1.6]"

    def test_subarctic_deeper_than_arctic(self, output):
        """Subarctic (warmer, more snow) should have deeper active layer than arctic."""
        alt_arctic = output["arctic"]["active_layer_thickness"]
        alt_sub = output["subarctic"]["active_layer_thickness"]
        assert alt_sub > alt_arctic, (
            f"Subarctic ALT ({alt_sub}) should exceed Arctic ALT ({alt_arctic})"
        )


# ============================================================
# Warm site tests (no permafrost)
# ============================================================

class TestWarmSite:
    def test_no_permafrost(self, output):
        """Warm site (Ta=2, Aa=12) should have no permafrost."""
        assert output["warm"]["has_permafrost"] is False

    def test_permafrost_temp_null(self, output):
        """Permafrost temperature should be null when no permafrost."""
        assert output["warm"]["permafrost_temperature"] is None

    def test_alt_null(self, output):
        """Active layer thickness should be null when no permafrost."""
        assert output["warm"]["active_layer_thickness"] is None

    def test_ground_surface_temp(self, output):
        """Tgs ~ 2.92 degC (warmed by snow insulation from Ta=2)."""
        tgs = output["warm"]["ground_surface_temperature"]
        assert tgs > 2.0, f"Warm Tgs {tgs} should be > Ta=2.0 due to snow insulation"
        assert abs(tgs - 2.92) < 0.15, f"Warm Tgs {tgs} not near 2.92"

    def test_ground_surface_amplitude(self, output):
        """Ags ~ 11.41 (reduced from Aa=12 by snow damping)."""
        ags = output["warm"]["ground_surface_amplitude"]
        assert ags < 12.0, f"Warm Ags {ags} should be < Aa=12.0"
        assert abs(ags - 11.41) < 0.15, f"Warm Ags {ags} not near 11.41"


# ============================================================
# Cross-site consistency tests
# ============================================================

class TestConsistency:
    def test_permafrost_temp_types(self, output):
        """Permafrost temp must be float when permafrost exists, null otherwise."""
        for site_name, site_data in output.items():
            if site_data["has_permafrost"]:
                assert isinstance(site_data["permafrost_temperature"], (int, float))
                assert isinstance(site_data["active_layer_thickness"], (int, float))
            else:
                assert site_data["permafrost_temperature"] is None
                assert site_data["active_layer_thickness"] is None

    def test_amplitudes_positive(self, output):
        """All ground surface amplitudes must be positive."""
        for site_name, site_data in output.items():
            assert site_data["ground_surface_amplitude"] > 0

    def test_frost_numbers_consistent_with_temperature(self, output):
        """Sites with lower Ta should generally have higher frost numbers."""
        assert output["arctic"]["air_frost_number"] > output["warm"]["air_frost_number"]

    def test_thermal_library_exists(self):
        """The Fortran shared library must exist."""
        assert os.path.exists("/app/thermal_lib/libthermal.so"), (
            "libthermal.so not found — the Fortran thermal library must be compiled"
        )

    def test_library_is_shared(self):
        """The thermal library must be a shared object, not a static archive."""
        lib_path = "/app/thermal_lib/libthermal.so"
        assert os.path.exists(lib_path), "libthermal.so not found"
        with open(lib_path, "rb") as f:
            header = f.read(18)
        # Check ELF magic bytes: 0x7f 'E' 'L' 'F'
        assert len(header) >= 18, "File too small to be a valid ELF shared library"
        assert header[:4] == b'\x7fELF', (
            f"libthermal.so is not an ELF binary (starts with {header[:4]!r}); "
            "static archives start with b'!<arch>' — rebuild as a shared object"
        )
        # ELF e_type at offset 16 (2 bytes): ET_DYN (3) = shared object
        e_type = struct.unpack_from('<H', header, 16)[0]
        assert e_type == 3, (
            f"libthermal.so ELF type is {e_type} (expected 3=ET_DYN shared object); "
            "type 1 is a relocatable object, type 2 is an executable"
        )
