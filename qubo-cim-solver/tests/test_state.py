"""Tests for solver portfolio evaluation: verdict, existence, self-consistency, solution quality."""
import json
import os

import numpy as np
import pytest


INSTANCE_DIR = "/app/instances"
RESULT_DIR = "/app/results"

ALL_INSTANCES = [
    "ising_chain", "ising_frustrated", "ising_sk20", "ising_chimera",
    "qubo_maxcut", "qubo_partition",
]
ISING_INSTANCES = ["ising_chain", "ising_frustrated", "ising_sk20", "ising_chimera"]
QUBO_INSTANCES = ["qubo_maxcut", "qubo_partition"]


def load_json(path):
    with open(path) as f:
        return json.load(f)


def _find_verdict_entry(verdict, name):
    """Find a verdict entry by solver name, tolerant of key formatting."""
    for key, val in verdict.items():
        k = key.lower().replace("solver_", "").replace("solver-", "").replace("solver ", "").strip()
        if k == name:
            return val
    pytest.fail(f"No entry for solver '{name}' found in verdict.json")


def ising_energy_from_lists(spins, couplings, fields):
    """Compute H = sum_{(i,j)} J_ij s_i s_j + sum_i h_i s_i."""
    e = sum(J * spins[int(i)] * spins[int(j)] for i, j, J in couplings)
    e += sum(h * s for h, s in zip(fields, spins))
    return e


def qubo_energy_from_bits(bits, Q):
    """Compute E = sum_i Q_ii x_i + sum_{i<j} Q_ij x_i x_j (Q upper-triangular)."""
    n = len(bits)
    e = sum(Q[i][i] * bits[i] for i in range(n))
    e += sum(Q[i][j] * bits[i] * bits[j] for i in range(n) for j in range(i + 1, n))
    return e


def brute_force_ising_ground(n, couplings, fields):
    """Find Ising ground state energy by exhaustive enumeration (vectorised)."""
    J_mat = np.zeros((n, n))
    for i, j, Jij in couplings:
        J_mat[int(i)][int(j)] = Jij
        J_mat[int(j)][int(i)] = Jij
    h_vec = np.array(fields, dtype=np.float64)

    best = float("inf")
    chunk = 1 << min(n, 18)
    total = 1 << n
    for start in range(0, total, chunk):
        end = min(start + chunk, total)
        bits_range = np.arange(start, end, dtype=np.int64)
        configs = np.zeros((end - start, n), dtype=np.float64)
        for j in range(n):
            configs[:, j] = 2.0 * ((bits_range >> j) & 1) - 1.0
        ce = np.sum((configs @ J_mat) * configs, axis=1) / 2.0
        fe = configs @ h_vec
        chunk_min = float(np.min(ce + fe))
        if chunk_min < best:
            best = chunk_min
    return best


def brute_force_qubo_ground(n, Q):
    """Find QUBO ground state energy by exhaustive enumeration."""
    Q_arr = np.array(Q, dtype=np.float64)
    total = 1 << n
    bits_range = np.arange(total, dtype=np.int64)
    configs = np.zeros((total, n), dtype=np.float64)
    for j in range(n):
        configs[:, j] = ((bits_range >> j) & 1).astype(np.float64)
    energies = np.sum((configs @ Q_arr) * configs, axis=1)
    return float(np.min(energies))


