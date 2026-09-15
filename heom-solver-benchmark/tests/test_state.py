"""
Tests for dissipative spin-boson HEOM steady-state analysis.

"""
import csv
import os
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_csv(path):
    """Read a CSV file with no header, returning list of lists of floats."""
    rows = []
    with open(path, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if row:  # skip blank lines
                rows.append([float(x) for x in row])
    return rows


# ---------------------------------------------------------------------------
# File existence and format
# ---------------------------------------------------------------------------

class TestFileFormat:
    def test_populations_exists(self):
        assert os.path.isfile("/app/results/populations.csv")

    def test_coherences_exists(self):
        assert os.path.isfile("/app/results/coherences.csv")

    def test_trace_distances_exists(self):
        assert os.path.isfile("/app/results/trace_distances.csv")

    def test_convergence_exists(self):
        assert os.path.isfile("/app/results/convergence.csv")

    def test_populations_rows(self):
        data = read_csv("/app/results/populations.csv")
        assert len(data) == 6, f"Expected 6 rows, got {len(data)}"
        for row in data:
            assert len(row) == 3, f"Expected 3 columns, got {len(row)}"

    def test_coherences_rows(self):
        data = read_csv("/app/results/coherences.csv")
        assert len(data) == 6
        for row in data:
            assert len(row) == 3

    def test_trace_distances_rows(self):
        data = read_csv("/app/results/trace_distances.csv")
        assert len(data) == 6
        for row in data:
            assert len(row) == 2

    def test_convergence_rows(self):
        data = read_csv("/app/results/convergence.csv")
        assert len(data) == 7, f"Expected 7 rows (NC=2..8), got {len(data)}"
        for row in data:
            assert len(row) == 2

    def test_lambda_values(self):
        data = read_csv("/app/results/populations.csv")
        expected = [0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
        for row, lam_exp in zip(data, expected):
            assert abs(row[0] - lam_exp) < 1e-6, (
                f"Expected lambda={lam_exp}, got {row[0]}"
            )

    def test_nc_values(self):
        data = read_csv("/app/results/convergence.csv")
        expected_nc = [2, 3, 4, 5, 6, 7, 8]
        for row, nc_exp in zip(data, expected_nc):
            assert abs(row[0] - nc_exp) < 1e-6, (
                f"Expected NC={nc_exp}, got {row[0]}"
            )


# ---------------------------------------------------------------------------
# Physical constraints
# ---------------------------------------------------------------------------

class TestPhysicalConstraints:
    def test_populations_bounded(self):
        data = read_csv("/app/results/populations.csv")
        for row in data:
            _, p11_h, p11_l = row
            assert -0.001 <= p11_h <= 1.001, f"P11_heom={p11_h} out of [0,1]"
            assert -0.001 <= p11_l <= 1.001, f"P11_lindblad={p11_l} out of [0,1]"

    def test_coherences_bounded(self):
        data = read_csv("/app/results/coherences.csv")
        for row in data:
            _, c_h, c_l = row
            assert -0.001 <= c_h <= 0.501, f"coherence_heom={c_h} out of range"
            assert -0.001 <= c_l <= 0.501, f"coherence_lindblad={c_l} out of range"

    def test_trace_distances_nonneg(self):
        data = read_csv("/app/results/trace_distances.csv")
        for row in data:
            assert row[1] >= -1e-6, f"Trace distance={row[1]} is negative"
            assert row[1] <= 1.001, f"Trace distance={row[1]} > 1"

    def test_convergence_bounded(self):
        data = read_csv("/app/results/convergence.csv")
        for row in data:
            assert -0.001 <= row[1] <= 1.001, f"P11={row[1]} out of [0,1]"


# ---------------------------------------------------------------------------
# Qualitative behaviour
# ---------------------------------------------------------------------------

class TestQualitativeBehavior:
    def test_weak_coupling_agreement(self):
        """At lambda=0.025, HEOM and Lindblad should closely agree."""
        data = read_csv("/app/results/trace_distances.csv")
        # first row is lambda=0.025
        td_weak = data[0][1]
        assert td_weak < 0.015, (
            f"Trace distance at weak coupling ({td_weak}) should be < 0.015"
        )

    def test_strong_coupling_disagreement(self):
        """At lambda=1.0, HEOM and Lindblad should visibly differ."""
        data = read_csv("/app/results/trace_distances.csv")
        td_strong = data[-1][1]
        assert td_strong > 0.01, (
            f"Trace distance at strong coupling ({td_strong}) should be > 0.01"
        )

    def test_trace_distance_trend(self):
        """Trace distance should generally increase from weak to strong coupling."""
        data = read_csv("/app/results/trace_distances.csv")
        assert data[-1][1] > data[0][1], (
            "Trace distance should grow from weak to strong coupling"
        )

    def test_convergence_stabilises(self):
        """Last two NC values in the convergence sweep should be close."""
        data = read_csv("/app/results/convergence.csv")
        p_nc7 = data[-2][1]  # NC=7
        p_nc8 = data[-1][1]  # NC=8
        assert abs(p_nc7 - p_nc8) < 0.005, (
            f"HEOM not converged: NC=7 -> {p_nc7}, NC=8 -> {p_nc8}"
        )


# ---------------------------------------------------------------------------
# Independent HEOM verification for lambda = 0.1
# ---------------------------------------------------------------------------

class TestIndependentVerification:
    """Recompute HEOM steady state for lambda=0.1 and compare to agent."""

    @pytest.fixture(autouse=True)
    def _compute_reference(self):
        import qutip as qt

        eps, Delta, gamma, T = 0.5, 1.0, 0.5, 0.5
        beta = 1.0 / T
        lam, Nk, NC = 0.1, 2, 5

        Hsys = 0.5 * eps * qt.sigmaz() + 0.5 * Delta * qt.sigmax()
        Q = qt.sigmaz()

        solver = self._make_solver(Hsys, Q, lam, T, gamma, Nk, NC, beta)

        # Obtain steady state
        try:
            rho_ss, _ = solver.steady_state()
        except Exception:
            rho0 = qt.identity(2) / 2
            tlist = np.linspace(0, 150, 750)
            result = solver.run(rho0, tlist)
            rho_ss = result.states[-1]

        P11 = qt.basis(2, 0) * qt.basis(2, 0).dag()
        self.ref_p11 = np.real(qt.expect(P11, rho_ss))
        self.ref_coh = float(np.abs(rho_ss.full()[0, 1]))

    # ---- helpers for multi-API robustness ----

    @staticmethod
    def _make_solver(Hsys, Q, lam, T, gamma, Nk, NC, beta):
        import qutip as qt

        opts = {"nsteps": 15000, "store_states": True,
                "rtol": 1e-12, "atol": 1e-12}

        # Approach 1: legacy HSolverDL
        try:
            from qutip.solver.heom import HSolverDL
            return HSolverDL(Hsys, Q, lam, T, NC, Nk, gamma,
                             bnd_cut_approx=True, options=opts)
        except Exception:
            pass

        # Approach 2: DrudeLorentzEnvironment (new API)
        try:
            from qutip.core.environment import (
                DrudeLorentzEnvironment, system_terminator,
            )
            from qutip.solver.heom import HEOMSolver

            env = DrudeLorentzEnvironment(lam=lam, gamma=gamma, T=T)
            env_approx, delta = env.approximate(
                "matsubara", Nk=Nk, compute_delta=True,
            )
            Ltot = qt.liouvillian(Hsys) + system_terminator(Q, delta)
            return HEOMSolver(Ltot, (env_approx, Q), NC, options=opts)
        except Exception:
            pass

        # Approach 3: manual Matsubara + terminator
        from qutip.solver.heom import HEOMSolver

        cot_v = 1.0 / np.tan(gamma * beta / 2)
        ckAR = [lam * gamma * cot_v]
        vkAR = [gamma]
        for k in range(1, Nk + 1):
            vk = 2 * np.pi * k * T
            ckAR.append(
                4 * lam * gamma * T * vk / (vk ** 2 - gamma ** 2)
            )
            vkAR.append(vk)
        ckAI = [lam * gamma * (-1.0)]
        vkAI = [gamma]

        delta = (2 * lam / (beta * gamma)) - 1j * lam
        delta -= lam * gamma * (-1j + cot_v) / gamma
        for k in range(1, Nk + 1):
            vk = 2 * np.pi * k * T
            delta -= (
                4 * lam * gamma * T * vk / (vk ** 2 - gamma ** 2)
            ) / vk

        op = (
            -2 * qt.spre(Q) * qt.spost(Q.dag())
            + qt.spre(Q.dag() * Q)
            + qt.spost(Q.dag() * Q)
        )
        L_bnd = -delta * op
        Ltot = qt.liouvillian(Hsys) + L_bnd

        try:
            from qutip.core.environment import ExponentialBosonicEnvironment
            env = ExponentialBosonicEnvironment(ckAR, vkAR, ckAI, vkAI)
            bath_arg = (env, Q)
        except ImportError:
            from qutip.solver.heom import BosonicBath
            bath_arg = BosonicBath(Q, ckAR, vkAR, ckAI, vkAI)

        return HEOMSolver(Ltot, bath_arg, NC, options=opts)

    # ---- actual assertions ----

    def test_p11_matches(self):
        data = read_csv("/app/results/populations.csv")
        row = next(r for r in data if abs(r[0] - 0.1) < 1e-6)
        p11_agent = row[1]
        assert abs(p11_agent - self.ref_p11) < 0.01, (
            f"P11 mismatch at lambda=0.1: agent={p11_agent:.6f}, "
            f"ref={self.ref_p11:.6f}"
        )

    def test_coherence_matches(self):
        data = read_csv("/app/results/coherences.csv")
        row = next(r for r in data if abs(r[0] - 0.1) < 1e-6)
        coh_agent = row[1]
        assert abs(coh_agent - self.ref_coh) < 0.01, (
            f"Coherence mismatch at lambda=0.1: agent={coh_agent:.6f}, "
            f"ref={self.ref_coh:.6f}"
        )


# ---------------------------------------------------------------------------
# Lindblad independent verification for lambda = 0.1
# ---------------------------------------------------------------------------

class TestLindbladVerification:
    """Independently verify the Lindblad steady state for lambda=0.1."""

    @pytest.fixture(autouse=True)
    def _compute_lindblad_ref(self):
        import qutip as qt

        eps, Delta, gamma, T = 0.5, 1.0, 0.5, 0.5
        lam = 0.1

        Hsys = 0.5 * eps * qt.sigmaz() + 0.5 * Delta * qt.sigmax()
        Q = qt.sigmaz()

        evals, estates = Hsys.eigenstates()
        gap = evals[1] - evals[0]

        Q_me = float(
            np.abs(Q.matrix_element(estates[0].dag(), estates[1])) ** 2
        )
        J_gap = 2 * lam * gamma * gap / (gamma ** 2 + gap ** 2)
        n_th = 1.0 / (np.exp(gap / T) - 1.0)

        rate_down = Q_me * J_gap * (n_th + 1)
        rate_up = Q_me * J_gap * n_th

        c_ops = []
        if rate_down > 0:
            c_ops.append(
                np.sqrt(rate_down) * estates[0] * estates[1].dag()
            )
        if rate_up > 0:
            c_ops.append(
                np.sqrt(rate_up) * estates[1] * estates[0].dag()
            )

        rho_ss = qt.steadystate(Hsys, c_ops)
        P11 = qt.basis(2, 0) * qt.basis(2, 0).dag()
        self.ref_p11_l = float(np.real(qt.expect(P11, rho_ss)))
        self.ref_coh_l = float(np.abs(rho_ss.full()[0, 1]))

    def test_lindblad_p11(self):
        data = read_csv("/app/results/populations.csv")
        row = next(r for r in data if abs(r[0] - 0.1) < 1e-6)
        p11_l_agent = row[2]
        assert abs(p11_l_agent - self.ref_p11_l) < 0.01, (
            f"Lindblad P11 mismatch: agent={p11_l_agent:.6f}, "
            f"ref={self.ref_p11_l:.6f}"
        )

    def test_lindblad_coherence(self):
        data = read_csv("/app/results/coherences.csv")
        row = next(r for r in data if abs(r[0] - 0.1) < 1e-6)
        coh_l_agent = row[2]
        assert abs(coh_l_agent - self.ref_coh_l) < 0.01, (
            f"Lindblad coherence mismatch: agent={coh_l_agent:.6f}, "
            f"ref={self.ref_coh_l:.6f}"
        )
