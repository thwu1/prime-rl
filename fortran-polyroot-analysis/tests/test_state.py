"""Verify polynomial root-finding audit results.

"""
import json
import os

import pytest

AUDIT_PATH = "/app/audit.json"
POLYNOMIALS_PATH = "/app/polynomials.json"

POLY_NAMES = {"simple_quintic", "asymmetric_sextic", "wilkinson_20",
              "near_double", "chebyshev_20", "roots_of_unity"}

EXPECTED_DEFECTIVE = {"asymmetric_sextic", "wilkinson_20", "near_double"}
EXPECTED_CORRECT = {"simple_quintic", "chebyshev_20", "roots_of_unity"}

# Keywords that must appear in the defect type string for each defective polynomial
DEFECT_TYPE_KEYWORDS = {
    "asymmetric_sextic": ["coefficient", "ordering", "reversed", "order", "convention",
                          "ascending", "descending", "flipped", "wrong_polynomial",
                          "swapped", "inverted", "reverse"],
    "wilkinson_20": ["missing", "dropped", "count", "incomplete", "lost", "absent",
                     "fewer", "short", "19"],
    "near_double": ["convergence", "spurious", "wrong", "inaccurate", "failure",
                    "diverge", "bogus", "false", "incorrect", "bad", "non_root",
                    "invalid"],
}

# Backward error tolerance per polynomial for corrected roots
BACKWARD_ERROR_TOL = {
    "simple_quintic": 1e-10,
    "asymmetric_sextic": 1e-8,
    "wilkinson_20": 1e-2,
    "near_double": 1e-8,
    "chebyshev_20": 1e-8,
    "roots_of_unity": 1e-10,
}


@pytest.fixture(scope="module")
def polynomials():
    with open(POLYNOMIALS_PATH) as f:
        data = json.load(f)
    return {p["name"]: p for p in data["polynomials"]}


@pytest.fixture(scope="module")
def audit():
    with open(AUDIT_PATH) as f:
        return json.load(f)


def eval_poly_horner(coeffs_desc, z):
    """Evaluate polynomial with descending coefficients at complex z."""
    result = complex(coeffs_desc[0])
    for c in coeffs_desc[1:]:
        result = result * z + complex(c)
    return result


def backward_error(coeffs_desc, z):
    """Componentwise relative backward error: |p(z)| / sum(|a_k| |z|^k)."""
    pz = eval_poly_horner(coeffs_desc, z)
    n = len(coeffs_desc) - 1
    az = abs(z)
    denom = sum(abs(coeffs_desc[i]) * (az ** (n - i)) for i in range(n + 1))
    if denom < 1e-300:
        return abs(pz)
    return abs(pz) / denom


# ========== Structural tests ==========

class TestAuditStructure:
    def test_audit_file_exists(self):
        assert os.path.exists(AUDIT_PATH), f"Audit file not found at {AUDIT_PATH}"

    def test_audit_valid_json(self):
        with open(AUDIT_PATH) as f:
            json.load(f)

    def test_has_required_keys(self, audit):
        for key in ["defective_polynomials", "correct_polynomials", "defects",
                     "corrected_roots", "algorithm_comparison", "best_algorithm"]:
            assert key in audit, f"Missing key '{key}'"


# ========== Defect classification tests ==========

class TestDefectClassification:
    def test_defective_set(self, audit):
        found = set(audit["defective_polynomials"])
        assert found == EXPECTED_DEFECTIVE, \
            f"Expected defective: {EXPECTED_DEFECTIVE}, got: {found}"

    def test_correct_set(self, audit):
        found = set(audit["correct_polynomials"])
        assert found == EXPECTED_CORRECT, \
            f"Expected correct: {EXPECTED_CORRECT}, got: {found}"

    def test_complete_coverage(self, audit):
        all_classified = set(audit["defective_polynomials"]) | set(audit["correct_polynomials"])
        assert all_classified == POLY_NAMES, \
            f"Not all polynomials classified: missing {POLY_NAMES - all_classified}"

    def test_no_overlap(self, audit):
        overlap = set(audit["defective_polynomials"]) & set(audit["correct_polynomials"])
        assert overlap == set(), f"Polynomials in both lists: {overlap}"


# ========== Defect diagnosis tests ==========

class TestDefectDiagnosis:
    @pytest.mark.parametrize("poly_name", sorted(EXPECTED_DEFECTIVE))
    def test_defect_entry_exists(self, audit, poly_name):
        assert poly_name in audit["defects"], f"Missing defect entry for '{poly_name}'"

    @pytest.mark.parametrize("poly_name", sorted(EXPECTED_DEFECTIVE))
    def test_defect_has_type(self, audit, poly_name):
        defect = audit["defects"][poly_name]
        assert "type" in defect, f"{poly_name}: defect missing 'type' field"

    @pytest.mark.parametrize("poly_name", sorted(EXPECTED_DEFECTIVE))
    def test_defect_type_matches(self, audit, poly_name):
        dtype = audit["defects"][poly_name]["type"].lower().replace("-", "_").replace(" ", "_")
        keywords = DEFECT_TYPE_KEYWORDS[poly_name]
        assert any(kw in dtype for kw in keywords), \
            f"{poly_name}: defect type '{dtype}' doesn't match expected keywords {keywords}"