# ---------------------------------------------------------------------------
# Verdict evaluation tests — evaluates the agent's solver assessment
# ---------------------------------------------------------------------------
class TestVerdict:
    def test_verdict_exists(self):
        assert os.path.isfile("/app/verdict.json"), \
            "verdict.json not found at /app/verdict.json"

    def test_verdict_has_all_solvers(self):
        verdict = load_json("/app/verdict.json")
        found = set()
        for key in verdict:
            k = key.lower().replace("solver_", "").replace("solver-", "").replace("solver ", "").strip()
            if k in ("alpha", "beta", "gamma"):
                found.add(k)
        assert found == {"alpha", "beta", "gamma"}, \
            f"verdict must evaluate all three solvers; found: {found}"

    def test_all_solvers_identified_as_defective(self):
        verdict = load_json("/app/verdict.json")
        for name in ("alpha", "beta", "gamma"):
            entry = _find_verdict_entry(verdict, name)
            assert entry.get("has_defects") is True, \
                f"solver {name} should be identified as having defects"

    def test_alpha_energy_computation_defect(self):
        verdict = load_json("/app/verdict.json")
        entry = _find_verdict_entry(verdict, "alpha")
        cats = entry.get("defect_categories", [])
        assert "energy_computation" in cats, \
            f"alpha defect_categories should include 'energy_computation'; got {cats}"

    def test_beta_local_search_defect(self):
        verdict = load_json("/app/verdict.json")
        entry = _find_verdict_entry(verdict, "beta")
        cats = entry.get("defect_categories", [])
        assert "local_search" in cats, \
            f"beta defect_categories should include 'local_search'; got {cats}"

    def test_gamma_dynamics_parameters_defect(self):
        verdict = load_json("/app/verdict.json")
        entry = _find_verdict_entry(verdict, "gamma")
        cats = entry.get("defect_categories", [])
        assert "dynamics_parameters" in cats, \
            f"gamma defect_categories should include 'dynamics_parameters'; got {cats}"

    def test_verdict_entries_have_impact(self):
        verdict = load_json("/app/verdict.json")
        for name in ("alpha", "beta", "gamma"):
            entry = _find_verdict_entry(verdict, name)
            impact = entry.get("impact", "")
            assert isinstance(impact, str) and len(impact) > 10, \
                f"verdict entry for {name} must have a meaningful 'impact' description"


# ---------------------------------------------------------------------------
# Existence tests
# ---------------------------------------------------------------------------
class TestOutputsExist:
    def test_solver_exists(self):
        assert os.path.isfile("/app/solver.py"), \
            "Composite solver not found at /app/solver.py"

    @pytest.mark.parametrize("name", ALL_INSTANCES)
    def test_result_exists(self, name):
        path = os.path.join(RESULT_DIR, f"{name}.json")
        assert os.path.isfile(path), f"Result file not found: {path}"


# ---------------------------------------------------------------------------
# Self-consistency tests — reported energy must match recomputed energy
# ---------------------------------------------------------------------------
class TestConsistency:
    @pytest.mark.parametrize("name", ISING_INSTANCES)
    def test_ising_energy_matches(self, name):
        inst = load_json(f"{INSTANCE_DIR}/{name}.json")
        res = load_json(f"{RESULT_DIR}/{name}.json")
        assert "spins" in res and "energy" in res
        spins = res["spins"]
        assert len(spins) == inst["n"], f"Expected {inst['n']} spins, got {len(spins)}"
        assert all(s in (-1, 1) for s in spins), "All spins must be +1 or -1"
        computed = ising_energy_from_lists(spins, inst["couplings"], inst["fields"])
        assert abs(computed - res["energy"]) < 1e-4, \
            f"Reported energy {res['energy']} != computed {computed}"

    @pytest.mark.parametrize("name", QUBO_INSTANCES)
    def test_qubo_energy_matches(self, name):
        inst = load_json(f"{INSTANCE_DIR}/{name}.json")
        res = load_json(f"{RESULT_DIR}/{name}.json")
        assert "bits" in res and "energy" in res
        bits = res["bits"]
        assert len(bits) == inst["n"], f"Expected {inst['n']} bits, got {len(bits)}"
        assert all(b in (0, 1) for b in bits), "All bits must be 0 or 1"
        computed = qubo_energy_from_bits(bits, inst["Q"])
        assert abs(computed - res["energy"]) < 1e-4, \
            f"Reported energy {res['energy']} != computed {computed}"


