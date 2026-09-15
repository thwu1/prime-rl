"""Tests for nuclear fuel depletion simulation.

"""

import glob
import math
import os
import sqlite3
import xml.etree.ElementTree as ET

import numpy as np
from scipy.linalg import expm
import pytest

try:
    import tomllib
except ImportError:
    import tomli as tomllib

BARN_TO_CM2 = 1.0e-24


# ---------------------------------------------------------------------------
# Reference computation helpers
# ---------------------------------------------------------------------------


def parse_chain(path="/app/chain.xml"):
    tree = ET.parse(path)
    root = tree.getroot()
    nuclides = []
    for nuc_elem in root.findall("nuclide"):
        name = nuc_elem.get("name")
        half_life = float(nuc_elem.get("half_life"))
        decay_constant = math.log(2) / half_life

        decay_modes = []
        for d in nuc_elem.findall("decay"):
            decay_modes.append({
                "target": d.get("target"),
                "branching_ratio": float(d.get("branching_ratio")),
            })

        reactions = []
        for r in nuc_elem.findall("reaction"):
            xs = float(r.find("cross_section").get("barn"))
            fission_yields = []
            fy_elem = r.find("neutron_fission_yields/fission_yields")
            if fy_elem is not None:
                prods = fy_elem.find("products").text.split()
                vals = [float(x) for x in fy_elem.find("data").text.split()]
                fission_yields = [
                    {"product": p, "yield_fraction": y}
                    for p, y in zip(prods, vals)
                ]
            reactions.append({
                "type": r.get("type"),
                "target": r.get("target"),
                "xs_barn": xs,
                "fission_yields": fission_yields,
            })

        nuclides.append({
            "name": name,
            "decay_constant": decay_constant,
            "decay_modes": decay_modes,
            "reactions": reactions,
        })
    return nuclides


def parse_problem(path="/app/problem.toml"):
    with open(path, "rb") as f:
        return tomllib.load(f)


def build_index(nuclides):
    return {nuc["name"]: i for i, nuc in enumerate(nuclides)}


def build_matrix(nuclides, idx, flux):
    n = len(nuclides)
    A = np.zeros((n, n))
    for i, nuc in enumerate(nuclides):
        lam = nuc["decay_constant"]
        A[i, i] -= lam
        for mode in nuc["decay_modes"]:
            target = mode["target"]
            if target in idx:
                A[idx[target], i] += lam * mode["branching_ratio"]
        for rxn in nuc["reactions"]:
            sigma = rxn["xs_barn"] * BARN_TO_CM2
            rate = sigma * flux
            A[i, i] -= rate
            if rxn["type"] == "(n,gamma)" and rxn["target"] and rxn["target"] in idx:
                A[idx[rxn["target"]], i] += rate
            if rxn["type"] == "fission":
                for fy in rxn.get("fission_yields", []):
                    if fy["product"] in idx:
                        A[idx[fy["product"]], i] += fy["yield_fraction"] * rate
    return A


def compute_reference():
    nuclides = parse_chain()
    problem = parse_problem()
    idx = build_index(nuclides)
    n = len(nuclides)
    names = [nuc["name"] for nuc in nuclides]

    conc = np.zeros(n)
    for name, val in problem["inventory"].items():
        if name in idx:
            conc[idx[name]] = val

    results = {0: {nm: conc[idx[nm]] for nm in names}}
    times = {0: 0.0}
    cumtime = 0.0

    for step_idx, step in enumerate(problem["schedule"]):
        flux = step["flux_n_per_cm2_s"]
        dt = step["duration_s"]
        A = build_matrix(nuclides, idx, flux)
        conc = expm(A * dt) @ conc
        cumtime += dt
        sn = step_idx + 1
        results[sn] = {nm: conc[idx[nm]] for nm in names}
        times[sn] = cumtime

    return results, times, names


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reference():
    return compute_reference()


@pytest.fixture(scope="module")
def agent_db():
    conn = sqlite3.connect("/app/results.db")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Schema / structure tests
# ---------------------------------------------------------------------------


