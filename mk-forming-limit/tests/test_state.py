
"""
Tests for M-K forming limit curve predictor.
Includes an embedded reference solver for von Mises + Swift (psi0=0)
to validate numerical accuracy.
"""

import subprocess
import os
import json
import csv
import tempfile
import numpy as np
from scipy.optimize import brentq
import pytest


# ═══════════════════════════════════════════════════════════════════
# Embedded reference M-K solver (von Mises + Swift only, psi0=0)
# Used for verification — NOT the solution.
# ═══════════════════════════════════════════════════════════════════

def _vm_Ss(a):
    """Von Mises equivalent stress factor."""
    return np.sqrt(a * a - a + 1.0)

def _vm_E1(a):
    """Strain-rate direction factor E1 for von Mises."""
    return (2.0 - a) / (2.0 * _vm_Ss(a))

def _vm_E2(a):
    """Strain-rate direction factor E2 for von Mises."""
    return (2.0 * a - 1.0) / (2.0 * _vm_Ss(a))

def _swift(e, K, eps0, n):
    """Swift hardening law."""
    return K * (eps0 + max(e, 0.0)) ** n

def _ref_mk_point(K, eps0, n, f0, alpha_A,
                   delta=5e-4, max_steps=500000, threshold=10.0):
    """
    Compute one FLC point using the M-K model for von Mises + Swift, psi0=0.
    Returns (minor_strain, major_strain) or None.
    """
    e1A = _vm_E1(alpha_A)
    e2A = _vm_E2(alpha_A)
    is_ps = abs(e2A) < 1e-6

    eA = 1e-7
    eB = 1e-7
    f = f0

    for _ in range(max_steps):
        deB = delta

        if is_ps:
            aB = 0.5
            e1B = _vm_E1(0.5)

            def _feq_ps(dea):
                fn = f * np.exp(e1A * dea - e1B * deB)
                return _swift(eA + dea, K, eps0, n) - fn * _swift(eB + deB, K, eps0, n)

            try:
                deA = brentq(_feq_ps, 0.0, deB * 10.0, xtol=1e-14)
            except (ValueError, RuntimeError):
                return None
        else:
            def _feq_ab(ab):
                e2b = _vm_E2(ab)
                dea = e2b / e2A * deB
                if dea <= 0:
                    return -1e10
                fn = f * np.exp(e1A * dea - _vm_E1(ab) * deB)
                lhs = _swift(eA + dea, K, eps0, n) / _vm_Ss(alpha_A)
                rhs = fn * _swift(eB + deB, K, eps0, n) / _vm_Ss(ab)
                return lhs - rhs

            if e2A < 0:
                lo = max(-0.5, alpha_A - 0.5)
                hi = 0.5 - 1e-10
            else:
                lo = 0.5 + 1e-10
                hi = min(2.0, alpha_A + 0.5)

            try:
                flo = _feq_ab(lo)
                fhi = _feq_ab(hi)
                if flo * fhi > 0:
                    if e2A < 0:
                        lo = max(-1.0, lo - 0.5)
                    else:
                        hi = min(3.0, hi + 0.5)
                aB = brentq(_feq_ab, lo, hi, xtol=1e-10, maxiter=300)
            except (ValueError, RuntimeError):
                return None

            deA = _vm_E2(aB) / e2A * deB

        if deA < 0:
            return None

        f = f * np.exp(e1A * deA - _vm_E1(aB) * deB)
        eA += deA
        eB += deB

        # Adaptive step
        ratio = deA / deB
        if ratio < 0.5:
            delta = max(1e-5, delta * 0.5)

        if ratio < 1.0 / threshold:
            return (e2A * eA, e1A * eA)

    return None


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _run_solver(config_path, output_path, timeout=240):
    """Run the candidate solver and assert it exits cleanly."""
    r = subprocess.run(
        ["python3", "/app/mk_flc.py", config_path, output_path],
        capture_output=True, text=True, timeout=timeout,
    )
    assert r.returncode == 0, (
        f"Solver exited with code {r.returncode}.\n"
        f"stderr (first 800 chars): {r.stderr[:800]}"
    )


def _read_flc(path):
    """Read an FLC CSV and return (minor, major) arrays."""
    data = np.loadtxt(path, delimiter=",", skiprows=1)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    return data[:, 0], data[:, 1]


# ═══════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════

class TestSolverExists:
    def test_program_file_exists(self):
        assert os.path.isfile("/app/mk_flc.py"), "/app/mk_flc.py must exist"


