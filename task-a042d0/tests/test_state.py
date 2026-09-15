
import json
import os
import re

import pytest

RESULTS_PATH = "/app/results.json"
CORRECTED_PATH = "/app/corrected.inp"
CONVERGENCE_DIR = "/app/convergence"
ORIGINAL_PATH = "/app/project/model.inp"

REFERENCE_SIGMA_YY = -5.38  # MPa


@pytest.fixture
def results():
    with open(RESULTS_PATH, "r") as f:
        return json.load(f)


@pytest.fixture
def corrected_inp():
    with open(CORRECTED_PATH, "r") as f:
        return f.read()


# ================================================================
# results.json structure and schema
# ================================================================

class TestResultsFile:
    def test_results_exists(self):
        assert os.path.isfile(RESULTS_PATH), "results.json not found at /app/results.json"

    def test_results_valid_json(self):
        with open(RESULTS_PATH, "r") as f:
            data = json.load(f)
        assert isinstance(data, dict), "results.json must be a JSON object"

    def test_required_keys(self, results):
        for key in ["benchmark_id", "errors", "convergence", "final_sigma_yy_MPa"]:
            assert key in results, f"Missing required key: {key}"

    def test_benchmark_id(self, results):
        bid = results["benchmark_id"].upper().replace("-", "").replace("_", "").replace(" ", "")
        assert "LE10" in bid, (
            f"benchmark_id '{results['benchmark_id']}' must identify the LE10 benchmark"
        )


# ================================================================
# Error diagnosis
# ================================================================

class TestErrorDiagnosis:
    def test_errors_count(self, results):
        assert len(results["errors"]) >= 3, "Must identify at least 3 errors"

    def test_errors_schema(self, results):
        for err in results["errors"]:
            for key in ["line_number", "original", "corrected", "category"]:
                assert key in err, f"Error entry missing key: {key}"
            assert err["category"] in ("material", "boundary_condition", "loading"), (
                f"Invalid category: {err['category']}"
            )

    def test_errors_span_categories(self, results):
        categories = {err["category"] for err in results["errors"]}
        assert len(categories) >= 2, (
            f"Errors must span at least 2 categories, found only: {categories}"
        )


# ================================================================
# Corrected model verification
# ================================================================

class TestCorrectedModel:
    def test_corrected_exists(self):
        assert os.path.isfile(CORRECTED_PATH), "corrected.inp not found at /app/corrected.inp"

    def test_differs_from_original(self, corrected_inp):
        with open(ORIGINAL_PATH, "r") as f:
            original = f.read()
        assert corrected_inp.strip() != original.strip(), (
            "corrected.inp must differ from the original model.inp"
        )

    def test_poisson_ratio(self, corrected_inp):
        """Elastic constants must match benchmark specification."""
        lines = corrected_inp.split("\n")
        in_elastic = False
        found = False
        for line in lines:
            upper = line.strip().upper()
            if upper.startswith("*ELASTIC"):
                in_elastic = True
                continue
            if in_elastic and line.strip() and not line.strip().startswith("*"):
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        nu = float(parts[1].strip())
                        assert 0.25 <= nu <= 0.35, (
                            f"Poisson's ratio {nu} not within expected range [0.25, 0.35]"
                        )
                        found = True
                    except ValueError:
                        pass
                in_elastic = False
        assert found, "Could not find valid *ELASTIC data with Poisson's ratio"

    def test_dc_symmetry_boundary(self, corrected_inp):
        """Symmetry BC must be present on all required planes."""
        lines = corrected_inp.split("\n")
        in_boundary = False
        found_dc_v = False
        for line in lines:
            upper = line.strip().upper()
            if upper.startswith("*BOUNDARY"):
                in_boundary = True
                continue
            if in_boundary and upper.startswith("*") and not upper.startswith("**"):
                in_boundary = False
                continue
            if in_boundary and "DC" in upper:
                # Accept DC,2 or DC, 2, 2 or DC,2,2,0.0 etc.
                after_dc = upper.split("DC")[1]
                if "2" in after_dc:
                    found_dc_v = True
        assert found_dc_v, (
            "Missing symmetry boundary condition: DC node set must have DOF 2 constrained"
        )

    def test_pressure_positive(self, corrected_inp):
        """Applied loading must have correct sign and magnitude."""
        lines = corrected_inp.split("\n")
        in_dload = False
        found_positive = False
        for line in lines:
            upper = line.strip().upper()
            if upper.startswith("*DLOAD"):
                in_dload = True
                continue
            if in_dload and upper.startswith("*") and not upper.startswith("**"):
                in_dload = False
                continue
            if in_dload and "P" in upper:
                parts = line.split(",")
                if len(parts) >= 3:
                    try:
                        val = float(parts[-1].strip())
                        if val > 0:
                            found_positive = True
                    except ValueError:
                        pass
        assert found_positive, "Pressure load must be positive (compressive into surface)"