class TestSchema:
    def test_database_exists(self):
        assert os.path.exists("/app/results.db"), "/app/results.db not found"

    def test_nuclides_table(self, agent_db):
        rows = agent_db.execute(
            "SELECT name FROM nuclides ORDER BY name"
        ).fetchall()
        names = {r["name"] for r in rows}
        expected = {
            "U234", "U235", "U236", "U238", "Np239",
            "Pu239", "Pu240", "Pu241", "Xe135", "I135",
        }
        assert names == expected, f"Missing nuclides: {expected - names}"

    def test_steps_table_count(self, agent_db):
        rows = agent_db.execute(
            "SELECT step_number, cumulative_time_s FROM steps "
            "ORDER BY step_number"
        ).fetchall()
        assert len(rows) == 6, f"Expected 6 steps (0-5), got {len(rows)}"

    def test_step_zero(self, agent_db):
        row = agent_db.execute(
            "SELECT cumulative_time_s FROM steps WHERE step_number = 0"
        ).fetchone()
        assert row is not None, "Step 0 missing"
        assert row["cumulative_time_s"] == 0.0

    def test_concentrations_count(self, agent_db):
        count = agent_db.execute(
            "SELECT COUNT(*) FROM concentrations"
        ).fetchone()[0]
        assert count == 60, (
            f"Expected 60 rows (10 nuclides x 6 steps), got {count}"
        )

    def test_step_times(self, agent_db, reference):
        _, ref_times, _ = reference
        rows = agent_db.execute(
            "SELECT step_number, cumulative_time_s FROM steps "
            "ORDER BY step_number"
        ).fetchall()
        for row in rows:
            step = row["step_number"]
            agent_time = row["cumulative_time_s"]
            ref_time = ref_times[step]
            assert abs(agent_time - ref_time) < 1.0, (
                f"Step {step}: time {agent_time} != reference {ref_time}"
            )


# ---------------------------------------------------------------------------
# Numerical accuracy tests
# ---------------------------------------------------------------------------


class TestAccuracy:
    @staticmethod
    def _get_agent_conc(agent_db, step_number):
        rows = agent_db.execute(
            "SELECT nuclide, value_atoms_per_cm3 "
            "FROM concentrations WHERE step_number = ?",
            (step_number,),
        ).fetchall()
        return {r["nuclide"]: r["value_atoms_per_cm3"] for r in rows}

    @staticmethod
    def _check_step(agent_db, reference, step_idx):
        ref_results, _, nuclide_names = reference
        ref = ref_results[step_idx]
        agent = TestAccuracy._get_agent_conc(agent_db, step_idx)

        for name in nuclide_names:
            ref_val = ref[name]
            agent_val = agent.get(name)
            assert agent_val is not None, (
                f"Step {step_idx}: missing nuclide {name}"
            )
            if abs(ref_val) < 1e6:
                assert abs(agent_val - ref_val) < 1e6, (
                    f"Step {step_idx} {name}: "
                    f"agent={agent_val:.6e} ref={ref_val:.6e}"
                )
            else:
                rel = abs(agent_val - ref_val) / abs(ref_val)
                assert rel < 1e-3, (
                    f"Step {step_idx} {name}: "
                    f"agent={agent_val:.6e} ref={ref_val:.6e} rel={rel:.2e}"
                )

    def test_initial_state(self, agent_db, reference):
        """Initial concentrations (step 0) should match inventory."""
        self._check_step(agent_db, reference, 0)

    def test_step1_low_power(self, agent_db, reference):
        """After 2-day low-power startup."""
        self._check_step(agent_db, reference, 1)

    def test_step2_full_power(self, agent_db, reference):
        """After 30-day full power irradiation."""
        self._check_step(agent_db, reference, 2)

    def test_step3_shutdown(self, agent_db, reference):
        """After 5-day shutdown decay."""
        self._check_step(agent_db, reference, 3)

    def test_step4_reduced_power(self, agent_db, reference):
        """After 15-day reduced power operation."""
        self._check_step(agent_db, reference, 4)

    def test_step5_final_shutdown(self, agent_db, reference):
        """After 10-day final shutdown."""
        self._check_step(agent_db, reference, 5)


# ---------------------------------------------------------------------------
# Physics consistency tests
# ---------------------------------------------------------------------------