class TestVonMisesFLC:
    """Run the solver with the von Mises material config and validate."""

    @pytest.fixture(autouse=True)
    def _run(self, tmp_path):
        self.out = str(tmp_path / "flc_vm.csv")
        _run_solver("/app/material_vm.json", self.out)
        self.minor, self.major = _read_flc(self.out)

    def test_csv_header(self):
        with open(self.out) as fh:
            reader = csv.DictReader(fh)
            assert "minor_strain" in reader.fieldnames
            assert "major_strain" in reader.fieldnames

    def test_enough_points(self):
        assert len(self.minor) >= 5, f"Need >= 5 points, got {len(self.minor)}"

    def test_all_major_positive(self):
        assert np.all(self.major > 0), "All major strains must be > 0"

    def test_has_left_side(self):
        assert np.any(self.minor < -0.01), "Need left-side points (minor < 0)"

    def test_has_right_side(self):
        assert np.any(self.minor > 0.01), "Need right-side points (minor > 0)"

    def test_sorted_ascending(self):
        assert np.all(np.diff(self.minor) >= -1e-8), "Must be sorted by minor_strain"

    def test_flc0_near_plane_strain(self):
        idx = np.argmin(self.major)
        assert abs(self.minor[idx]) < 0.06, (
            f"FLC0 at minor={self.minor[idx]:.4f}, expected near 0"
        )

    def test_flc0_magnitude(self):
        flc0 = np.min(self.major)
        assert 0.10 < flc0 < 0.28, f"FLC0 = {flc0:.4f} outside [0.10, 0.28]"

    def test_v_shape(self):
        idx = np.argmin(self.major)
        flc0 = self.major[idx]
        if idx > 0:
            assert self.major[0] >= flc0 * 0.90
        if idx < len(self.major) - 1:
            assert self.major[-1] >= flc0 * 0.90

    def test_numerical_accuracy_vs_reference(self):
        """Compare candidate output against embedded reference solver."""
        with open("/app/material_vm.json") as fh:
            cfg = json.load(fh)
        K = cfg["hardening"]["K"]
        eps0 = cfg["hardening"]["eps0"]
        n = cfg["hardening"]["n"]
        f0 = cfg["mk_params"]["f0"]

        check_alphas = [0.0, 0.3, 0.5, 0.7, 1.0]
        ref_pts = {}
        for a in check_alphas:
            pt = _ref_mk_point(K, eps0, n, f0, a)
            if pt is not None:
                ref_pts[a] = pt

        assert len(ref_pts) >= 3, "Reference solver must produce >= 3 points"

        for alpha, (ref_mi, ref_ma) in ref_pts.items():
            dists = np.abs(self.minor - ref_mi)
            idx = np.argmin(dists)
            if ref_ma > 0.05:
                rel = abs(self.major[idx] - ref_ma) / ref_ma
                assert rel < 0.20, (
                    f"alpha={alpha}: got major={self.major[idx]:.4f}, "
                    f"ref={ref_ma:.4f}, err={rel:.1%}"
                )


class TestHill48FLC:
    """Run the solver with Hill48 material config and validate."""

    @pytest.fixture(autouse=True)
    def _run(self, tmp_path):
        self.out = str(tmp_path / "flc_h48.csv")
        _run_solver("/app/material_h48.json", self.out)
        self.minor, self.major = _read_flc(self.out)

    def test_enough_points(self):
        assert len(self.minor) >= 5

    def test_all_major_positive(self):
        assert np.all(self.major > 0)

    def test_has_both_sides(self):
        assert np.any(self.minor < -0.01), "Need left side"
        assert np.any(self.minor > 0.01), "Need right side"

    def test_flc0_range(self):
        flc0 = np.min(self.major)
        assert 0.08 < flc0 < 0.30, f"Hill48 FLC0 = {flc0:.4f} out of range"

    def test_differs_from_von_mises(self, tmp_path):
        """Hill48 FLC must differ from von Mises FLC in shape."""
        vm_out = str(tmp_path / "flc_vm_cmp.csv")
        _run_solver("/app/material_vm.json", vm_out)
        vm_mi, vm_ma = _read_flc(vm_out)

        # At least some corresponding points should differ meaningfully.
        # Hill48 with R0=1.5, R90=2.0 shifts the FLC relative to von Mises.
        # Check rightmost points differ in either minor or major strain.
        vm_right_ma = vm_ma[-1]
        h48_right_ma = self.major[-1]
        vm_right_mi = vm_mi[-1]
        h48_right_mi = self.minor[-1]

        shape_differs = (
            abs(vm_right_ma - h48_right_ma) / max(vm_right_ma, 0.01) > 0.03
            or abs(vm_right_mi - h48_right_mi) > 0.01
        )
        assert shape_differs, (
            "Hill48 and von Mises should produce different FLC shapes"
        )


class TestImperfectionEffect:
    """Larger imperfection (lower f0) should yield a lower FLC."""

    def test_lower_f0_gives_lower_flc(self, tmp_path):
        with open("/app/material_vm.json") as fh:
            base = json.load(fh)

        # Create config with larger imperfection
        cfg2 = json.loads(json.dumps(base))
        cfg2["mk_params"]["f0"] = 0.990

        cfg2_path = str(tmp_path / "mat_f990.json")
        with open(cfg2_path, "w") as fh:
            json.dump(cfg2, fh)

        out1 = str(tmp_path / "flc_f996.csv")
        out2 = str(tmp_path / "flc_f990.csv")

        _run_solver("/app/material_vm.json", out1)
        _run_solver(cfg2_path, out2)

        _, ma1 = _read_flc(out1)
        _, ma2 = _read_flc(out2)

        flc0_996 = np.min(ma1)
        flc0_990 = np.min(ma2)

        assert flc0_990 < flc0_996, (
            f"f0=0.990 FLC0={flc0_990:.4f} should be < "
            f"f0=0.996 FLC0={flc0_996:.4f}"
        )
