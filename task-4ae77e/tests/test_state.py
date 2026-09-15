"""
Tests for Cantilever Beam RBDO solution.
Verifies simulation driver protocol, Dakota input file syntax,
reliability analysis validation, optimal design, Monte Carlo consistency,
and convergence.
"""

import json
import csv
import os
import re
import subprocess
import pytest
import numpy as np
from scipy.stats import norm


RESULTS_DIR = "/app/results"


# ============================================================
# Helper: Create and parse Dakota-format files
# ============================================================

def write_dakota_params(path, var_pairs, asv_list, dvv_indices=None):
    """Write a Dakota standard-format parameters file."""
    with open(path, 'w') as f:
        f.write(f"                    {len(var_pairs)} variables\n")
        for val, label in var_pairs:
            f.write(f"  {val:20.15e} {label}\n")
        f.write(f"                    {len(asv_list)} functions\n")
        for asv_val, asv_label in asv_list:
            f.write(f"                    {asv_val} {asv_label}\n")
        if dvv_indices:
            f.write(f"                    {len(dvv_indices)} derivative_variables\n")
            for i, idx in enumerate(dvv_indices):
                f.write(f"                    {idx} DVV_{i+1}\n")
        else:
            f.write(f"                    0 derivative_variables\n")
        f.write(f"                    0 analysis_components\n")


def parse_dakota_results(path):
    """Parse a Dakota results file.

    Returns list of (value, gradient_or_None) tuples.
    """
    with open(path) as f:
        content = f.read()

    results = []
    lines = content.strip().split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith('[') and not line.startswith('[['):
            grad_str = line.strip('[] \t').strip()
            grad = [float(x) for x in grad_str.split()]
            if results:
                results[-1] = (results[-1][0], grad)
            i += 1
        elif line.startswith('[['):
            i += 1
        else:
            parts = line.split()
            if parts:
                val = float(parts[0])
                results.append((val, None))
            i += 1
    return results


# ============================================================
# Dakota Simulation Driver Protocol Tests
# ============================================================

