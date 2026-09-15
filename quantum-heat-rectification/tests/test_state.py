"""Verify thermal rectification results from HEOM computation."""

import json
import os

import numpy as np
import pytest
import qutip as qt
from qutip.core.environment import (
    CFExponent,
    DrudeLorentzEnvironment,
    system_terminator,
)
from qutip.solver.heom import HEOMSolver


# ---------------------------------------------------------------------------
# Helper functions for independent verification
# ---------------------------------------------------------------------------

def build_hamiltonian(epsilon, J12):
    """Build the two-qubit system Hamiltonian."""
    H1 = epsilon / 2 * qt.tensor(qt.sigmaz() + qt.identity(2), qt.identity(2))
    H2 = epsilon / 2 * qt.tensor(qt.identity(2), qt.sigmaz() + qt.identity(2))
    H12 = J12 * (
        qt.tensor(qt.sigmap(), qt.sigmam())
        + qt.tensor(qt.sigmam(), qt.sigmap())
    )
    return H1 + H2 + H12


def bath_heat_current(bath_tag, ado_state, hamiltonian, coupling_op, delta=0):
    """Extract bath heat current j_B^K = d/dt <H_B^K> from level-1 ADOs."""
    l1_labels = ado_state.filter(level=1, tags=[bath_tag])
    a_op = 1j * (hamiltonian * coupling_op - coupling_op * hamiltonian)

    result = 0
    cI0 = 0
    for label in l1_labels:
        [exp] = ado_state.exps(label)
        result += exp.vk * (coupling_op * ado_state.extract(label)).tr()
        if exp.type == CFExponent.types["I"]:
            cI0 += exp.ck
        elif exp.type == CFExponent.types["RI"]:
            cI0 += exp.ck2

    result -= 2 * cI0 * (coupling_op * coupling_op * ado_state.rho).tr()
    if delta != 0:
        result -= (
            1j
            * delta
            * ((a_op * coupling_op - coupling_op * a_op) * ado_state.rho).tr()
        )
    return result


def compute_reference(epsilon, J12, gamma, T1, T2, lam1, lam2, Nk, NC):
    """Run an independent HEOM steady-state computation and return (j1, j2)."""
    H = build_hamiltonian(epsilon, J12)
    Q1 = qt.tensor(qt.sigmax(), qt.identity(2))
    Q2 = qt.tensor(qt.identity(2), qt.sigmax())

    env1 = DrudeLorentzEnvironment(lam=lam1, gamma=gamma, T=T1, tag="bath1")
    env1_approx, delta1 = env1.approximate(
        "pade", Nk=Nk, compute_delta=True, tag="bath1"
    )

    env2 = DrudeLorentzEnvironment(lam=lam2, gamma=gamma, T=T2, tag="bath2")
    env2_approx, delta2 = env2.approximate(
        "pade", Nk=Nk, compute_delta=True, tag="bath2"
    )

    Ltot = (
        qt.liouvillian(H)
        + system_terminator(Q1, delta1)
        + system_terminator(Q2, delta2)
    )

    options = {
        "nsteps": 15000,
        "store_states": True,
        "rtol": 1e-12,
        "atol": 1e-12,
        "method": "vern9",
    }

    solver = HEOMSolver(
        Ltot,
        [(env1_approx, Q1), (env2_approx, Q2)],
        max_depth=NC,
        options=options,
    )

    _, steady_ados = solver.steady_state()

    j1 = float(np.real(bath_heat_current("bath1", steady_ados, H, Q1, delta1)))
    j2 = float(np.real(bath_heat_current("bath2", steady_ados, H, Q2, delta2)))
    return j1, j2


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PARAMS_PATH = "/app/system_params.json"
RESULTS_DIR = "/app/results"


