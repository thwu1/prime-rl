"""
Tests for quantum heat transport results.

"""

import json
import numpy as np
import pytest
import qutip as qt
from qutip.core.environment import (
    CFExponent, DrudeLorentzEnvironment, system_terminator
)
from qutip.solver.heom import HEOMSolver


# ── System constants (must match instruction) ──────────────────────────────

EPSILON = 1.0
J12 = 0.05
GAMMA = 3.0
T_HOT = 2.5
T_COLD = 1.5
NK = 1
NC = 7
EXPECTED_LAMBDAS = [0.005, 0.0125, 0.025, 0.05, 0.1, 0.2]
REF_LAMBDA = 0.025


# ── Helpers ─────────────────────────────────────────────────────────────────

def _build_system():
    H1 = (EPSILON / 2) * qt.tensor(
        qt.sigmaz() + qt.identity(2), qt.identity(2)
    )
    H2 = (EPSILON / 2) * qt.tensor(
        qt.identity(2), qt.sigmaz() + qt.identity(2)
    )
    H12 = J12 * (
        qt.tensor(qt.sigmap(), qt.sigmam())
        + qt.tensor(qt.sigmam(), qt.sigmap())
    )
    return H1 + H2 + H12


def _bhc(tag, ados, H, Q, delta):
    """Bath heat current from level-1 ADOs."""
    labels = ados.filter(level=1, tags=[tag])
    a = 1j * (H * Q - Q * H)
    r = 0.0
    cI0 = 0.0
    for label in labels:
        [e] = ados.exps(label)
        r += e.vk * (Q * ados.extract(label)).tr()
        if e.type == CFExponent.types["I"]:
            cI0 += e.ck
        elif e.type == CFExponent.types["RI"]:
            cI0 += e.ck2
    r -= 2 * cI0 * (Q * Q * ados.rho).tr()
    if delta != 0:
        r -= 1j * delta * ((a * Q - Q * a) * ados.rho).tr()
    return r


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference():
    """Independent computation at lambda=0.025."""
    H_S = _build_system()
    Q1 = qt.tensor(qt.sigmax(), qt.identity(2))
    Q2 = qt.tensor(qt.identity(2), qt.sigmax())

    env1 = DrudeLorentzEnvironment(
        lam=REF_LAMBDA, gamma=GAMMA, T=T_HOT, tag="b1"
    )
    env2 = DrudeLorentzEnvironment(
        lam=REF_LAMBDA, gamma=GAMMA, T=T_COLD, tag="b2"
    )
    ea1, d1 = env1.approx_by_pade(Nk=NK, compute_delta=True, tag="b1")
    ea2, d2 = env2.approx_by_pade(Nk=NK, compute_delta=True, tag="b2")

    solver = HEOMSolver(
        qt.liouvillian(H_S) + system_terminator(Q1, d1)
        + system_terminator(Q2, d2),
        [(ea1, Q1), (ea2, Q2)],
        max_depth=NC,
    )
    _, ados = solver.steady_state()

    jB1 = float(np.real(_bhc("b1", ados, H_S, Q1, d1)))
    jB2 = float(np.real(_bhc("b2", ados, H_S, Q2, d2)))
    sz1 = float(np.real(
        (qt.tensor(qt.sigmaz(), qt.identity(2)) * ados.rho).tr()
    ))
    return {"j_B1": jB1, "j_B2": jB2, "sz1": sz1}


# ── Structure tests ─────────────────────────────────────────────────────────

class TestStructure:
    def test_required_keys(self, results):
        for key in [
            "heat_currents", "steady_state_sigma_z1",
            "peak_lambda", "peak_current_abs", "energy_conservation_error",
        ]:
            assert key in results, f"Missing key: {key}"

    def test_heat_currents_count(self, results):
        assert len(results["heat_currents"]) == 6

    def test_heat_currents_lambdas(self, results):
        for i, entry in enumerate(results["heat_currents"]):
            assert "lambda" in entry
            assert "j_B1_real" in entry
            assert "j_B2_real" in entry
            assert abs(entry["lambda"] - EXPECTED_LAMBDAS[i]) < 1e-10, (
                f"Expected lambda={EXPECTED_LAMBDAS[i]}, got {entry['lambda']}"
            )


# ── Physical constraint tests ───────────────────────────────────────────────

class TestPhysics:
    def test_hot_bath_loses_energy(self, results):
        """j_B^1 < 0: energy leaves the hot bath."""
        for e in results["heat_currents"]:
            assert e["j_B1_real"] < 0, (
                f"Hot-bath current must be negative at lam={e['lambda']}"
            )

    def test_cold_bath_gains_energy(self, results):
        """j_B^2 > 0: energy enters the cold bath."""
        for e in results["heat_currents"]:
            assert e["j_B2_real"] > 0, (
                f"Cold-bath current must be positive at lam={e['lambda']}"
            )

    def test_energy_conservation(self, results):
        """Relative energy-conservation error must be small."""
        assert results["energy_conservation_error"] < 0.01

    def test_turnover_present(self, results):
        """Current must be non-monotonic (turnover behavior)."""
        c = [abs(e["j_B1_real"]) for e in results["heat_currents"]]
        assert c[0] < max(c), "Weakest coupling should not be the peak"
        assert c[-1] < max(c), "Strongest coupling should not be the peak"

    def test_sigma_z1_thermal_range(self, results):
        sz = results["steady_state_sigma_z1"]
        assert -1.0 <= sz <= 0.0, f"sigma_z^1 = {sz} is out of range"

    def test_peak_in_range(self, results):
        pl = results["peak_lambda"]
        assert 0.005 < pl < 0.2, f"peak_lambda={pl} outside expected range"


# ── Numerical accuracy (against independent computation) ─────────────────

class TestAccuracy:
    def test_sigma_z1(self, results, reference):
        assert np.isclose(
            results["steady_state_sigma_z1"],
            reference["sz1"],
            rtol=0.05,
        ), (
            f"sigma_z1 mismatch: got {results['steady_state_sigma_z1']}, "
            f"expected {reference['sz1']}"
        )

    def test_j_B1_at_ref_lambda(self, results, reference):
        entry = [
            e for e in results["heat_currents"]
            if abs(e["lambda"] - REF_LAMBDA) < 1e-10
        ]
        assert len(entry) == 1, "Missing lambda=0.025 entry"
        assert np.isclose(
            entry[0]["j_B1_real"], reference["j_B1"], rtol=0.05
        ), (
            f"j_B1 mismatch at lam=0.025: got {entry[0]['j_B1_real']}, "
            f"expected {reference['j_B1']}"
        )

    def test_j_B2_at_ref_lambda(self, results, reference):
        entry = [
            e for e in results["heat_currents"]
            if abs(e["lambda"] - REF_LAMBDA) < 1e-10
        ]
        assert len(entry) == 1
        assert np.isclose(
            entry[0]["j_B2_real"], reference["j_B2"], rtol=0.05
        ), (
            f"j_B2 mismatch at lam=0.025: got {entry[0]['j_B2_real']}, "
            f"expected {reference['j_B2']}"
        )

    def test_reference_conservation(self, reference):
        """Sanity: the reference computation itself must conserve energy."""
        j1, j2 = reference["j_B1"], reference["j_B2"]
        assert abs(j1 + j2) < 0.01 * abs(j1), (
            f"Reference energy conservation failed: j1={j1}, j2={j2}"
        )