class TestDriverProtocol:
    """Test that the cantilever driver follows Dakota's file I/O protocol."""

    def test_driver_exists(self):
        assert os.path.exists("/app/cantilever_driver.py"), \
            "Missing /app/cantilever_driver.py"

    def test_driver_values_only(self):
        """ASV=[1,1,1]: compute function values only."""
        w, t = 2.5, 3.5
        R, E, X, Y = 40000.0, 29.0e6, 500.0, 1000.0

        params_path = "/tmp/test_params_val.in"
        results_path = "/tmp/test_results_val.out"

        write_dakota_params(params_path,
            [(w, 'w'), (t, 't'), (R, 'R'), (E, 'E'), (X, 'X'), (Y, 'Y')],
            [(1, 'ASV_1:area'), (1, 'ASV_2:stress_con'), (1, 'ASV_3:disp_con')])

        result = subprocess.run(
            ['python3', '/app/cantilever_driver.py', params_path, results_path],
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"Driver failed: {result.stderr}"
        assert os.path.exists(results_path), "No results file produced"

        results = parse_dakota_results(results_path)
        assert len(results) >= 3, f"Expected 3 responses, got {len(results)}"

        # Verify area = w * t
        assert abs(results[0][0] - w * t) < 0.01, \
            f"area = {results[0][0]}, expected {w * t}"

        # Verify stress constraint = stress/R - 1
        stress = 600.0 * Y / (w * t**2) + 600.0 * X / (w**2 * t)
        expected_sc = stress / R - 1.0
        assert abs(results[1][0] - expected_sc) < 1e-6, \
            f"stress_con = {results[1][0]}, expected {expected_sc}"

        # Verify displacement constraint = D/D0 - 1
        D0, L = 2.2535, 100.0
        S = np.sqrt((Y / t**2)**2 + (X / w**2)**2)
        D = 4.0 * L**3 * S / (E * w * t)
        expected_dc = D / D0 - 1.0
        assert abs(results[2][0] - expected_dc) < 1e-6, \
            f"disp_con = {results[2][0]}, expected {expected_dc}"

    def test_driver_with_gradients(self):
        """ASV=[3,3,3]: values + gradients w.r.t. w and t."""
        w, t = 2.5, 3.5
        R, E, X, Y = 40000.0, 29.0e6, 500.0, 1000.0

        params_path = "/tmp/test_params_grad.in"
        results_path = "/tmp/test_results_grad.out"

        write_dakota_params(params_path,
            [(w, 'w'), (t, 't'), (R, 'R'), (E, 'E'), (X, 'X'), (Y, 'Y')],
            [(3, 'ASV_1:area'), (3, 'ASV_2:stress_con'), (3, 'ASV_3:disp_con')],
            dvv_indices=[1, 2])

        result = subprocess.run(
            ['python3', '/app/cantilever_driver.py', params_path, results_path],
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"Driver failed: {result.stderr}"

        results = parse_dakota_results(results_path)

        # Area value
        assert abs(results[0][0] - w * t) < 0.01

        # Area gradient: d(w*t)/dw = t, d(w*t)/dt = w
        area_grad = results[0][1]
        assert area_grad is not None, "No gradient vector for area"
        assert len(area_grad) == 2, f"Expected 2-element gradient, got {len(area_grad)}"
        assert abs(area_grad[0] - t) < 1e-6, \
            f"d(area)/dw = {area_grad[0]}, expected {t}"
        assert abs(area_grad[1] - w) < 1e-6, \
            f"d(area)/dt = {area_grad[1]}, expected {w}"

        # Stress constraint gradient exists and has correct dimension
        sc_grad = results[1][1]
        assert sc_grad is not None, "No gradient vector for stress constraint"
        assert len(sc_grad) == 2

        # Verify stress constraint gradient analytically
        expected_sc_dw = -600.0 * (Y / t + 2.0 * X / w) / (w**2 * t * R)
        assert abs(sc_grad[0] - expected_sc_dw) < 1e-8, \
            f"d(stress_con)/dw = {sc_grad[0]}, expected {expected_sc_dw}"

        # Displacement constraint gradient exists
        dc_grad = results[2][1]
        assert dc_grad is not None, "No gradient vector for displacement constraint"
        assert len(dc_grad) == 2

    def test_driver_different_point(self):
        """Test driver at a second design point for robustness."""
        w, t = 3.0, 4.0
        R, E, X, Y = 38000.0, 28.0e6, 450.0, 950.0

        params_path = "/tmp/test_params_alt.in"
        results_path = "/tmp/test_results_alt.out"

        write_dakota_params(params_path,
            [(w, 'w'), (t, 't'), (R, 'R'), (E, 'E'), (X, 'X'), (Y, 'Y')],
            [(1, 'ASV_1:area'), (1, 'ASV_2:stress_con'), (1, 'ASV_3:disp_con')])

        result = subprocess.run(
            ['python3', '/app/cantilever_driver.py', params_path, results_path],
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"Driver failed at (3,4): {result.stderr}"

        results = parse_dakota_results(results_path)
        assert abs(results[0][0] - w * t) < 0.01, \
            f"area = {results[0][0]}, expected {w * t}"

        stress = 600.0 * Y / (w * t**2) + 600.0 * X / (w**2 * t)
        assert abs(results[1][0] - (stress / R - 1.0)) < 1e-6


# ============================================================
# Dakota Input File Syntax Tests
# ============================================================

class TestDakotaInputFile:
    """Validate the Dakota input file has correct block structure."""

    @pytest.fixture(autouse=True)
    def load_file(self):
        path = "/app/dakota_cantilever.in"
        assert os.path.exists(path), f"Missing {path}"
        with open(path) as f:
            self.content = f.read()
        self.lower = self.content.lower()

    def test_has_method_block(self):
        assert re.search(r'^\s*method\b', self.lower, re.MULTILINE), \
            "Missing 'method' block"

    def test_has_local_reliability(self):
        assert 'local_reliability' in self.lower, \
            "Missing 'local_reliability' method keyword"

    def test_has_mpp_search(self):
        assert 'mpp_search' in self.lower, \
            "Missing 'mpp_search' keyword"

    def test_has_variables_block(self):
        assert re.search(r'^\s*variables\b', self.lower, re.MULTILINE), \
            "Missing 'variables' block"

    def test_has_continuous_design(self):
        assert 'continuous_design' in self.lower, \
            "Missing 'continuous_design' specification"

    def test_has_normal_uncertain(self):
        assert 'normal_uncertain' in self.lower, \
            "Missing 'normal_uncertain' specification"

    def test_has_interface_block(self):
        assert re.search(r'^\s*interface\b', self.lower, re.MULTILINE), \
            "Missing 'interface' block"

    def test_has_fork_interface(self):
        assert 'fork' in self.lower, \
            "Missing 'fork' interface specification"

    def test_has_driver_reference(self):
        assert 'cantilever_driver' in self.lower, \
            "Missing reference to cantilever_driver in interface"

    def test_has_responses_block(self):
        assert re.search(r'^\s*responses\b', self.lower, re.MULTILINE), \
            "Missing 'responses' block"

    def test_has_gradient_specification(self):
        assert 'gradients' in self.lower, \
            "Missing gradient specification in responses"

    def test_design_var_descriptors(self):
        assert ("'w'" in self.content or '"w"' in self.content), \
            "Missing 'w' descriptor"
        assert ("'t'" in self.content or '"t"' in self.content), \
            "Missing 't' descriptor"

    def test_uncertain_var_descriptors(self):
        for var in ['R', 'E', 'X', 'Y']:
            assert (f"'{var}'" in self.content or f'"{var}"' in self.content), \
                f"Missing '{var}' descriptor for uncertain variable"


# ============================================================
# Reliability Analysis Validation Tests (Linear Analytical Case)
# ============================================================

class TestFormValidation:
    """Test reliability analysis against analytical linear test case.
    g(u1,u2) = 5 + 0.6*u1 - 0.8*u2 has exact beta=5.0, MPP=[-3,4].
    """

    @pytest.fixture(autouse=True)
    def load_data(self):
        path = os.path.join(RESULTS_DIR, "form_validation.json")
        assert os.path.exists(path), f"Missing {path}"
        with open(path) as f:
            self.data = json.load(f)

    def test_has_beta_key(self):
        assert "beta" in self.data

    def test_has_mpp_key(self):
        assert "mpp" in self.data

    def test_beta_exact(self):
        assert abs(self.data["beta"] - 5.0) < 1e-3, \
            f"beta = {self.data['beta']}, expected 5.0"

    def test_mpp_dimension(self):
        assert len(self.data["mpp"]) == 2

    def test_mpp_component_0(self):
        assert abs(self.data["mpp"][0] - (-3.0)) < 1e-3, \
            f"MPP[0] = {self.data['mpp'][0]}, expected -3.0"

    def test_mpp_component_1(self):
        assert abs(self.data["mpp"][1] - 4.0) < 1e-3, \
            f"MPP[1] = {self.data['mpp'][1]}, expected 4.0"

    def test_beta_mpp_consistency(self):
        mpp_norm = np.sqrt(self.data["mpp"][0]**2 + self.data["mpp"][1]**2)
        assert abs(self.data["beta"] - mpp_norm) < 1e-3


# ============================================================
# Optimal Design Tests
# ============================================================

class TestOptimalDesign:
    """Test that the RBDO found a valid, well-optimized design."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        path = os.path.join(RESULTS_DIR, "optimal_design.json")
        assert os.path.exists(path), f"Missing {path}"
        with open(path) as f:
            self.data = json.load(f)

    def test_required_keys(self):
        for key in ["w", "t", "area", "beta_stress", "beta_displacement", "algorithm"]:
            assert key in self.data, f"optimal_design.json missing '{key}'"

    def test_algorithm_recognized(self):
        """Verify a recognized constrained optimization algorithm was used."""
        algo = self.data["algorithm"].upper().replace("-", "_").replace(" ", "_")
        recognized = [
            # NLopt gradient-based
            "LD_SLSQP", "LD_MMA", "LD_CCSAQ",
            # NLopt derivative-free
            "LN_COBYLA", "LN_BOBYQA", "LN_NELDERMEAD", "LN_SBPLX",
            # NLopt global
            "GN_ISRES", "GN_DIRECT", "GN_AGS", "AUGLAG",
            # SciPy
            "SLSQP", "COBYLA", "TRUST_CONSTR",
            # General
            "SQP", "SEQUENTIAL_QUADRATIC",
        ]
        assert any(a in algo for a in recognized), \
            f"algorithm '{self.data['algorithm']}' is not a recognized optimization algorithm"

    def test_area_equals_w_times_t(self):
        assert abs(self.data["area"] - self.data["w"] * self.data["t"]) < 0.01

    def test_w_in_bounds(self):
        assert 1.0 <= self.data["w"] <= 10.0

    def test_t_in_bounds(self):
        assert 1.0 <= self.data["t"] <= 10.0

    def test_stress_reliability_satisfied(self):
        assert self.data["beta_stress"] >= 2.95, \
            f"beta_stress = {self.data['beta_stress']}, must be >= 2.95"

    def test_displacement_reliability_satisfied(self):
        assert self.data["beta_displacement"] >= 2.95, \
            f"beta_displacement = {self.data['beta_displacement']}, must be >= 2.95"

    def test_area_improved_from_initial(self):
        assert self.data["area"] < 14.0

    def test_area_physically_reasonable(self):
        assert self.data["area"] > 5.0

    def test_area_well_optimized(self):
        assert self.data["area"] < 13.0

    def test_at_least_one_active_constraint(self):
        min_beta = min(self.data["beta_stress"], self.data["beta_displacement"])
        assert min_beta < 3.5, \
            f"No active constraint (min beta = {min_beta:.3f})"

    def test_independent_mc_stress(self):
        """Independent MC verification of stress at reported optimum."""
        w, t = self.data["w"], self.data["t"]
        rng = np.random.default_rng(12345)
        n = 200000
        R = rng.normal(40000., 2000., n)
        X = rng.normal(500., 100., n)
        Y = rng.normal(1000., 100., n)
        stress = 600 * Y / (w * t**2) + 600 * X / (w**2 * t)
        pf = np.mean(stress >= R)
        assert pf < 0.005, f"Independent MC pf_stress = {pf:.5f}"

    def test_independent_mc_displacement(self):
        """Independent MC verification of displacement at reported optimum."""
        w, t = self.data["w"], self.data["t"]
        rng = np.random.default_rng(12345)
        n = 200000
        E = rng.normal(29e6, 1.45e6, n)
        X = rng.normal(500., 100., n)
        Y = rng.normal(1000., 100., n)
        S = np.sqrt((Y / t**2)**2 + (X / w**2)**2)
        disp_ratio = 4 * 100.**3 * S / (E * w * t * 2.2535)
        pf = np.mean(disp_ratio >= 1.0)
        assert pf < 0.005, f"Independent MC pf_disp = {pf:.5f}"


# ============================================================
# Monte Carlo Validation Tests
# ============================================================

class TestMonteCarlo:
    """Test Monte Carlo validation results."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        path = os.path.join(RESULTS_DIR, "monte_carlo.json")
        assert os.path.exists(path), f"Missing {path}"
        with open(path) as f:
            self.data = json.load(f)

    def test_required_keys(self):
        for key in ["n_samples", "pf_stress", "pf_displacement",
                     "beta_stress_mc", "beta_displacement_mc"]:
            assert key in self.data

    def test_sufficient_samples(self):
        assert self.data["n_samples"] >= 500000

    def test_pf_stress_small(self):
        assert self.data["pf_stress"] < 0.005

    def test_pf_displacement_small(self):
        assert self.data["pf_displacement"] < 0.005

    def test_mc_beta_stress_positive(self):
        assert self.data["beta_stress_mc"] > 2.0

    def test_mc_beta_displacement_positive(self):
        assert self.data["beta_displacement_mc"] > 2.0

    def test_mc_form_stress_consistency(self):
        opt_path = os.path.join(RESULTS_DIR, "optimal_design.json")
        with open(opt_path) as f:
            opt = json.load(f)
        diff = abs(self.data["beta_stress_mc"] - opt["beta_stress"])
        assert diff < 0.8

    def test_mc_form_displacement_consistency(self):
        opt_path = os.path.join(RESULTS_DIR, "optimal_design.json")
        with open(opt_path) as f:
            opt = json.load(f)
        diff = abs(self.data["beta_displacement_mc"] - opt["beta_displacement"])
        assert diff < 0.8


# ============================================================
# Convergence History Tests
# ============================================================

class TestConvergence:
    """Test convergence history format and quality."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        path = os.path.join(RESULTS_DIR, "convergence.csv")
        assert os.path.exists(path), f"Missing {path}"
        with open(path) as f:
            reader = csv.DictReader(f)
            self.rows = list(reader)

    def test_required_columns(self):
        required = {"iteration", "w", "t", "area", "beta_stress", "beta_displacement"}
        actual = set(self.rows[0].keys())
        missing = required - actual
        assert not missing, f"Missing columns: {missing}"

    def test_minimum_iterations(self):
        assert len(self.rows) >= 3

    def test_area_improves(self):
        initial_area = float(self.rows[0]["area"])
        final_area = float(self.rows[-1]["area"])
        assert final_area < initial_area

    def test_values_are_finite_and_positive(self):
        for i, row in enumerate(self.rows):
            for key in ["w", "t", "area", "beta_stress", "beta_displacement"]:
                val = float(row[key])
                assert np.isfinite(val), f"Row {i}, {key} not finite"
                assert val > 0, f"Row {i}, {key} not positive"

    def test_final_constraints_satisfied(self):
        last = self.rows[-1]
        bs = float(last["beta_stress"])
        bd = float(last["beta_displacement"])
        assert bs >= 2.9, f"Final beta_stress = {bs}"
        assert bd >= 2.9, f"Final beta_displacement = {bd}"