class TestPhysics:
    @staticmethod
    def _conc(agent_db, step, nuclide):
        row = agent_db.execute(
            "SELECT value_atoms_per_cm3 FROM concentrations "
            "WHERE step_number = ? AND nuclide = ?",
            (step, nuclide),
        ).fetchone()
        return row[0] if row else None

    def test_u235_consumed_during_irradiation(self, agent_db):
        u235_0 = self._conc(agent_db, 0, "U235")
        u235_1 = self._conc(agent_db, 1, "U235")
        assert u235_1 < u235_0, (
            f"U235 should decrease: {u235_0:.4e} -> {u235_1:.4e}"
        )

    def test_u235_monotone_during_irradiation(self, agent_db):
        vals = [self._conc(agent_db, s, "U235") for s in range(6)]
        # Steps 0->1, 1->2 are irradiation: must decrease
        assert vals[1] < vals[0], "U235 must decrease step 0->1"
        assert vals[2] < vals[1], "U235 must decrease step 1->2"
        # Steps 3->4 is reduced power: must decrease
        assert vals[4] < vals[3], "U235 must decrease step 3->4"

    def test_pu239_bred(self, agent_db):
        pu_0 = self._conc(agent_db, 0, "Pu239")
        pu_2 = self._conc(agent_db, 2, "Pu239")
        assert pu_2 > pu_0, (
            f"Pu239 should increase: {pu_0:.4e} -> {pu_2:.4e}"
        )

    def test_xe135_equilibrium(self, agent_db):
        xe = self._conc(agent_db, 2, "Xe135")
        assert xe > 1e14, (
            f"Xe135 should reach >1e14 during full power, got {xe:.4e}"
        )

    def test_xe135_decays_during_shutdown(self, agent_db):
        xe_oper = self._conc(agent_db, 2, "Xe135")
        xe_shut = self._conc(agent_db, 3, "Xe135")
        # 5-day shutdown is ~13 Xe-135 half-lives
        assert xe_shut < xe_oper * 0.01, (
            f"Xe135 should mostly decay during 5-day shutdown: "
            f"{xe_oper:.4e} -> {xe_shut:.4e}"
        )

    def test_xe135_rebuilds_on_restart(self, agent_db):
        xe_shut = self._conc(agent_db, 3, "Xe135")
        xe_restart = self._conc(agent_db, 4, "Xe135")
        assert xe_restart > xe_shut * 10 or xe_restart > 1e14, (
            f"Xe135 should rebuild during restart: "
            f"{xe_shut:.4e} -> {xe_restart:.4e}"
        )

    def test_np239_decays_during_shutdown(self, agent_db):
        np_before = self._conc(agent_db, 2, "Np239")
        np_after = self._conc(agent_db, 3, "Np239")
        if np_before and np_before > 1e10:
            # Np239 T_half ~ 2.35 days; 5 days ~ 2.1 half-lives
            assert np_after < np_before * 0.3, (
                f"Np239 should decay during shutdown: "
                f"{np_before:.4e} -> {np_after:.4e}"
            )

    def test_u236_produced(self, agent_db):
        u236_0 = self._conc(agent_db, 0, "U236")
        u236_2 = self._conc(agent_db, 2, "U236")
        assert u236_2 > u236_0, (
            f"U236 should increase: {u236_0:.4e} -> {u236_2:.4e}"
        )

    def test_no_negative_concentrations(self, agent_db):
        rows = agent_db.execute(
            "SELECT step_number, nuclide, value_atoms_per_cm3 "
            "FROM concentrations"
        ).fetchall()
        for row in rows:
            val = row["value_atoms_per_cm3"]
            assert val >= -1e5, (
                f"Negative: {row['nuclide']} at step "
                f"{row['step_number']}: {val:.4e}"
            )


# ---------------------------------------------------------------------------
# Implementation constraint tests
# ---------------------------------------------------------------------------


class TestImplementation:
    def test_no_scipy_in_solver(self):
        """Solver must not import scipy."""
        for fpath in glob.glob("/app/**/*.py", recursive=True):
            with open(fpath) as f:
                lines = f.readlines()
            for lineno, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "import scipy" in stripped or "from scipy" in stripped:
                    pytest.fail(
                        f"{fpath}:{lineno} imports scipy — "
                        "the simulation must be implemented without scipy"
                    )

    def test_results_in_sqlite(self):
        """Results must be in SQLite format."""
        assert os.path.exists("/app/results.db"), "results.db not found"
        conn = sqlite3.connect("/app/results.db")
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "nuclides" in tables, "nuclides table missing"
            assert "steps" in tables, "steps table missing"
            assert "concentrations" in tables, "concentrations table missing"
        finally:
            conn.close()