@pytest.fixture(scope="module")
def params():
    with open(PARAMS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def currents():
    with open(os.path.join(RESULTS_DIR, "steady_state_currents.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def rectification():
    with open(os.path.join(RESULTS_DIR, "rectification.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def conservation():
    with open(os.path.join(RESULTS_DIR, "energy_conservation.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference_alpha2(params):
    """Pre-compute reference HEOM results for alpha=2.0 (used by spot-check)."""
    p = params
    lam1 = p["lam_base"]
    lam2 = 2.0 * p["lam_base"]

    j1_fwd, j2_fwd = compute_reference(
        p["epsilon"], p["J12"], p["gamma"],
        p["T_hot"], p["T_cold"], lam1, lam2,
        p["Nk"], p["NC"],
    )
    j1_rev, j2_rev = compute_reference(
        p["epsilon"], p["J12"], p["gamma"],
        p["T_cold"], p["T_hot"], lam1, lam2,
        p["Nk"], p["NC"],
    )
    return {
        "J_fwd": abs(j1_fwd),
        "J_rev": abs(j1_rev),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_output_files_exist():
    """All three required output files must be present."""
    assert os.path.isfile(os.path.join(RESULTS_DIR, "steady_state_currents.json"))
    assert os.path.isfile(os.path.join(RESULTS_DIR, "rectification.json"))
    assert os.path.isfile(os.path.join(RESULTS_DIR, "energy_conservation.json"))


def test_currents_structure(currents, params):
    """steady_state_currents.json must have correct keys and types."""
    ratios = [str(r) for r in params["asymmetry_ratios"]]
    for r in ratios:
        assert r in currents, f"Missing ratio {r} in steady_state_currents"
        assert "j_forward" in currents[r], f"Missing j_forward for ratio {r}"
        assert "j_reverse" in currents[r], f"Missing j_reverse for ratio {r}"
        assert isinstance(currents[r]["j_forward"], (int, float))
        assert isinstance(currents[r]["j_reverse"], (int, float))


def test_rectification_structure(rectification, params):
    """rectification.json must have an entry for every ratio."""
    for r in [str(a) for a in params["asymmetry_ratios"]]:
        assert r in rectification, f"Missing ratio {r} in rectification"
        assert isinstance(rectification[r], (int, float))


def test_positive_currents(currents, params):
    """Through-current magnitudes must be strictly positive."""
    for r in [str(a) for a in params["asymmetry_ratios"]]:
        assert currents[r]["j_forward"] > 0, (
            f"j_forward must be > 0 for alpha={r}, got {currents[r]['j_forward']}"
        )
        assert currents[r]["j_reverse"] > 0, (
            f"j_reverse must be > 0 for alpha={r}, got {currents[r]['j_reverse']}"
        )


def test_energy_conservation(conservation, params):
    """Relative energy conservation error must be < 1% for all configurations."""
    for r in [str(a) for a in params["asymmetry_ratios"]]:
        assert r in conservation, f"Missing ratio {r} in energy_conservation"
        assert conservation[r]["forward"] < 0.01, (
            f"Forward energy conservation error too large for alpha={r}: "
            f"{conservation[r]['forward']}"
        )
        assert conservation[r]["reverse"] < 0.01, (
            f"Reverse energy conservation error too large for alpha={r}: "
            f"{conservation[r]['reverse']}"
        )


def test_symmetry_case(rectification):
    """For symmetric coupling (alpha=1.0), rectification must be near zero."""
    assert abs(rectification["1.0"]) < 0.02, (
        f"Rectification for alpha=1.0 should be ~0, got {rectification['1.0']}"
    )


def test_rectification_consistency(currents, rectification, params):
    """R = (J_fwd - J_rev) / max(J_fwd, J_rev) must match reported values."""
    for r in [str(a) for a in params["asymmetry_ratios"]]:
        j_fwd = currents[r]["j_forward"]
        j_rev = currents[r]["j_reverse"]
        max_j = max(j_fwd, j_rev)
        expected_R = (j_fwd - j_rev) / max_j if max_j > 0 else 0.0
        np.testing.assert_allclose(
            rectification[r],
            expected_R,
            atol=1e-10,
            err_msg=f"Rectification inconsistent with currents for alpha={r}",
        )


def test_spot_check_alpha_2(currents, reference_alpha2):
    """Verify currents for alpha=2.0 against independent HEOM computation."""
    np.testing.assert_allclose(
        currents["2.0"]["j_forward"],
        reference_alpha2["J_fwd"],
        rtol=1e-3,
        err_msg="Forward current mismatch for alpha=2.0",
    )
    np.testing.assert_allclose(
        currents["2.0"]["j_reverse"],
        reference_alpha2["J_rev"],
        rtol=1e-3,
        err_msg="Reverse current mismatch for alpha=2.0",
    )