# ================================================================
# Convergence study
# ================================================================

class TestConvergenceStudy:
    def test_convergence_count(self, results):
        assert len(results["convergence"]) >= 3, "Need at least 3 convergence levels"

    def test_convergence_schema(self, results):
        for entry in results["convergence"]:
            for key in ["level", "num_elements", "num_nodes", "sigma_yy_MPa"]:
                assert key in entry, f"Convergence entry missing key: {key}"
            assert isinstance(entry["num_elements"], int), "num_elements must be int"
            assert isinstance(entry["num_nodes"], int), "num_nodes must be int"
            assert isinstance(entry["sigma_yy_MPa"], (int, float)), "sigma_yy_MPa must be numeric"

    def test_increasing_elements(self, results):
        conv = sorted(results["convergence"], key=lambda x: x["level"])
        elements = [c["num_elements"] for c in conv]
        for i in range(1, len(elements)):
            assert elements[i] > elements[i - 1], (
                f"num_elements must strictly increase: level {conv[i-1]['level']} "
                f"has {elements[i-1]}, level {conv[i]['level']} has {elements[i]}"
            )

    def test_convergence_trend(self, results):
        conv = sorted(results["convergence"], key=lambda x: x["level"])
        if len(conv) < 3:
            pytest.skip("Need at least 3 levels to test trend")
        values = [c["sigma_yy_MPa"] for c in conv]
        final = values[-1]
        # First value should be further from final than last-but-one
        dist_first = abs(values[0] - final)
        dist_penult = abs(values[-2] - final)
        assert dist_first >= dist_penult, (
            f"Values should converge: distance of level 1 from final ({dist_first:.4f}) "
            f"should exceed distance of penultimate from final ({dist_penult:.4f})"
        )

    def test_final_sigma_accuracy(self, results):
        final = results["final_sigma_yy_MPa"]
        assert isinstance(final, (int, float)), "final_sigma_yy_MPa must be numeric"
        rel_err = abs(final - REFERENCE_SIGMA_YY) / abs(REFERENCE_SIGMA_YY)
        assert rel_err <= 0.05, (
            f"final_sigma_yy_MPa={final:.4f} not within 5% of reference "
            f"{REFERENCE_SIGMA_YY} (relative error={rel_err*100:.1f}%)"
        )


# ================================================================
# Convergence output files
# ================================================================

class TestConvergenceFiles:
    def test_convergence_dir_exists(self):
        assert os.path.isdir(CONVERGENCE_DIR), "/app/convergence/ directory not found"

    def test_dat_files_exist(self, results):
        for entry in results.get("convergence", []):
            level = entry["level"]
            dat_path = os.path.join(CONVERGENCE_DIR, f"level_{level}.dat")
            assert os.path.isfile(dat_path), f"Missing convergence output: {dat_path}"

    def test_dat_files_have_content(self, results):
        for entry in results.get("convergence", []):
            level = entry["level"]
            dat_path = os.path.join(CONVERGENCE_DIR, f"level_{level}.dat")
            if os.path.isfile(dat_path):
                size = os.path.getsize(dat_path)
                assert size > 100, (
                    f"{dat_path} is too small ({size} bytes); "
                    f"must contain actual CalculiX solver output"
                )
