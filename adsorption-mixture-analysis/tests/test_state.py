
"""Tests for the adsorption mixture analysis tool."""

import json
import subprocess
import pytest


def run_analyze(*args):
    """Run the analyze.py script and return parsed JSON output."""
    cmd = ["python3", "/app/analyze.py"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"Command failed with stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    return json.loads(result.stdout.strip())


# ---- IAST Tests ----

class TestIAST:
    """Test IAST binary mixture prediction."""

    def test_iast_equimolar_1bar_fractions(self):
        """IAST at equimolar gas feed, 1 bar: adsorbed fractions match reference."""
        result = run_analyze(
            "iast",
            "/app/data/ch4_mof5.json",
            "/app/data/c2h6_mof5.json",
            "0.5", "0.5", "1.0",
        )
        x = result["adsorbed_fractions"]
        assert len(x) == 2
        # CH4 mole fraction ~0.188, C2H6 mole fraction ~0.812
        assert abs(x[0] - 0.188) < 0.015, f"x_CH4 = {x[0]}, expected ~0.188"
        assert abs(x[1] - 0.812) < 0.015, f"x_C2H6 = {x[1]}, expected ~0.812"

    def test_iast_equimolar_1bar_selectivity(self):
        """IAST selectivity at equimolar, 1 bar matches reference."""
        result = run_analyze(
            "iast",
            "/app/data/ch4_mof5.json",
            "/app/data/c2h6_mof5.json",
            "0.5", "0.5", "1.0",
        )
        s = result["selectivity"]
        # S12 = (x1/y1)/(x2/y2) = (0.188/0.5)/(0.812/0.5) ~ 0.232
        assert abs(s - 0.232) < 0.05, f"selectivity = {s}, expected ~0.232"

    def test_iast_fraction_normalization(self):
        """Adsorbed fractions sum to 1 and are in valid range."""
        result = run_analyze(
            "iast",
            "/app/data/ch4_mof5.json",
            "/app/data/c2h6_mof5.json",
            "0.5", "0.5", "1.0",
        )
        x = result["adsorbed_fractions"]
        assert abs(sum(x) - 1.0) < 1e-6, f"Fractions sum to {sum(x)}"
        assert all(0 < xi < 1 for xi in x), f"Fractions out of range: {x}"

    def test_iast_c2h6_enriched(self):
        """C2H6 (stronger adsorbate) is enriched in adsorbed phase vs gas phase."""
        result = run_analyze(
            "iast",
            "/app/data/ch4_mof5.json",
            "/app/data/c2h6_mof5.json",
            "0.5", "0.5", "1.0",
        )
        x = result["adsorbed_fractions"]
        assert x[1] > 0.5, f"C2H6 not enriched: x_C2H6={x[1]}"
        assert x[0] < 0.5, f"CH4 not depleted: x_CH4={x[0]}"

    def test_iast_selectivity_positive(self):
        """Selectivity is positive."""
        result = run_analyze(
            "iast",
            "/app/data/ch4_mof5.json",
            "/app/data/c2h6_mof5.json",
            "0.5", "0.5", "1.0",
        )
        assert result["selectivity"] > 0

    def test_iast_higher_pressure(self):
        """IAST at 5 bar produces valid result with different fractions than 1 bar."""
        result_1 = run_analyze(
            "iast",
            "/app/data/ch4_mof5.json",
            "/app/data/c2h6_mof5.json",
            "0.5", "0.5", "1.0",
        )
        result_5 = run_analyze(
            "iast",
            "/app/data/ch4_mof5.json",
            "/app/data/c2h6_mof5.json",
            "0.5", "0.5", "5.0",
        )
        x1 = result_1["adsorbed_fractions"]
        x5 = result_5["adsorbed_fractions"]
        assert abs(x1[0] - x5[0]) > 0.001, "IAST should give different results at different pressures"
        assert abs(sum(x5) - 1.0) < 1e-6


# ---- Isosteric Enthalpy Tests ----

class TestIsostericEnthalpy:
    """Test isosteric enthalpy via Clausius-Clapeyron."""

    def test_enthalpy_average(self):
        """Average isosteric enthalpy matches reference ~28.1 kJ/mol."""
        result = run_analyze(
            "enthalpy",
            "/app/data/butane_298K.json",
            "/app/data/butane_323K.json",
            "/app/data/butane_348K.json",
        )
        avg = result["average_enthalpy"]
        assert abs(avg - 28.0) < 2.0, f"average_enthalpy = {avg}, expected ~28.0 kJ/mol"

    def test_enthalpy_loading_count(self):
        """Should output 50 loading points."""
        result = run_analyze(
            "enthalpy",
            "/app/data/butane_298K.json",
            "/app/data/butane_323K.json",
            "/app/data/butane_348K.json",
        )
        assert len(result["loading"]) == 50
        assert len(result["isosteric_enthalpy"]) == 50

    def test_enthalpy_all_positive(self):
        """All isosteric enthalpy values should be positive (exothermic adsorption)."""
        result = run_analyze(
            "enthalpy",
            "/app/data/butane_298K.json",
            "/app/data/butane_323K.json",
            "/app/data/butane_348K.json",
        )
        for i, h in enumerate(result["isosteric_enthalpy"]):
            assert h > 0, f"Enthalpy at loading[{i}]={result['loading'][i]} is {h}, expected > 0"

    def test_enthalpy_loading_range(self):
        """Loading range should be within the common range of all isotherms."""
        result = run_analyze(
            "enthalpy",
            "/app/data/butane_298K.json",
            "/app/data/butane_323K.json",
            "/app/data/butane_348K.json",
        )
        loadings = result["loading"]
        # Min loading should be > max of isotherm minima (298K min=0.728)
        assert loadings[0] > 0.72, f"Min loading {loadings[0]} too low"
        # Max loading should be < min of isotherm maxima (348K max=8.843)
        assert loadings[-1] < 8.85, f"Max loading {loadings[-1]} too high"

    def test_enthalpy_reasonable_range(self):
        """Enthalpies should be in a physically reasonable range (5-50 kJ/mol)."""
        result = run_analyze(
            "enthalpy",
            "/app/data/butane_298K.json",
            "/app/data/butane_323K.json",
            "/app/data/butane_348K.json",
        )
        for h in result["isosteric_enthalpy"]:
            assert 5 < h < 50, f"Enthalpy {h} outside reasonable range [5, 50] kJ/mol"


# ---- SVP Tests ----

class TestSVP:
    """Test selectivity vs pressure curve."""

    def test_svp_point_count(self):
        """SVP should return the requested number of pressure points."""
        result = run_analyze(
            "svp",
            "/app/data/ch4_mof5.json",
            "/app/data/c2h6_mof5.json",
            "0.5", "0.5", "0.01", "10", "30",
        )
        assert len(result["pressures"]) == 30
        assert len(result["selectivities"]) == 30

    def test_svp_mean_selectivity(self):
        """Mean selectivity over [0.01, 10] bar matches reference ~0.19."""
        result = run_analyze(
            "svp",
            "/app/data/ch4_mof5.json",
            "/app/data/c2h6_mof5.json",
            "0.5", "0.5", "0.01", "10", "30",
        )
        mean_sel = result["mean_selectivity"]
        assert abs(mean_sel - 0.19) < 0.05, f"mean_selectivity = {mean_sel}, expected ~0.19"

    def test_svp_all_positive(self):
        """All selectivities should be positive."""
        result = run_analyze(
            "svp",
            "/app/data/ch4_mof5.json",
            "/app/data/c2h6_mof5.json",
            "0.5", "0.5", "0.01", "10", "30",
        )
        for i, s in enumerate(result["selectivities"]):
            assert s > 0, f"Selectivity at P={result['pressures'][i]} is {s}, expected > 0"

    def test_svp_selectivity_less_than_one(self):
        """S_CH4/C2H6 should be < 1 (C2H6 is preferentially adsorbed)."""
        result = run_analyze(
            "svp",
            "/app/data/ch4_mof5.json",
            "/app/data/c2h6_mof5.json",
            "0.5", "0.5", "0.01", "10", "30",
        )
        for i, s in enumerate(result["selectivities"]):
            assert s < 1.0, f"S12 at P={result['pressures'][i]} is {s}, expected < 1"

    def test_svp_pressure_range(self):
        """Pressures should span the requested range."""
        result = run_analyze(
            "svp",
            "/app/data/ch4_mof5.json",
            "/app/data/c2h6_mof5.json",
            "0.5", "0.5", "0.01", "10", "30",
        )
        assert abs(result["pressures"][0] - 0.01) < 1e-6
        assert abs(result["pressures"][-1] - 10.0) < 1e-6
