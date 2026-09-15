import subprocess
import math
import os
import pytest


BINARY = "/app/build/manipulator"


def build():
    """Configure and build the project with CMake from a clean state."""
    subprocess.run(["rm", "-rf", "/app/build"], capture_output=True, timeout=10)
    r = subprocess.run(
        ["cmake", "-B", "/app/build", "-S", "/app"],
        capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 0, f"CMake configure failed:\n{r.stderr}\n{r.stdout}"
    r = subprocess.run(
        ["cmake", "--build", "/app/build"],
        capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, f"Build failed:\n{r.stderr}\n{r.stdout}"


def run_fk(q):
    cmd = [BINARY, "--fk"] + [str(x) for x in q]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"FK failed: {r.stderr}"
    vals = []
    for line in r.stdout.strip().split("\n"):
        vals.extend(float(x) for x in line.split())
    assert len(vals) == 16
    return vals


def run_ik(T):
    cmd = [BINARY, "--ik"] + [str(x) for x in T]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"IK failed: {r.stderr}"
    lines = r.stdout.strip().split("\n")
    num = int(lines[0].split(":")[1].strip())
    sols = []
    for i in range(1, num + 1):
        sols.append([float(x) for x in lines[i].split()])
    return sols


def frob_err(A, B):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(A, B)))


def best_roundtrip_err(T, sols):
    """Return the minimum round-trip Frobenius error across all solutions."""
    if not sols:
        return float('inf')
    return min(frob_err(T, run_fk(s)) for s in sols)


class TestManipulator:
    @classmethod
    def setup_class(cls):
        build()

    # ------------------------------------------------------------------ #
    #  Build and linkage verification
    # ------------------------------------------------------------------ #
    def test_binary_exists(self):
        assert os.path.isfile(BINARY), f"Binary not found at {BINARY}"

    def test_dynamic_linking(self):
        """Binary must dynamically link against libmanipulator_core."""
        r = subprocess.run(
            ["ldd", BINARY], capture_output=True, text=True, timeout=5
        )
        assert r.returncode == 0, f"ldd failed: {r.stderr}"
        assert "manipulator_core" in r.stdout, \
            "Binary must be dynamically linked against libmanipulator_core.so"

    def test_fk_runs(self):
        """Forward kinematics must produce a valid 4x4 matrix."""
        q = [0.0] * 6
        T = run_fk(q)
        assert len(T) == 16

    # ------------------------------------------------------------------ #
    #  Round-trip bulk tests via the built-in verifier
    # ------------------------------------------------------------------ #
    def _run_verify(self, n):
        r = subprocess.run([BINARY, "--verify", str(n)],
                           capture_output=True, text=True, timeout=120)
        return r

    def test_roundtrip_500(self):
        r = self._run_verify(500)
        assert "STATUS: ALL PASSED" in r.stdout, \
            f"Round-trip 500 failed:\n{r.stdout}"

    def test_roundtrip_1000(self):
        r = self._run_verify(1000)
        assert "STATUS: ALL PASSED" in r.stdout, \
            f"Round-trip 1000 failed:\n{r.stdout}"

    # ------------------------------------------------------------------ #
    #  Specific configuration tests
    # ------------------------------------------------------------------ #
    def test_zero_config(self):
        q = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        T = run_fk(q)
        sols = run_ik(T)
        assert len(sols) > 0, "No solutions for zero config"
        err = best_roundtrip_err(T, sols)
        assert err < 1e-6, f"Best round-trip error {err:.2e} for zero config"

    def test_degenerate_q5_zero(self):
        """Wrist singularity: q5 = 0"""
        q = [0.5, 1.0, -0.5, 0.3, 0.0, 0.7]
        T = run_fk(q)
        sols = run_ik(T)
        assert len(sols) > 0, "No solutions for q5=0 singularity"
        err = best_roundtrip_err(T, sols)
        assert err < 1e-6, f"Best round-trip error {err:.2e} for q5=0"

    def test_degenerate_q5_pi(self):
        """Wrist singularity: q5 = pi"""
        q = [1.2, 0.8, -0.3, 0.5, math.pi, 0.4]
        T = run_fk(q)
        sols = run_ik(T)
        assert len(sols) > 0, "No solutions for q5=pi singularity"
        err = best_roundtrip_err(T, sols)
        assert err < 1e-6, f"Best round-trip error {err:.2e} for q5=pi"

    def test_multiple_branches(self):
        """Generic config must produce >= 2 solution branches"""
        q = [0.7, 1.2, -0.8, 0.3, 1.5, 0.9]
        T = run_fk(q)
        sols = run_ik(T)
        assert len(sols) >= 2, f"Expected >=2 branches, got {len(sols)}"
        err = best_roundtrip_err(T, sols)
        assert err < 1e-6, f"Best round-trip error {err:.2e}"

    def test_joint_angle_range(self):
        """All returned angles must be in [0, 2*pi)"""
        q = [1.0, 2.0, 3.0, 4.0, 1.5, 0.5]
        T = run_fk(q)
        sols = run_ik(T)
        assert len(sols) > 0
        for si, s in enumerate(sols):
            for ji, a in enumerate(s):
                assert -1e-10 <= a < 2 * math.pi + 1e-10, \
                    f"sol {si} joint {ji}: {a} out of [0,2pi)"

    def test_all_solutions_valid(self):
        """Every returned IK solution must round-trip through FK within tolerance."""
        configs = [
            [0.7, 1.2, 0.8, 0.3, 1.5, 0.9],
            [3.0, 2.5, 1.0, 4.5, 0.8, 5.0],
            [2.0, 1.0, 0.5, 3.0, 2.0, 1.0],
            [5.5, 0.3, 0.2, 4.0, 1.0, 2.5],
            [1.0, 2.5, 5.5, 5.0, 2.0, 3.5],
        ]
        for q in configs:
            T = run_fk(q)
            sols = run_ik(T)
            assert len(sols) > 0, f"No solutions for {q}"
            for i, s in enumerate(sols):
                T_check = run_fk(s)
                err = frob_err(T, T_check)
                assert err < 1e-6, \
                    f"Solution {i}/{len(sols)} invalid (error {err:.2e}) " \
                    f"for config {q}: sol={s}"

    def test_various_configs(self):
        configs = [
            [0.1, 0.5, 0.3, 0.8, 1.2, 0.6],
            [3.0, 2.5, 1.0, 4.5, 0.8, 5.0],
            [1.57, 0.0, 0.0, 1.57, 1.57, 0.0],
            [0.0, 3.14, 0.0, 0.0, 1.57, 3.14],
            [2.0, 1.0, 0.5, 3.0, 2.0, 1.0],
        ]
        for q in configs:
            T = run_fk(q)
            sols = run_ik(T)
            assert len(sols) > 0, f"No solutions for {q}"
            err = best_roundtrip_err(T, sols)
            assert err < 1e-6, \
                f"Best round-trip error {err:.2e} for config {q}"

    def test_original_recovered(self):
        """At least one IK solution must match the original angles (mod 2pi)"""
        q_orig = [0.5, 1.0, 0.5, 0.3, 1.5, 0.9]
        T = run_fk(q_orig)
        sols = run_ik(T)
        found = False
        for s in sols:
            ok = True
            for a, b in zip(q_orig, s):
                d = abs(a - b)
                d = min(d, 2 * math.pi - d)
                if d > 1e-4:
                    ok = False
                    break
            if ok:
                found = True
                break
        assert found, \
            f"No solution matches original {q_orig}. Got: {sols}"
