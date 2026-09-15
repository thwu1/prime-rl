"""Tests for quantum entanglement distillation circuits and results."""

import json
import os
import re
import sys
import subprocess
import importlib
import numpy as np
import pytest

RESULTS_PATH = "/app/results.json"
SCENARIOS_PATH = "/app/scenarios.json"
CIRCUITS_DIR = "/app/circuits"
VALIDATOR_PATH = "/app/validate_locc.py"
TOLERANCE = 1e-3

# ---------------------------------------------------------------------------
# Analytical expected values from entanglement distillation theory
# ---------------------------------------------------------------------------
_F1 = 0.80
_F1_out = _F1**2 / (_F1**2 + (1 - _F1)**2)
_p1 = _F1**2 + (1 - _F1)**2
_cs1 = _F1**2

_F3 = 0.75
_F3_out = _F3**3 / (_F3**3 + (1 - _F3)**3)
_p3 = _F3**3 + (1 - _F3)**3
_cs3 = _F3**3

_F5 = 0.70
_F5_out = _F5**5 / (_F5**5 + (1 - _F5)**5)
_p5 = _F5**5 + (1 - _F5)**5
_cs5 = _F5**5

EXPECTED = {
    "S1": {"fidelity": _F1_out, "success_probability": _p1,
           "claim_strength": _cs1, "num_bell_pairs": 2},
    "S2": {"fidelity": _F1_out, "success_probability": _p1,
           "claim_strength": _cs1, "num_bell_pairs": 2},
    "S3": {"fidelity": _F3_out, "success_probability": _p3,
           "claim_strength": _cs3, "num_bell_pairs": 3},
    "S4": {"fidelity": _F3_out, "success_probability": _p3,
           "claim_strength": _cs3, "num_bell_pairs": 3},
    "S5": {"fidelity": _F5_out, "success_probability": _p5,
           "claim_strength": _cs5, "num_bell_pairs": 5},
}

EXPECTED_QUBITS = {
    "S1": 4, "S2": 4, "S3": 6, "S4": 6, "S5": 10,
}


# ---------------------------------------------------------------------------
# Lightweight OpenQASM 3.0 parser (no qiskit dependency)
# ---------------------------------------------------------------------------

def parse_qasm3_file(filepath):
    """Parse an OpenQASM 3.0 file and extract structural properties."""
    with open(filepath) as f:
        content = f.read()

    props = {
        "valid": False,
        "num_qubits": 0,
        "has_measurements": False,
        "has_multi_qubit_gates": False,
    }

    if not re.search(r"OPENQASM\s+3\.0", content):
        return props

    m = re.search(r"qubit\[(\d+)\]\s+\w+", content)
    if not m:
        return props

    props["num_qubits"] = int(m.group(1))
    props["valid"] = True

    # Detect measurement operations (both 'measure q[i]' and 'c[i] = measure q[j]')
    props["has_measurements"] = bool(re.search(r"measure\s+", content))

    # Detect multi-qubit gates by finding lines with 2+ qubit operands
    skip_prefixes = (
        "OPENQASM", "include", "qubit", "bit", "int", "uint",
        "bool", "float", "const", "let", "input", "output",
        "{", "}", "barrier", "reset", "delay", "pragma",
    )
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if any(line.startswith(p) for p in skip_prefixes):
            continue
        if "measure" in line:
            continue
        qubit_refs = re.findall(r"q\[(\d+)\]", line)
        if len(qubit_refs) >= 2:
            props["has_multi_qubit_gates"] = True
            break

    return props


# ===================== Results format tests =====================