# ========== Corrected roots tests ==========

class TestCorrectedRoots:
    @pytest.mark.parametrize("poly_name", sorted(POLY_NAMES))
    def test_roots_present(self, audit, poly_name):
        assert poly_name in audit["corrected_roots"], \
            f"Missing corrected roots for '{poly_name}'"

    @pytest.mark.parametrize("poly_name", sorted(POLY_NAMES))
    def test_correct_count(self, audit, polynomials, poly_name):
        expected = polynomials[poly_name]["degree"]
        actual = len(audit["corrected_roots"][poly_name])
        assert actual == expected, \
            f"{poly_name}: expected {expected} roots, got {actual}"

    @pytest.mark.parametrize("poly_name", sorted(POLY_NAMES))
    def test_backward_error(self, audit, polynomials, poly_name):
        coeffs = polynomials[poly_name]["coefficients_descending"]
        tol = BACKWARD_ERROR_TOL[poly_name]
        for i, root in enumerate(audit["corrected_roots"][poly_name]):
            z = complex(root["re"], root["im"])
            be = backward_error(coeffs, z)
            assert be < tol, \
                f"{poly_name} root {i} (z={z:.6g}): backward_error={be:.2e} > {tol:.0e}"

    def test_wilkinson_20_all_integers(self, audit):
        """Corrected Wilkinson-20 roots must approximate all integers 1 through 20."""
        roots = audit["corrected_roots"]["wilkinson_20"]
        for target in range(1, 21):
            has_target = any(
                abs(r["re"] - target) < 1.0 and abs(r["im"]) < 1.0
                for r in roots
            )
            assert has_target, f"wilkinson_20: no corrected root near x={target}"

    def test_near_double_has_double_root(self, audit):
        """Corrected near_double must have two roots near x=1 (the double root)."""
        roots = audit["corrected_roots"]["near_double"]
        near_one = [r for r in roots
                    if abs(r["re"] - 1.0) < 0.15 and abs(r["im"]) < 0.15]
        assert len(near_one) == 2, \
            f"near_double: expected 2 roots near x=1, got {len(near_one)}"

    def test_simple_quintic_integer_roots(self, audit):
        """simple_quintic roots should be near 1, 2, 3, 4, 5."""
        roots = audit["corrected_roots"]["simple_quintic"]
        for target in [1, 2, 3, 4, 5]:
            has_target = any(
                abs(r["re"] - target) < 0.01 and abs(r["im"]) < 0.01
                for r in roots
            )
            assert has_target, f"simple_quintic: no root near x={target}"

    def test_roots_of_unity_on_unit_circle(self, audit):
        """roots_of_unity (x^15-1) roots should lie on the unit circle."""
        roots = audit["corrected_roots"]["roots_of_unity"]
        for i, r in enumerate(roots):
            mag = (r["re"]**2 + r["im"]**2)**0.5
            assert abs(mag - 1.0) < 1e-6, \
                f"roots_of_unity root {i}: |z|={mag:.8f}, expected 1.0"


# ========== Algorithm comparison tests ==========

class TestAlgorithmComparison:
    def test_at_least_3_algorithms(self, audit):
        n = len(audit["algorithm_comparison"])
        assert n >= 3, f"Need >= 3 algorithms in comparison, got {n}"

    def test_algorithms_cover_all_polynomials(self, audit):
        for algo, data in audit["algorithm_comparison"].items():
            for poly_name in POLY_NAMES:
                assert poly_name in data, \
                    f"Algorithm '{algo}' missing data for '{poly_name}'"

    def test_metrics_are_numeric(self, audit):
        for algo, data in audit["algorithm_comparison"].items():
            for poly_name, metrics in data.items():
                assert "max_backward_error" in metrics, \
                    f"{algo}/{poly_name}: missing 'max_backward_error'"
                assert isinstance(metrics["max_backward_error"], (int, float)), \
                    f"{algo}/{poly_name}: max_backward_error not numeric"

    def test_best_algorithm_in_comparison(self, audit):
        assert audit["best_algorithm"] in audit["algorithm_comparison"], \
            f"best_algorithm '{audit['best_algorithm']}' not in algorithm_comparison"

    def test_best_algorithm_performance(self, audit):
        """Best algorithm should achieve low backward errors on well-conditioned polynomials."""
        best = audit["best_algorithm"]
        data = audit["algorithm_comparison"][best]
        for pname in ["simple_quintic", "roots_of_unity"]:
            be = data[pname]["max_backward_error"]
            assert be < 1e-6, \
                f"Best algorithm '{best}' has backward error {be:.2e} on '{pname}'"

    def test_algorithms_are_distinct(self, audit):
        """Algorithm names must be distinct (no duplicates)."""
        names = list(audit["algorithm_comparison"].keys())
        assert len(names) == len(set(names)), "Duplicate algorithm names found"
