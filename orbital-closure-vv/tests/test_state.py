
"""
Tests for the GMAT Mission Script Propagation Cross-Validation framework.
Verifies GMAT script parsing, closure test results, conservation laws,
RAAN precession, and Octave cross-validation.
"""

import json
import os
import glob
import re
import math

RESULTS_PATH = "/app/results.json"
OCTAVE_OUTPUT = "/app/octave_results.txt"

# Expected values from the GMAT scripts (ground truth for parsing verification)
EXPECTED_MISSIONS = {
    "LEO_ISS": {
        "initial_state": [-4453.78359, -5038.20376, -426.384456, 3.831888, -2.887221, -6.018232],
        "gravity_degree": 4,
        "gravity_order": 0,
        "duration_days": 1.0,
        "integrator_type": "RungeKutta89",
        "accuracy": 1e-12,
    },
    "GEO_comsat": {
        "initial_state": [36607.35826, -20921.7237, 0.0, 1.525636, 2.669451, 0.0],
        "gravity_degree": 0,
        "gravity_order": 0,
        "duration_days": 7.0,
        "integrator_type": "PrinceDormand78",
        "accuracy": 1e-12,
    },
    "HEO_molniya": {
        "initial_state": [-1529.89429, -2672.87736, -6150.11534, 8.717518, -4.989709, 0.0],
        "gravity_degree": 2,
        "gravity_order": 0,
        "duration_days": 3.0,
        "integrator_type": "PrinceDormand78",
        "accuracy": 1e-12,
    },
    "MEO_gps": {
        "initial_state": [5525.33668, -15871.1849, -20998.9924, 2.750341, 2.434198, -1.068884],
        "gravity_degree": 3,
        "gravity_order": 0,
        "duration_days": 2.0,
        "integrator_type": "RungeKutta89",
        "accuracy": 1e-12,
    },
}