# ---------------------------------------------------------------------------
# Solution quality — compare to brute-force ground state
# ---------------------------------------------------------------------------
class TestQuality:
    def test_ising_chain(self):
        inst = load_json(f"{INSTANCE_DIR}/ising_chain.json")
        res = load_json(f"{RESULT_DIR}/ising_chain.json")
        ground = brute_force_ising_ground(inst["n"], inst["couplings"], inst["fields"])
        tol = abs(ground) * 0.05 + 0.1
        assert res["energy"] <= ground + tol, \
            f"energy {res['energy']} too far from ground {ground} (tol {tol})"

    def test_ising_frustrated(self):
        inst = load_json(f"{INSTANCE_DIR}/ising_frustrated.json")
        res = load_json(f"{RESULT_DIR}/ising_frustrated.json")
        ground = brute_force_ising_ground(inst["n"], inst["couplings"], inst["fields"])
        tol = abs(ground) * 0.10 + 0.5
        assert res["energy"] <= ground + tol, \
            f"energy {res['energy']} too far from ground {ground} (tol {tol})"

    def test_ising_sk20(self):
        inst = load_json(f"{INSTANCE_DIR}/ising_sk20.json")
        res = load_json(f"{RESULT_DIR}/ising_sk20.json")
        ground = brute_force_ising_ground(inst["n"], inst["couplings"], inst["fields"])
        tol = abs(ground) * 0.15 + 1.0
        assert res["energy"] <= ground + tol, \
            f"energy {res['energy']} too far from ground {ground} (tol {tol})"

    def test_ising_chimera(self):
        inst = load_json(f"{INSTANCE_DIR}/ising_chimera.json")
        res = load_json(f"{RESULT_DIR}/ising_chimera.json")
        ground = brute_force_ising_ground(inst["n"], inst["couplings"], inst["fields"])
        tol = abs(ground) * 0.12 + 0.5
        assert res["energy"] <= ground + tol, \
            f"energy {res['energy']} too far from ground {ground} (tol {tol})"

    def test_qubo_maxcut(self):
        inst = load_json(f"{INSTANCE_DIR}/qubo_maxcut.json")
        res = load_json(f"{RESULT_DIR}/qubo_maxcut.json")
        ground = brute_force_qubo_ground(inst["n"], inst["Q"])
        tol = abs(ground) * 0.10 + 0.5
        assert res["energy"] <= ground + tol, \
            f"energy {res['energy']} too far from ground {ground} (tol {tol})"

    def test_qubo_partition(self):
        inst = load_json(f"{INSTANCE_DIR}/qubo_partition.json")
        res = load_json(f"{RESULT_DIR}/qubo_partition.json")
        ground = brute_force_qubo_ground(inst["n"], inst["Q"])
        tol = abs(ground) * 0.05 + 100.0
        assert res["energy"] <= ground + tol, \
            f"energy {res['energy']} too far from ground {ground} (tol {tol})"


# ---------------------------------------------------------------------------
# QUBO-to-Ising conversion correctness (for any QUBO result)
# ---------------------------------------------------------------------------
class TestConversion:
    @pytest.mark.parametrize("name", QUBO_INSTANCES)
    def test_qubo_ising_energy_correspondence(self, name):
        """Verify E_QUBO = E_Ising + offset for the returned QUBO solution."""
        inst = load_json(f"{INSTANCE_DIR}/{name}.json")
        res = load_json(f"{RESULT_DIR}/{name}.json")
        Q = inst["Q"]
        n = inst["n"]
        bits = res["bits"]
        spins = [2 * b - 1 for b in bits]

        # Compute Ising coupling matrix from QUBO
        J_mat = np.zeros((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                J_mat[i][j] = Q[i][j] / 4.0
                J_mat[j][i] = Q[i][j] / 4.0

        # Compute Ising fields from QUBO
        h_vec = np.zeros(n)
        for i in range(n):
            h_vec[i] = Q[i][i] / 2.0
            for j in range(n):
                if j != i:
                    mi, ma = min(i, j), max(i, j)
                    h_vec[i] += Q[mi][ma] / 4.0

        # Compute constant offset
        offset = sum(Q[i][i] / 2.0 for i in range(n))
        offset += sum(Q[i][j] / 4.0 for i in range(n) for j in range(i + 1, n))

        s = np.array(spins, dtype=np.float64)
        e_ising = float(0.5 * s @ J_mat @ s + h_vec @ s)
        e_qubo = qubo_energy_from_bits(bits, Q)

        assert abs(e_qubo - (e_ising + offset)) < 1e-6, \
            f"QUBO={e_qubo} != Ising+offset={e_ising + offset}"