class TestResultsFormat:
    """Verify results.json exists and has correct structure."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), \
            "results.json not found at /app/results.json"

    def test_results_valid_json(self):
        with open(RESULTS_PATH) as f:
            results = json.load(f)
        assert isinstance(results, dict)

    def test_all_scenarios_present(self):
        with open(RESULTS_PATH) as f:
            results = json.load(f)
        for key in ["S1", "S2", "S3", "S4", "S5"]:
            assert key in results, f"Missing scenario {key}"

    def test_required_fields(self):
        with open(RESULTS_PATH) as f:
            results = json.load(f)
        required = ["fidelity", "success_probability", "claim_strength",
                     "num_bell_pairs", "meets_threshold"]
        for key in ["S1", "S2", "S3", "S4", "S5"]:
            for field in required:
                assert field in results[key], \
                    f"Missing field '{field}' in {key}"


# ===================== Numerical accuracy tests =====================

class TestFidelityValues:
    """Verify computed fidelities match analytical expectations."""

    @pytest.fixture
    def results(self):
        with open(RESULTS_PATH) as f:
            return json.load(f)

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_fidelity(self, results, scenario):
        expected = EXPECTED[scenario]["fidelity"]
        actual = results[scenario]["fidelity"]
        assert abs(actual - expected) < TOLERANCE, \
            f"{scenario}: fidelity {actual:.6f} != expected {expected:.6f}"

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_success_probability(self, results, scenario):
        expected = EXPECTED[scenario]["success_probability"]
        actual = results[scenario]["success_probability"]
        assert abs(actual - expected) < TOLERANCE, \
            f"{scenario}: success_prob {actual:.6f} != expected {expected:.6f}"

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_claim_strength(self, results, scenario):
        expected = EXPECTED[scenario]["claim_strength"]
        actual = results[scenario]["claim_strength"]
        assert abs(actual - expected) < TOLERANCE, \
            f"{scenario}: claim_strength {actual:.6f} != expected {expected:.6f}"

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_num_bell_pairs(self, results, scenario):
        expected = EXPECTED[scenario]["num_bell_pairs"]
        actual = results[scenario]["num_bell_pairs"]
        assert actual == expected, \
            f"{scenario}: num_bell_pairs {actual} != expected {expected}"

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_meets_threshold(self, results, scenario):
        assert results[scenario]["meets_threshold"] is True, \
            f"{scenario}: must meet fidelity threshold"


# ===================== Consistency tests =====================

class TestClaimStrengthConsistency:
    """Verify claim_strength = fidelity * success_probability."""

    @pytest.fixture
    def results(self):
        with open(RESULTS_PATH) as f:
            return json.load(f)

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_consistency(self, results, scenario):
        f = results[scenario]["fidelity"]
        p = results[scenario]["success_probability"]
        cs = results[scenario]["claim_strength"]
        assert abs(cs - f * p) < 1e-6, \
            f"{scenario}: claim_strength {cs:.8f} != fidelity*prob {f * p:.8f}"


# ===================== Circuit file tests =====================

class TestCircuitFiles:
    """Verify OpenQASM 3.0 circuit files exist and parse correctly."""

    def test_circuits_directory_exists(self):
        assert os.path.isdir(CIRCUITS_DIR), \
            f"Circuit directory {CIRCUITS_DIR} not found"

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_qasm_file_exists(self, scenario):
        path = os.path.join(CIRCUITS_DIR, f"{scenario}.qasm")
        assert os.path.isfile(path), f"QASM file {path} not found"

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_qasm_parses(self, scenario):
        """Circuit must be valid OpenQASM 3.0 with qubit declarations."""
        path = os.path.join(CIRCUITS_DIR, f"{scenario}.qasm")
        props = parse_qasm3_file(path)
        assert props["valid"], f"Failed to parse {path} as valid OpenQASM 3.0"
        assert props["num_qubits"] > 0, f"Circuit in {path} has no qubits"

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_correct_num_qubits(self, scenario):
        """Circuit qubit count must match 2*N for the scenario."""
        path = os.path.join(CIRCUITS_DIR, f"{scenario}.qasm")
        props = parse_qasm3_file(path)
        expected_qubits = EXPECTED_QUBITS[scenario]
        assert props["num_qubits"] == expected_qubits, \
            f"{scenario}: expected {expected_qubits} qubits, " \
            f"got {props['num_qubits']}"

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_circuit_has_measurements(self, scenario):
        """Circuit must include measurement operations on ancilla qubits."""
        path = os.path.join(CIRCUITS_DIR, f"{scenario}.qasm")
        props = parse_qasm3_file(path)
        assert props["has_measurements"], \
            f"{scenario}: circuit must include measurement operations"

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_circuit_has_multi_qubit_gates(self, scenario):
        """Circuit must include two-qubit entangling gates."""
        path = os.path.join(CIRCUITS_DIR, f"{scenario}.qasm")
        props = parse_qasm3_file(path)
        assert props["has_multi_qubit_gates"], \
            f"{scenario}: circuit must include two-qubit gates"


# ===================== LOCC compliance tests =====================

class TestLOCCCompliance:
    """Verify circuits pass LOCC validation using the provided tool."""

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_locc_valid(self, scenario):
        n = EXPECTED[scenario]["num_bell_pairs"]
        qasm_file = os.path.join(CIRCUITS_DIR, f"{scenario}.qasm")
        result = subprocess.run(
            ["python3", VALIDATOR_PATH, qasm_file, str(n)],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"{scenario}: LOCC validation failed:\n{result.stdout}\n{result.stderr}"


# ===================== Simulator module tests =====================

class TestSimulatorModule:
    """Verify simulator.py exists and has correct API."""

    @pytest.fixture(autouse=True)
    def _load_simulator(self):
        sys.path.insert(0, "/app")
        import simulator
        importlib.reload(simulator)
        self.sim = simulator

    def test_simulator_importable(self):
        assert self.sim is not None

    def test_compute_fidelity_function_exists(self):
        assert hasattr(self.sim, "compute_fidelity_phi_plus"), \
            "simulator.py must export compute_fidelity_phi_plus(rho)"

    def test_fidelity_perfect_phi_plus(self):
        """Fidelity of |Phi+> w.r.t. itself must be 1.0."""
        phi_p = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
        rho = np.outer(phi_p, phi_p.conj())
        f = self.sim.compute_fidelity_phi_plus(rho)
        assert abs(f - 1.0) < 1e-10, f"Expected 1.0, got {f}"

    def test_fidelity_phi_minus(self):
        """Fidelity of |Phi-> w.r.t. |Phi+> must be 0."""
        phi_m = np.array([1, 0, 0, -1], dtype=complex) / np.sqrt(2)
        rho = np.outer(phi_m, phi_m.conj())
        f = self.sim.compute_fidelity_phi_plus(rho)
        assert abs(f) < 1e-10, f"Expected 0.0, got {f}"

    def test_fidelity_psi_plus(self):
        """Fidelity of |Psi+> w.r.t. |Phi+> must be 0."""
        psi_p = np.array([0, 1, 1, 0], dtype=complex) / np.sqrt(2)
        rho = np.outer(psi_p, psi_p.conj())
        f = self.sim.compute_fidelity_phi_plus(rho)
        assert abs(f) < 1e-10, f"Expected 0.0, got {f}"

    def test_fidelity_psi_minus(self):
        """Fidelity of |Psi-> w.r.t. |Phi+> must be 0."""
        psi_m = np.array([0, 1, -1, 0], dtype=complex) / np.sqrt(2)
        rho = np.outer(psi_m, psi_m.conj())
        f = self.sim.compute_fidelity_phi_plus(rho)
        assert abs(f) < 1e-10, f"Expected 0.0, got {f}"

    def test_fidelity_maximally_mixed(self):
        """Fidelity of maximally mixed 2-qubit state must be 0.25."""
        rho = np.eye(4, dtype=complex) / 4.0
        f = self.sim.compute_fidelity_phi_plus(rho)
        assert abs(f - 0.25) < 1e-10, f"Expected 0.25, got {f}"

    def test_fidelity_bell_diagonal_mixture(self):
        """Fidelity of 0.8|Phi+> + 0.2|Psi+> must be 0.8."""
        phi_p = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
        psi_p = np.array([0, 1, 1, 0], dtype=complex) / np.sqrt(2)
        rho = 0.8 * np.outer(phi_p, phi_p.conj()) + \
              0.2 * np.outer(psi_p, psi_p.conj())
        f = self.sim.compute_fidelity_phi_plus(rho)
        assert abs(f - 0.8) < 1e-10, f"Expected 0.8, got {f}"

    def test_fidelity_asymmetric_mixture(self):
        """Fidelity of Bell-diagonal [0.70, 0.00, 0.30, 0.00]."""
        phi_p = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
        psi_p = np.array([0, 1, 1, 0], dtype=complex) / np.sqrt(2)
        rho = (0.70 * np.outer(phi_p, phi_p.conj()) +
               0.30 * np.outer(psi_p, psi_p.conj()))
        f = self.sim.compute_fidelity_phi_plus(rho)
        assert abs(f - 0.70) < 1e-10, f"Expected 0.70, got {f}"


# ===================== Threshold sanity tests =====================

class TestThresholds:
    """Verify scenarios use thresholds from scenarios.json."""

    @pytest.fixture
    def results(self):
        with open(RESULTS_PATH) as f:
            return json.load(f)

    @pytest.fixture
    def scenarios(self):
        with open(SCENARIOS_PATH) as f:
            return json.load(f)

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_fidelity_above_threshold(self, results, scenarios, scenario):
        threshold = scenarios[scenario]["threshold"]
        fidelity = results[scenario]["fidelity"]
        assert fidelity >= threshold - 1e-9, \
            f"{scenario}: fidelity {fidelity:.6f} < threshold {threshold}"

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_success_probability_positive(self, results, scenario):
        p = results[scenario]["success_probability"]
        assert p > 0.0, f"{scenario}: success_probability must be > 0"

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_fidelity_bounded(self, results, scenario):
        f = results[scenario]["fidelity"]
        assert 0.0 <= f <= 1.0, f"{scenario}: fidelity {f} out of [0,1]"

    @pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
    def test_success_probability_bounded(self, results, scenario):
        p = results[scenario]["success_probability"]
        assert 0.0 < p <= 1.0, f"{scenario}: prob {p} out of (0,1]"