def load_results():
    assert os.path.exists(RESULTS_PATH), f"results.json not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestResultsStructure:
    """Verify results.json has the required top-level keys and structure."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_top_level_keys(self):
        data = load_results()
        required = [
            "parsed_missions",
            "closure_tests",
            "conservation",
            "raan_precession",
            "integrator_info",
        ]
        for key in required:
            assert key in data, f"Missing top-level key: {key}"

    def test_all_missions_present_in_parsed(self):
        data = load_results()
        for name in EXPECTED_MISSIONS:
            assert name in data["parsed_missions"], (
                f"Missing mission {name} in parsed_missions"
            )

    def test_all_missions_present_in_closure(self):
        data = load_results()
        for name in EXPECTED_MISSIONS:
            assert name in data["closure_tests"], (
                f"Missing mission {name} in closure_tests"
            )


class TestGMATScriptParsing:
    """Verify that GMAT scripts were correctly parsed."""

    def _check_state(self, mission_name):
        data = load_results()
        parsed = data["parsed_missions"][mission_name]
        expected = EXPECTED_MISSIONS[mission_name]
        state = parsed["initial_state"]
        assert isinstance(state, list), f"{mission_name}: initial_state must be a list"
        assert len(state) == 6, f"{mission_name}: initial_state must have 6 elements"
        for i, (got, exp) in enumerate(zip(state, expected["initial_state"])):
            assert abs(got - exp) < 1e-4, (
                f"{mission_name}: state[{i}] = {got}, expected {exp}"
            )

    def _check_gravity(self, mission_name):
        data = load_results()
        parsed = data["parsed_missions"][mission_name]
        expected = EXPECTED_MISSIONS[mission_name]
        assert parsed["gravity_degree"] == expected["gravity_degree"], (
            f"{mission_name}: gravity_degree = {parsed['gravity_degree']}, "
            f"expected {expected['gravity_degree']}"
        )
        assert parsed["gravity_order"] == expected["gravity_order"], (
            f"{mission_name}: gravity_order = {parsed['gravity_order']}, "
            f"expected {expected['gravity_order']}"
        )

    def _check_duration(self, mission_name):
        data = load_results()
        parsed = data["parsed_missions"][mission_name]
        expected = EXPECTED_MISSIONS[mission_name]
        assert abs(parsed["duration_days"] - expected["duration_days"]) < 1e-6, (
            f"{mission_name}: duration = {parsed['duration_days']}, "
            f"expected {expected['duration_days']}"
        )

    def _check_integrator(self, mission_name):
        data = load_results()
        parsed = data["parsed_missions"][mission_name]
        expected = EXPECTED_MISSIONS[mission_name]
        # Allow case-insensitive match and common abbreviations
        got_type = parsed["integrator_type"].lower().replace("_", "").replace("-", "").replace(" ", "")
        exp_type = expected["integrator_type"].lower().replace("_", "").replace("-", "").replace(" ", "")
        assert got_type == exp_type, (
            f"{mission_name}: integrator_type = {parsed['integrator_type']}, "
            f"expected {expected['integrator_type']}"
        )

    def test_leo_state(self):
        self._check_state("LEO_ISS")

    def test_geo_state(self):
        self._check_state("GEO_comsat")

    def test_heo_state(self):
        self._check_state("HEO_molniya")

    def test_meo_state(self):
        self._check_state("MEO_gps")

    def test_leo_gravity(self):
        self._check_gravity("LEO_ISS")

    def test_geo_gravity(self):
        self._check_gravity("GEO_comsat")

    def test_heo_gravity(self):
        self._check_gravity("HEO_molniya")

    def test_meo_gravity(self):
        self._check_gravity("MEO_gps")

    def test_leo_duration(self):
        self._check_duration("LEO_ISS")

    def test_geo_duration(self):
        self._check_duration("GEO_comsat")

    def test_heo_duration(self):
        self._check_duration("HEO_molniya")

    def test_meo_duration(self):
        self._check_duration("MEO_gps")

    def test_leo_integrator(self):
        self._check_integrator("LEO_ISS")

    def test_geo_integrator(self):
        self._check_integrator("GEO_comsat")

    def test_drag_srp_off(self):
        """All scripts have Drag=None and SRP=Off."""
        data = load_results()
        for name in EXPECTED_MISSIONS:
            parsed = data["parsed_missions"][name]
            drag = parsed.get("drag_model")
            assert drag is None or drag == "None" or drag == "none" or drag == "", (
                f"{name}: drag_model should be None/disabled, got {drag}"
            )
            srp = parsed.get("srp_enabled")
            assert srp is False or srp == "Off" or srp == "off" or srp is None, (
                f"{name}: srp_enabled should be False/Off, got {srp}"
            )


class TestClosureTests:
    """
    Forward-backward closure tests. Threshold varies by regime and force model.
    """

    def test_geo_twobody_closure(self):
        """GEO with point-mass gravity: sub-meter closure expected."""
        data = load_results()
        err = data["closure_tests"]["GEO_comsat"]["error_km"]
        assert isinstance(err, (int, float)), "error_km must be numeric"
        assert err >= 0, "Closure error must be non-negative"
        assert err < 0.001, (
            f"GEO two-body closure error {err:.2e} km >= 0.001 km"
        )

    def test_leo_perturbed_closure(self):
        """LEO with J2-J4 zonal: moderate closure error expected."""
        data = load_results()
        err = data["closure_tests"]["LEO_ISS"]["error_km"]
        assert err >= 0
        assert err < 0.01, (
            f"LEO perturbed closure {err:.2e} km >= 0.01 km"
        )

    def test_heo_j2_closure(self):
        """HEO with J2-only: high eccentricity makes this harder."""
        data = load_results()
        err = data["closure_tests"]["HEO_molniya"]["error_km"]
        assert err >= 0
        assert err < 0.5, (
            f"HEO J2 closure {err:.2e} km >= 0.5 km"
        )

    def test_meo_perturbed_closure(self):
        """MEO with J2+J3 zonal harmonics."""
        data = load_results()
        err = data["closure_tests"]["MEO_gps"]["error_km"]
        assert err >= 0
        assert err < 0.01, (
            f"MEO perturbed closure {err:.2e} km >= 0.01 km"
        )


class TestConservation:
    """
    Two-body dynamics conserve specific orbital energy and angular momentum.
    Only the GEO case uses point-mass-only gravity (Degree=0).
    """

    def test_conservation_reported_for_pointmass(self):
        """Conservation must be reported for the GEO (point-mass) case."""
        data = load_results()
        cons = data["conservation"]
        assert len(cons) > 0, "No conservation data reported"
        # Should have GEO_comsat (the only Degree=0 mission)
        assert "GEO_comsat" in cons, (
            "Conservation not reported for GEO_comsat (the point-mass mission)"
        )

    def test_energy_conservation(self):
        data = load_results()
        err = abs(data["conservation"]["GEO_comsat"]["energy_relative_error"])
        assert err < 1e-8, (
            f"Energy relative error {err:.2e} >= 1e-8"
        )

    def test_angular_momentum_conservation(self):
        data = load_results()
        err = abs(data["conservation"]["GEO_comsat"]["angular_momentum_relative_error"])
        assert err < 1e-8, (
            f"Angular momentum relative error {err:.2e} >= 1e-8"
        )


class TestRAANPrecession:
    """
    RAAN precession for LEO_ISS under J2-J4 perturbation.
    Analytical first-order J2: dOmega/dt = -3/2 * n * J2 * (Re/a)^2 * cos(i)
    For a~6738 km, i~51.6 deg: approximately -5.1 deg/day.
    Allow 5% tolerance for higher-order effects.
    """

    def test_raan_mission_identified(self):
        data = load_results()
        raan = data["raan_precession"]
        assert "mission_name" in raan, "raan_precession must specify mission_name"
        assert raan["mission_name"] == "LEO_ISS", (
            f"RAAN mission should be LEO_ISS, got {raan['mission_name']}"
        )

    def test_raan_analytical_value(self):
        data = load_results()
        analytical = data["raan_precession"]["analytical_deg_per_day"]
        assert -7.0 < analytical < -3.0, (
            f"Analytical RAAN rate {analytical} deg/day out of expected range"
        )

    def test_raan_numerical_value(self):
        data = load_results()
        numerical = data["raan_precession"]["numerical_deg_per_day"]
        assert numerical < 0, "RAAN precession should be retrograde (negative)"
        assert -7.0 < numerical < -3.0, (
            f"Numerical RAAN rate {numerical} deg/day out of expected range"
        )

    def test_raan_relative_error(self):
        data = load_results()
        rel_err = abs(data["raan_precession"]["relative_error_percent"])
        assert rel_err < 5.0, (
            f"RAAN relative error {rel_err:.2f}% >= 5%"
        )

    def test_raan_self_consistency(self):
        data = load_results()
        raan = data["raan_precession"]
        num = raan["numerical_deg_per_day"]
        ana = raan["analytical_deg_per_day"]
        reported = raan["relative_error_percent"]
        if abs(ana) > 1e-12:
            computed = abs((num - ana) / ana) * 100.0
            assert abs(computed - abs(reported)) < 1.0, (
                f"Reported error {reported}% inconsistent with "
                f"computed {computed:.2f}%"
            )


class TestOctaveValidation:
    """Verify that GNU Octave was used for analytical cross-validation."""

    def test_octave_output_exists(self):
        assert os.path.exists(OCTAVE_OUTPUT), (
            f"Octave output file not found at {OCTAVE_OUTPUT}"
        )

    def test_octave_output_has_markers(self):
        with open(OCTAVE_OUTPUT) as f:
            content = f.read()
        assert "ORBITAL_ANALYSIS_RESULTS" in content, (
            "Octave output missing ORBITAL_ANALYSIS_RESULTS marker"
        )
        assert "ANALYSIS_COMPLETE" in content, (
            "Octave output missing ANALYSIS_COMPLETE marker"
        )

    def test_octave_has_raan_value(self):
        with open(OCTAVE_OUTPUT) as f:
            content = f.read()
        assert "raan_precession_deg_day=" in content, (
            "Octave output missing raan_precession_deg_day"
        )

    def test_octave_raan_is_physical(self):
        """Extract RAAN rate from Octave output and check it's physical."""
        with open(OCTAVE_OUTPUT) as f:
            content = f.read()
        m = re.search(r"raan_precession_deg_day=([-\d.eE+]+)", content)
        assert m, "Could not parse raan_precession_deg_day from Octave output"
        octave_raan = float(m.group(1))
        assert -7.0 < octave_raan < -3.0, (
            f"Octave RAAN rate {octave_raan} deg/day out of expected range"
        )

    def test_octave_value_in_results(self):
        """Verify results.json contains octave_analytical_deg_per_day."""
        data = load_results()
        raan = data["raan_precession"]
        assert "octave_analytical_deg_per_day" in raan, (
            "results.json missing octave_analytical_deg_per_day"
        )

    def test_octave_value_consistency(self):
        """Octave value in results.json must match what's in octave_results.txt."""
        data = load_results()
        octave_from_json = data["raan_precession"]["octave_analytical_deg_per_day"]

        with open(OCTAVE_OUTPUT) as f:
            content = f.read()
        m = re.search(r"raan_precession_deg_day=([-\d.eE+]+)", content)
        assert m, "Could not parse raan_precession_deg_day from Octave output"
        octave_from_file = float(m.group(1))

        assert abs(octave_from_json - octave_from_file) < 0.01, (
            f"Octave RAAN in results.json ({octave_from_json}) differs from "
            f"octave_results.txt ({octave_from_file})"
        )

    def test_octave_script_filled_in(self):
        """Verify an Octave .m file exists at /app/ with filled-in state values."""
        m_files = glob.glob("/app/*.m")
        assert len(m_files) > 0, "No .m files found at /app/"
        found_filled = False
        for fpath in m_files:
            with open(fpath) as f:
                content = f.read()
            # The template has X0 = 0.0 — a filled script should have actual values
            if "4453" in content or "-4453" in content:
                found_filled = True
                break
        assert found_filled, (
            "No Octave script found with LEO_ISS state values filled in"
        )


