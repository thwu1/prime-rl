"""Tests for computational physics pipeline fidelity audit.

Tests verify both simulation correctness (output matches reference within
physical tolerances) and audit deliverables (structured diagnostic report
correctly identifying root causes and violated conservation laws).
"""
import json
import math
import os
import re
import subprocess
import pytest


def load_traj(path):
    with open(path) as fh:
        return json.load(fh)


def interpolate_at(traj, t_target):
    """Linearly interpolate trajectory data at a specific time."""
    times = traj["times"]
    data = traj["data"]
    if t_target <= times[0]:
        return data[0]
    if t_target >= times[-1]:
        return data[-1]
    for i in range(len(times) - 1):
        if times[i] <= t_target <= times[i + 1]:
            frac = (t_target - times[i]) / (times[i + 1] - times[i])
            return [d1 + frac * (d2 - d1) for d1, d2 in zip(data[i], data[i + 1])]
    return data[-1]


# ======================== Ballistic ========================

class TestBallistic:
    @pytest.fixture(autouse=True)
    def run_sim(self):
        result = subprocess.run(
            ["python3", "/app/simulations/ballistic.py"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"Simulation crashed: {result.stderr}"

    def test_range(self):
        ref = load_traj("/app/reference/ballistic.json")
        out = load_traj("/app/output/ballistic.json")
        ref_range = max(d[0] for d in ref["data"] if d[1] >= 0)
        out_range = max(d[0] for d in out["data"] if d[1] >= 0)
        rel_err = abs(out_range - ref_range) / ref_range
        assert rel_err < 0.05, (
            f"Range mismatch: {out_range:.2f} vs ref {ref_range:.2f} "
            f"(err={rel_err:.2%})"
        )

    def test_peak_height(self):
        ref = load_traj("/app/reference/ballistic.json")
        out = load_traj("/app/output/ballistic.json")
        ref_peak = max(d[1] for d in ref["data"])
        out_peak = max(d[1] for d in out["data"])
        rel_err = abs(out_peak - ref_peak) / ref_peak
        assert rel_err < 0.05, (
            f"Peak height mismatch: {out_peak:.2f} vs ref {ref_peak:.2f}"
        )

    def test_trajectory_midpoint(self):
        ref = load_traj("/app/reference/ballistic.json")
        out = load_traj("/app/output/ballistic.json")
        for tc in [1.0, 1.5]:
            ref_pt = interpolate_at(ref, tc)
            out_pt = interpolate_at(out, tc)
            for idx, label in enumerate(["x", "y"]):
                if abs(ref_pt[idx]) > 0.1:
                    rel_err = abs(out_pt[idx] - ref_pt[idx]) / abs(ref_pt[idx])
                    assert rel_err < 0.05, (
                        f"{label} at t={tc}: {out_pt[idx]:.3f} vs "
                        f"ref {ref_pt[idx]:.3f} (err={rel_err:.2%})"
                    )


# ======================== Oscillator ========================

class TestOscillator:
    @pytest.fixture(autouse=True)
    def run_sim(self):
        result = subprocess.run(
            ["python3", "/app/simulations/oscillator.py"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"Simulation crashed: {result.stderr}"

    def test_trajectory_q1(self):
        ref = load_traj("/app/reference/oscillator.json")
        out = load_traj("/app/output/oscillator.json")
        for tc in [1.0, 3.0, 5.0, 7.0, 9.0]:
            ref_pt = interpolate_at(ref, tc)
            out_pt = interpolate_at(out, tc)
            assert abs(out_pt[0] - ref_pt[0]) < 0.1, (
                f"q1 at t={tc}: {out_pt[0]:.4f} vs ref {ref_pt[0]:.4f}"
            )

    def test_trajectory_q2(self):
        ref = load_traj("/app/reference/oscillator.json")
        out = load_traj("/app/output/oscillator.json")
        for tc in [1.0, 3.0, 5.0, 7.0, 9.0]:
            ref_pt = interpolate_at(ref, tc)
            out_pt = interpolate_at(out, tc)
            assert abs(out_pt[1] - ref_pt[1]) < 0.1, (
                f"q2 at t={tc}: {out_pt[1]:.4f} vs ref {ref_pt[1]:.4f}"
            )

    def test_energy_bounded(self):
        """Total mechanical energy must remain bounded (no exponential growth)."""
        out = load_traj("/app/output/oscillator.json")
        k1, k2, k_c = 10.0, 8.0, 5.0
        m1_val, m2_val = 1.0, 1.5
        max_energy = 0
        for pt in out["data"]:
            q1, q2, v1, v2 = pt
            KE = 0.5 * m1_val * v1 ** 2 + 0.5 * m2_val * v2 ** 2
            PE = 0.5 * k1 * q1 ** 2 + 0.5 * k2 * q2 ** 2 + 0.5 * k_c * (q2 - q1) ** 2
            max_energy = max(max_energy, KE + PE)
        q1_0, q2_0 = 0.5, -0.3
        E0 = 0.5 * k1 * q1_0 ** 2 + 0.5 * k2 * q2_0 ** 2 + 0.5 * k_c * (q2_0 - q1_0) ** 2
        assert max_energy < 1.5 * E0, (
            f"Energy grew too much: max={max_energy:.4f} vs initial={E0:.4f}"
        )


# ======================== Diffusion ========================

class TestDiffusion:
    @pytest.fixture(autouse=True)
    def run_sim(self):
        result = subprocess.run(
            ["python3", "/app/simulations/diffusion.py"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"Simulation crashed: {result.stderr}"

    def test_final_profile(self):
        ref = load_traj("/app/reference/diffusion.json")
        out = load_traj("/app/output/diffusion.json")
        ref_final = ref["data"][-1]
        out_final = out["data"][-1]
        assert len(ref_final) == len(out_final), (
            f"Spatial resolution mismatch: {len(out_final)} vs {len(ref_final)}"
        )
        rms = math.sqrt(
            sum((a - b) ** 2 for a, b in zip(out_final, ref_final)) / len(ref_final)
        )
        assert rms < 2.0, f"Final temperature profile RMS error: {rms:.4f}"

    def test_no_oscillations(self):
        """Temperature must decrease monotonically from left (hot) to right (cold)."""
        out = load_traj("/app/output/diffusion.json")
        final = out["data"][-1]
        violations = 0
        for i in range(len(final) - 1):
            if final[i + 1] > final[i] + 0.5:
                violations += 1
        assert violations < 3, (
            f"Solution has {violations} monotonicity violations — likely unstable"
        )

    def test_boundary_conditions(self):
        out = load_traj("/app/output/diffusion.json")
        for snap in out["data"]:
            assert abs(snap[0] - 100.0) < 0.01, f"Left BC violated: {snap[0]}"
            assert abs(snap[-1]) < 0.01, f"Right BC violated: {snap[-1]}"


# ======================== Orbit ========================

class TestOrbit:
    @pytest.fixture(autouse=True)
    def run_sim(self):
        result = subprocess.run(
            ["python3", "/app/simulations/orbit.py"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, f"Simulation crashed: {result.stderr}"

    def test_orbit_closure(self):
        """After one period (T=1yr for a=1AU), position should return near perihelion."""
        ref = load_traj("/app/reference/orbit.json")
        out = load_traj("/app/output/orbit.json")
        ref_pt = interpolate_at(ref, 1.0)
        out_pt = interpolate_at(out, 1.0)
        pos_err = math.sqrt(
            (out_pt[0] - ref_pt[0]) ** 2 + (out_pt[1] - ref_pt[1]) ** 2
        )
        assert pos_err < 0.1, (
            f"Orbit position error at T=1yr: {pos_err:.4f} AU "
            f"(out=({out_pt[0]:.3f},{out_pt[1]:.3f}), "
            f"ref=({ref_pt[0]:.3f},{ref_pt[1]:.3f}))"
        )

    def test_energy_conservation(self):
        """Specific orbital energy E = v^2/2 - GM/r should be conserved."""
        out = load_traj("/app/output/orbit.json")
        GM = 4.0 * math.pi ** 2
        energies = []
        for pt in out["data"]:
            x, y, vx, vy = pt
            r = math.sqrt(x ** 2 + y ** 2)
            energies.append(0.5 * (vx ** 2 + vy ** 2) - GM / r)
        E0 = energies[0]
        max_rel_err = max(abs(e - E0) / abs(E0) for e in energies)
        assert max_rel_err < 0.01, (
            f"Energy not conserved: max relative error {max_rel_err:.4f}"
        )

    def test_angular_momentum(self):
        """Specific angular momentum L = x*vy - y*vx should be conserved."""
        out = load_traj("/app/output/orbit.json")
        L_vals = [pt[0] * pt[3] - pt[1] * pt[2] for pt in out["data"]]
        L0 = L_vals[0]
        max_rel_err = max(abs(l - L0) / abs(L0) for l in L_vals)
        assert max_rel_err < 0.01, (
            f"Angular momentum not conserved: max relative error {max_rel_err:.4f}"
        )


# ======================== Collision ========================

class TestCollision:
    @pytest.fixture(autouse=True)
    def run_sim(self):
        result = subprocess.run(
            ["python3", "/app/simulations/collision.py"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"Simulation crashed: {result.stderr}"

    def test_momentum_conservation(self):
        """Total momentum must be conserved across the collision."""
        out = load_traj("/app/output/collision.json")
        m1, m2 = 2.0, 3.0
        first = out["data"][0]
        last = out["data"][-1]
        for idx, label in [(2, "px"), (3, "py")]:
            p_init = m1 * first[idx] + m2 * first[idx + 4]
            p_final = m1 * last[idx] + m2 * last[idx + 4]
            denom = abs(p_init) if abs(p_init) > 0.01 else 1.0
            err = abs(p_final - p_init) / denom
            assert err < 0.02, (
                f"{label} not conserved: init={p_init:.4f}, "
                f"final={p_final:.4f} (err={err:.4f})"
            )

    def test_energy_conservation(self):
        """Total kinetic energy must be conserved (elastic collision)."""
        out = load_traj("/app/output/collision.json")
        m1, m2 = 2.0, 3.0
        first = out["data"][0]
        last = out["data"][-1]
        KE_init = (
            0.5 * m1 * (first[2] ** 2 + first[3] ** 2)
            + 0.5 * m2 * (first[6] ** 2 + first[7] ** 2)
        )
        KE_final = (
            0.5 * m1 * (last[2] ** 2 + last[3] ** 2)
            + 0.5 * m2 * (last[6] ** 2 + last[7] ** 2)
        )
        rel_err = abs(KE_final - KE_init) / KE_init
        assert rel_err < 0.02, (
            f"KE not conserved: init={KE_init:.4f}, "
            f"final={KE_final:.4f} (err={rel_err:.4f})"
        )

    def test_post_collision_velocities(self):
        """Post-collision velocities must match reference."""
        ref = load_traj("/app/reference/collision.json")
        out = load_traj("/app/output/collision.json")
        ref_pt = interpolate_at(ref, 1.5)
        out_pt = interpolate_at(out, 1.5)
        for idx in [2, 3, 6, 7]:
            err = abs(out_pt[idx] - ref_pt[idx])
            assert err < 0.5, (
                f"Velocity[{idx}] at t=1.5: {out_pt[idx]:.4f} "
                f"vs ref {ref_pt[idx]:.4f}"
            )


# ======================== Audit Report ========================

class TestAuditReport:
    """Verify the audit report correctly identifies defect layers,
    root causes, and violated conservation laws for each simulation."""

    @pytest.fixture(autouse=True)
    def load_report(self):
        path = "/app/audit/report.json"
        assert os.path.isfile(path), (
            "Audit report not found at /app/audit/report.json"
        )
        with open(path) as fh:
            self.report = json.load(fh)

    def _combined(self, sim):
        """Concatenate all text fields for a simulation entry, lowercased."""
        entry = self.report[sim]
        return " ".join(str(v) for v in entry.values()).lower()

    def test_report_completeness(self):
        """Report must contain all five simulations with required fields."""
        for sim in ["ballistic", "oscillator", "diffusion", "orbit", "collision"]:
            assert sim in self.report, f"Missing '{sim}' in audit report"
            entry = self.report[sim]
            for field in ["layer", "root_cause", "conservation_law_violated"]:
                assert field in entry, f"{sim}: missing '{field}' field"
                val = str(entry[field]).strip()
                assert len(val) >= 10, (
                    f"{sim}.{field} too short to be meaningful: '{val}'"
                )

    def test_ballistic_identifies_area_config(self):
        """Ballistic diagnosis must reference the area/drag configuration defect."""
        text = self._combined("ballistic")
        kw = ["area", "cross.section", "drag", "config", "toml",
              "projected", "reference_area", "surface"]
        assert any(re.search(k, text) for k in kw), (
            f"Ballistic: diagnosis doesn't identify area/config defect"
        )

    def test_oscillator_identifies_coupling_sign(self):
        """Oscillator diagnosis must reference coupling sign / Newton's 3rd law."""
        text = self._combined("oscillator")
        kw = ["sign", "newton", "third.law", "3rd.law", "coupl",
              "action.reaction", "k_c", "opposite"]
        assert any(re.search(k, text) for k in kw), (
            f"Oscillator: diagnosis doesn't identify coupling/sign defect"
        )

    def test_diffusion_identifies_buffer_interface(self):
        """Diffusion diagnosis must reference the ctypes buffer / interface defect."""
        text = self._combined("diffusion")
        kw = ["buffer", "u_in", "u_out", "return", "ctype",
              "wrapper", "interface", "marshal", "ffi", "binding"]
        assert any(re.search(k, text) for k in kw), (
            f"Diffusion: diagnosis doesn't identify interface/buffer defect"
        )

    def test_orbit_identifies_verlet_dt(self):
        """Orbit diagnosis must reference the verlet dt*dt / C library defect."""
        text = self._combined("orbit")
        kw = ["dt.{0,10}dt", "dt.squared", r"dt\^2", "verlet",
              "velocity.{0,15}update", "integrat", "time.step"]
        assert any(re.search(k, text) for k in kw), (
            f"Orbit: diagnosis doesn't identify verlet/dt defect"
        )

    def test_collision_identifies_formula(self):
        """Collision diagnosis must reference the elastic collision formula error."""
        text = self._combined("collision")
        kw = ["elastic", "formula", "m1.{0,10}m2", "numerator",
              "mass.{0,10}differ", "collision.{0,10}equation"]
        assert any(re.search(k, text) for k in kw), (
            f"Collision: diagnosis doesn't identify formula defect"
        )