class TestIntegratorInfo:
    """Verify integrator metadata."""

    def test_order_at_least_5(self):
        data = load_results()
        order = data["integrator_info"]["order"]
        assert isinstance(order, int), "order must be an integer"
        assert order >= 5, f"Integrator order {order} < 5"

    def test_reasonable_step_count(self):
        data = load_results()
        steps = data["integrator_info"]["total_steps_all_cases"]
        assert isinstance(steps, int)
        assert steps > 100, f"Suspiciously low step count: {steps}"
        assert steps < 10_000_000, f"Suspiciously high step count: {steps}"

    def test_reasonable_function_evals(self):
        data = load_results()
        evals = data["integrator_info"]["total_function_evals"]
        assert isinstance(evals, int)
        assert evals > 500, f"Suspiciously low function eval count: {evals}"


class TestNoForbiddenImports:
    """
    Verify that no Python files under /app/ import forbidden ODE-solver
    libraries. The task requires a custom integrator implementation.
    """

    FORBIDDEN_PATTERNS = [
        r"from\s+scipy\.integrate\s+import",
        r"from\s+scipy\s+import\s+integrate",
        r"import\s+scipy\.integrate",
        r"from\s+diffeq",
        r"import\s+diffeq",
        r"from\s+torchdiffeq",
        r"import\s+torchdiffeq",
        r"odeint\s*\(",
        r"solve_ivp\s*\(",
    ]

    def test_no_forbidden_imports(self):
        py_files = glob.glob("/app/**/*.py", recursive=True)
        violations = []
        for fpath in py_files:
            try:
                with open(fpath) as f:
                    content = f.read()
                for pattern in self.FORBIDDEN_PATTERNS:
                    if re.search(pattern, content):
                        violations.append(
                            f"{fpath}: matches forbidden pattern '{pattern}'"
                        )
            except Exception:
                pass
        assert not violations, (
            "Forbidden ODE-solver imports found:\n" + "\n".join(violations)
        )
