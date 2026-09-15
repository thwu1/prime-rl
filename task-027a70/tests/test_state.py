
"""
Tests for the elliptic filter design module and validation pipeline.
Verifies complete_elliptic_K, cd, cd_inv, elliptic_rational,
solve_degree_equation, elliptic_filter_poles_zeros, the C frequency
response analyzer, and the validation report.
"""
import sys
import os
import re
import json
import subprocess
import tempfile
import numpy as np
import pytest

sys.path.insert(0, "/app")

from scipy.special import ellipk
from scipy.signal import ellip as scipy_ellip


def load_module():
    """Import the module under test."""
    import elliptic_filter
    return elliptic_filter


# ============================================================
# Test: no scipy/mpmath dependency in module source
# ============================================================
class TestNoDependency:
    def test_no_scipy_in_source(self):
        """The module must not import scipy or mpmath."""
        with open('/app/elliptic_filter.py', 'r') as f:
            source = f.read()
        matches = re.findall(r'^\s*(?:import|from)\s+(scipy|mpmath)\b', source, re.MULTILINE)
        assert len(matches) == 0, f"Module must not depend on scipy or mpmath, found imports: {matches}"


# ============================================================
# Test complete_elliptic_K(k)
# ============================================================
class TestCompleteEllipticK:
    def test_k_zero(self):
        mod = load_module()
        assert abs(mod.complete_elliptic_K(0.0) - np.pi / 2) < 1e-12

    @pytest.mark.parametrize("k", [0.1, 0.3, 0.5, 0.7, 0.9, 0.99, 0.999, 0.9999])
    def test_against_scipy(self, k):
        mod = load_module()
        result = mod.complete_elliptic_K(k)
        expected = float(ellipk(k**2))  # scipy ellipk takes m = k^2
        rel_err = abs(result - expected) / abs(expected)
        assert rel_err < 1e-10, f"K({k}): got {result}, expected {expected}, rel_err={rel_err}"

    def test_monotonicity(self):
        mod = load_module()
        ks = [0.1, 0.3, 0.5, 0.7, 0.9, 0.99]
        vals = [mod.complete_elliptic_K(k) for k in ks]
        for i in range(len(vals) - 1):
            assert vals[i] < vals[i + 1], f"K should be monotonically increasing: K({ks[i]})={vals[i]} >= K({ks[i+1]})={vals[i+1]}"


# ============================================================
# Test cd(x, k) — Jacobian elliptic cosine
# ============================================================
class TestCd:
    def test_k_zero_reduces_to_cos(self):
        """At k=0, cd(x, 0) = cos(x)."""
        mod = load_module()
        for x in [0.0, 0.5, 1.0, 1.5, np.pi / 4]:
            result = mod.cd(x, 0.0)
            expected = np.cos(x)
            assert abs(result - expected) < 1e-12, f"cd({x}, 0) = {result}, expected cos({x}) = {expected}"

    def test_cd_at_zero(self):
        """cd(0, k) = 1 for all k."""
        mod = load_module()
        for k in [0.0, 0.3, 0.7, 0.99]:
            result = mod.cd(0.0, k)
            assert abs(result - 1.0) < 1e-12, f"cd(0, {k}) = {result}, expected 1.0"

    def test_cd_at_K(self):
        """cd(K, k) = 0."""
        mod = load_module()
        for k in [0.3, 0.5, 0.7, 0.9]:
            K = mod.complete_elliptic_K(k)
            result = mod.cd(K, k)
            assert abs(result) < 1e-10, f"cd(K, {k}) = {result}, expected 0"

    def test_cd_at_2K(self):
        """cd(2K, k) = -1."""
        mod = load_module()
        for k in [0.3, 0.5, 0.7, 0.9]:
            K = mod.complete_elliptic_K(k)
            result = mod.cd(2 * K, k)
            assert abs(result - (-1.0)) < 1e-10, f"cd(2K, {k}) = {result}, expected -1"

    def test_cd_even_symmetry(self):
        """cd(-x, k) = cd(x, k)."""
        mod = load_module()
        k = 0.8
        for x in [0.3, 0.7, 1.2]:
            assert abs(mod.cd(x, k) - mod.cd(-x, k)) < 1e-12

    def test_cd_periodicity(self):
        """cd(x + 4K, k) = cd(x, k)."""
        mod = load_module()
        k = 0.8
        K = mod.complete_elliptic_K(k)
        for x in [0.3, 0.7, 1.2]:
            assert abs(mod.cd(x, k) - mod.cd(x + 4 * K, k)) < 1e-10

    def test_cd_complex_argument(self):
        """cd(jK'/2, k) = 1/sqrt(k) — transition band midpoint identity."""
        mod = load_module()
        for k in [0.5, 0.8, 0.95]:
            K = mod.complete_elliptic_K(k)
            kp = np.sqrt(1 - k**2)
            Kp = mod.complete_elliptic_K(kp)
            x = 1j * Kp / 2
            result = mod.cd(x, k)
            expected = 1.0 / np.sqrt(k)
            assert abs(result - expected) < 1e-8, f"cd(jK'/2, {k}) = {result}, expected {expected}"

    def test_cd_intermediate_values(self):
        """cd at K/2 should be a specific value related to (1+k')/(1+k) structure."""
        mod = load_module()
        for k in [0.3, 0.6, 0.9]:
            K = mod.complete_elliptic_K(k)
            val = mod.cd(K / 2, k)
            # cd(K/2, k) should be in (0, 1)
            assert 0 < val < 1, f"cd(K/2, {k}) = {val} should be in (0,1)"
            sn_at_half = mod.sn(K / 2, k)
            cd_at_half = mod.cd(K / 2, k)
            assert abs(sn_at_half - cd_at_half) < 1e-10, "sn(K/2) should equal cd(K/2)"


# ============================================================
# Test cd_inv(y, k)
# ============================================================
class TestCdInv:
    def test_not_raising(self):
        """cd_inv must be implemented (not raise NotImplementedError)."""
        mod = load_module()
        try:
            mod.cd_inv(0.5, 0.5)
        except NotImplementedError:
            pytest.fail("cd_inv is not implemented — it still raises NotImplementedError")

    def test_round_trip_real(self):
        """cd_inv(cd(x, k), k) ~ x for real x in [0, K]."""
        mod = load_module()
        for k in [0.3, 0.7, 0.95]:
            K = mod.complete_elliptic_K(k)
            for x in [0.1 * K, 0.3 * K, 0.5 * K, 0.8 * K]:
                y = mod.cd(x, k)
                x_recovered = mod.cd_inv(y, k)
                assert abs(x_recovered - x) < 1e-8, f"round trip cd_inv(cd({x}, {k}), {k}) = {x_recovered}, expected {x}"

    def test_cd_inv_of_one(self):
        """cd_inv(1, k) = 0."""
        mod = load_module()
        for k in [0.3, 0.7, 0.95]:
            result = mod.cd_inv(1.0, k)
            assert abs(result) < 1e-7, f"cd_inv(1, {k}) = {result}, expected 0"

    def test_cd_inv_of_zero(self):
        """cd_inv(0, k) = K."""
        mod = load_module()
        for k in [0.3, 0.7, 0.95]:
            K = mod.complete_elliptic_K(k)
            result = mod.cd_inv(0.0, k)
            assert abs(result - K) < 1e-8, f"cd_inv(0, {k}) = {result}, expected K={K}"

    def test_cd_inv_round_trip_many(self):
        """Exhaustive round-trip test across many k and x values."""
        mod = load_module()
        for k in [0.1, 0.4, 0.6, 0.85, 0.99]:
            K = mod.complete_elliptic_K(k)
            for frac in [0.05, 0.15, 0.25, 0.4, 0.6, 0.75, 0.9, 0.95]:
                x = frac * K
                y = mod.cd(x, k)
                x_rec = mod.cd_inv(y, k)
                assert abs(x_rec - x) < 1e-7, (
                    f"k={k}, x={x}: cd_inv(cd(x)) = {x_rec}, expected {x}"
                )

    def test_cd_inv_k_zero(self):
        """cd_inv(y, 0) = arccos(y)."""
        mod = load_module()
        for y in [0.0, 0.3, 0.7, 1.0]:
            result = mod.cd_inv(y, 0.0)
            expected = np.arccos(y)
            assert abs(result - expected) < 1e-10, f"cd_inv({y}, 0) = {result}, expected {expected}"


# ============================================================
# Test elliptic_rational(x, N, k)
# ============================================================
class TestEllipticRational:
    def test_not_raising(self):
        """elliptic_rational must be implemented (not raise NotImplementedError)."""
        mod = load_module()
        try:
            mod.elliptic_rational(0.5, 3, 0.9)
        except NotImplementedError:
            pytest.fail("elliptic_rational is not implemented — it still raises NotImplementedError")

    def test_RN_at_one(self):
        """R_N(1, k) = 1."""
        mod = load_module()
        for N in [3, 4, 5, 7]:
            for k in [0.9, 0.99]:
                result = mod.elliptic_rational(1.0, N, k)
                assert abs(result - 1.0) < 1e-10, f"R_{N}(1, {k}) = {result}, expected 1"

    def test_RN_at_neg_one(self):
        """R_N(-1, k) = (-1)^N."""
        mod = load_module()
        for N in [3, 4, 5]:
            for k in [0.9, 0.99]:
                result = mod.elliptic_rational(-1.0, N, k)
                expected = (-1.0) ** N
                assert abs(result - expected) < 1e-10, f"R_{N}(-1, {k}) = {result}, expected {expected}"

    def test_RN_odd_at_zero(self):
        """R_N(0, k) = 0 for odd N."""
        mod = load_module()
        for N in [3, 5, 7]:
            for k in [0.9, 0.99]:
                result = mod.elliptic_rational(0.0, N, k)
                assert abs(result) < 1e-10, f"R_{N}(0, {k}) = {result}, expected 0"

    def test_RN_equiripple_passband(self):
        """In the passband |x| <= 1, |R_N(x)| <= 1."""
        mod = load_module()
        N, k = 5, 0.95
        for x in np.linspace(-1, 1, 50):
            val = abs(mod.elliptic_rational(x, N, k))
            assert val <= 1.0 + 1e-9, f"|R_{N}({x}, {k})| = {val} > 1"

    def test_RN_symmetry(self):
        """R_N(1/(k*x)) = 1/(k_tilde * R_N(x))."""
        mod = load_module()
        N, k = 5, 0.95
        k_tilde = mod.solve_degree_equation(N, k)
        for x in [0.3, 0.5, 0.8]:
            lhs = mod.elliptic_rational(1.0 / (k * x), N, k)
            rhs = 1.0 / (k_tilde * mod.elliptic_rational(x, N, k))
            rel = abs(lhs - rhs) / (abs(rhs) + 1e-30)
            assert rel < 1e-8, f"Symmetry check failed: R_{N}(1/(k*{x})) = {lhs} vs 1/(k_tilde*R_{N}({x})) = {rhs}"

    def test_RN_stopband_bound(self):
        """In the stopband |x| >= 1/k, |R_N(x)| >= 1/k_tilde."""
        mod = load_module()
        N, k = 5, 0.95
        k_tilde = mod.solve_degree_equation(N, k)
        threshold = 1.0 / k_tilde
        for x_mult in [1.01, 1.1, 1.5, 2.0]:
            x = x_mult / k
            val = abs(mod.elliptic_rational(x, N, k))
            assert val >= threshold - 1e-6, (
                f"|R_{N}({x}, {k})| = {val} < 1/k_tilde = {threshold}"
            )


# ============================================================
# Test solve_degree_equation(N, k)
# ============================================================
class TestDegreeEquation:
    def test_N2_is_landen(self):
        """For N=2, k_tilde should satisfy K'/K ratio = 2 * K'(k)/K(k)."""
        mod = load_module()
        for k in [0.5, 0.8, 0.95, 0.99]:
            K = float(ellipk(k**2))
            Kp = float(ellipk(1 - k**2))
            target_ratio = 2 * Kp / K
            k_tilde = mod.solve_degree_equation(2, k)
            K_tilde = float(ellipk(k_tilde**2))
            Kp_tilde = float(ellipk(1 - k_tilde**2))
            actual_ratio = Kp_tilde / K_tilde
            rel_err = abs(actual_ratio - target_ratio) / target_ratio
            assert rel_err < 1e-8, f"N=2, k={k}: ratio={actual_ratio}, expected={target_ratio}"

    @pytest.mark.parametrize("N", [3, 4, 5, 7, 9])
    def test_degree_equation_ratio(self, N):
        """K'(k_tilde)/K(k_tilde) = N * K'(k)/K(k)."""
        mod = load_module()
        k = 0.95
        K = float(ellipk(k**2))
        Kp = float(ellipk(1 - k**2))
        target_ratio = N * Kp / K

        k_tilde = mod.solve_degree_equation(N, k)
        assert 0 < k_tilde < k, f"k_tilde={k_tilde} should be in (0, {k})"

        K_tilde = float(ellipk(k_tilde**2))
        Kp_tilde = float(ellipk(1 - k_tilde**2))
        actual_ratio = Kp_tilde / K_tilde
        rel_err = abs(actual_ratio - target_ratio) / target_ratio
        assert rel_err < 1e-8, f"N={N}: ratio={actual_ratio}, expected={target_ratio}, rel_err={rel_err}"

    def test_k_tilde_decreases_with_N(self):
        """Higher N -> smaller k_tilde (better discrimination)."""
        mod = load_module()
        k = 0.95
        k_tildes = [mod.solve_degree_equation(N, k) for N in [3, 5, 7, 9]]
        for i in range(len(k_tildes) - 1):
            assert k_tildes[i] > k_tildes[i + 1], "k_tilde should decrease with increasing N"


# ============================================================
# Test elliptic_filter_poles_zeros — full pipeline
# ============================================================
class TestEllipticFilter:
    @pytest.mark.parametrize(
        "N, Rp, Rs",
        [
            (3, 1.0, 40.0),
            (4, 0.5, 60.0),
            (5, 1.0, 80.0),
            (5, 0.1, 50.0),
            (7, 0.5, 80.0),
            (9, 1.0, 100.0),
        ],
    )
    def test_against_scipy(self, N, Rp, Rs):
        """Poles and zeros must match scipy.signal.ellip to 1e-7 relative."""
        mod = load_module()
        z_ref, p_ref, k_ref = scipy_ellip(N, Rp, Rs, 1.0, analog=True, output="zpk")

        z_stu, p_stu, k_stu = mod.elliptic_filter_poles_zeros(N, Rp, Rs)
        z_stu = np.array(z_stu, dtype=complex)
        p_stu = np.array(p_stu, dtype=complex)
        k_stu = float(k_stu)
        z_ref = np.array(z_ref, dtype=complex)
        p_ref = np.array(p_ref, dtype=complex)
        k_ref = float(k_ref)

        def sort_key(arr):
            return arr[np.lexsort((arr.imag, arr.real, np.abs(arr.imag)))]

        z_stu_s = sort_key(z_stu)
        z_ref_s = sort_key(z_ref)
        p_stu_s = sort_key(p_stu)
        p_ref_s = sort_key(p_ref)

        assert len(z_stu_s) == len(z_ref_s), f"N={N}: wrong number of zeros: {len(z_stu_s)} vs {len(z_ref_s)}"
        assert len(p_stu_s) == len(p_ref_s), f"N={N}: wrong number of poles: {len(p_stu_s)} vs {len(p_ref_s)}"

        for i, (zs, zr) in enumerate(zip(z_stu_s, z_ref_s)):
            rel = abs(zs - zr) / (abs(zr) + 1e-30)
            assert rel < 1e-7, f"N={N},Rp={Rp},Rs={Rs}: zero[{i}] mismatch: {zs} vs {zr}, rel={rel}"

        for i, (ps, pr) in enumerate(zip(p_stu_s, p_ref_s)):
            rel = abs(ps - pr) / (abs(pr) + 1e-30)
            assert rel < 1e-7, f"N={N},Rp={Rp},Rs={Rs}: pole[{i}] mismatch: {ps} vs {pr}, rel={rel}"

        if abs(k_ref) > 1e-15:
            rel_k = abs(k_stu - k_ref) / abs(k_ref)
            assert rel_k < 1e-7, f"N={N}: gain mismatch: {k_stu} vs {k_ref}, rel={rel_k}"

    def test_zeros_purely_imaginary(self):
        """All finite zeros should be purely imaginary for a lowpass elliptic filter."""
        mod = load_module()
        z, p, k = mod.elliptic_filter_poles_zeros(5, 1.0, 60.0)
        z = np.array(z, dtype=complex)
        for zi in z:
            assert abs(zi.real) < 1e-10, f"Zero {zi} has non-zero real part"

    def test_poles_left_half_plane(self):
        """All poles must be in the left half of the s-plane."""
        mod = load_module()
        z, p, k = mod.elliptic_filter_poles_zeros(5, 1.0, 60.0)
        p = np.array(p, dtype=complex)
        for pi in p:
            assert pi.real < 0, f"Pole {pi} is not in the left half-plane"

    def test_correct_pole_zero_count(self):
        """An Nth order elliptic filter has N poles and N-1 (odd) or N (even) finite zeros."""
        mod = load_module()
        for N in [3, 4, 5, 7]:
            z, p, k = mod.elliptic_filter_poles_zeros(N, 1.0, 60.0)
            z = np.array(z, dtype=complex)
            p = np.array(p, dtype=complex)
            assert len(p) == N, f"N={N}: expected {N} poles, got {len(p)}"
            if N % 2 == 0:
                assert len(z) == N, f"N={N}(even): expected {N} zeros, got {len(z)}"
            else:
                assert len(z) == N - 1, f"N={N}(odd): expected {N-1} zeros, got {len(z)}"

    def test_frequency_response_passband(self):
        """Verify passband ripple constraint: |H(jw)|^2 >= 10^(-Rp/10) for w in [0, 1]."""
        mod = load_module()
        N, Rp, Rs = 5, 1.0, 60.0
        z, p, k = mod.elliptic_filter_poles_zeros(N, Rp, Rs)
        z = np.array(z, dtype=complex)
        p = np.array(p, dtype=complex)
        k = float(k)

        freqs = np.linspace(0.01, 1.0, 100)
        for w in freqs:
            s = 1j * w
            num = k * np.prod(s - z)
            den = np.prod(s - p)
            H = abs(num / den)
            H2 = H**2
            threshold = 10 ** (-Rp / 10)
            assert H2 >= threshold - 1e-6, f"w={w}: |H|^2={H2} < {threshold}"

    def test_frequency_response_stopband(self):
        """Verify stopband attenuation: |H(jw)|^2 <= 10^(-Rs/10) for w >= stopband edge."""
        mod = load_module()
        N, Rp, Rs = 5, 1.0, 60.0
        z, p, k_gain = mod.elliptic_filter_poles_zeros(N, Rp, Rs)
        z = np.array(z, dtype=complex)
        p = np.array(p, dtype=complex)

        z_ref, p_ref, k_ref = scipy_ellip(N, Rp, Rs, 1.0, analog=True, output="zpk")
        w_stop = float(np.min(np.abs(z_ref)))

        freqs = np.linspace(w_stop * 1.01, w_stop * 3, 50)
        threshold = 10 ** (-Rs / 10)
        for w in freqs:
            s = 1j * w
            num = k_gain * np.prod(s - z)
            den = np.prod(s - p)
            H2 = abs(num / den) ** 2
            assert H2 <= threshold + 1e-6, f"w={w}: |H|^2={H2} > threshold={threshold}"

    def test_gain_not_one(self):
        """Gain must not be the placeholder value of 1.0 for all specs."""
        mod = load_module()
        # For even-order filters, gain should be significantly less than 1
        z, p, k = mod.elliptic_filter_poles_zeros(4, 0.5, 60.0)
        z_ref, p_ref, k_ref = scipy_ellip(4, 0.5, 60.0, 1.0, analog=True, output="zpk")
        rel = abs(float(k) - float(k_ref)) / abs(float(k_ref))
        assert rel < 1e-7, f"Gain mismatch: got {k}, expected {k_ref}, rel_err={rel}"


# ============================================================
# Test C frequency response analyzer
# ============================================================
class TestFreqrespTool:
    def test_binary_exists(self):
        """freqresp binary must be built at /app/freqresp."""
        assert os.path.isfile('/app/freqresp'), \
            "freqresp binary not found at /app/freqresp — build it with make"

    def test_binary_executable(self):
        """freqresp must be executable."""
        if not os.path.isfile('/app/freqresp'):
            pytest.skip("freqresp not built")
        assert os.access('/app/freqresp', os.X_OK), "freqresp is not executable"

    def test_butterworth_reference(self):
        """Verify C tool with known 2nd-order Butterworth: |H(j1)| = 1/sqrt(2)."""
        if not os.path.isfile('/app/freqresp'):
            pytest.skip("freqresp not built")

        # Butterworth 2nd order: poles at -1/sqrt(2) +/- j/sqrt(2), no zeros, gain=1
        s2 = 1.0 / np.sqrt(2)
        zpk_content = f"0 2 1.0\n{-s2:.15e} {s2:.15e}\n{-s2:.15e} {-s2:.15e}\n"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, dir='/tmp') as f:
            f.write(zpk_content)
            zpk_path = f.name

        try:
            result = subprocess.run(
                ['/app/freqresp', zpk_path, '1.0', '1.0', '1'],
                capture_output=True, text=True, timeout=10
            )
            assert result.returncode == 0, f"freqresp failed: {result.stderr}"
            lines = [l for l in result.stdout.strip().split('\n') if l.strip() and not l.startswith('#')]
            assert len(lines) >= 1, "No output from freqresp"
            parts = lines[0].split()
            H_mag = float(parts[1])
            expected = 1.0 / np.sqrt(2)
            assert abs(H_mag - expected) < 0.01, \
                f"|H(j1)| = {H_mag}, expected {expected:.4f}"
        finally:
            os.unlink(zpk_path)

    def test_elliptic_filter_response(self):
        """Verify C tool with a 3rd-order elliptic filter from the module."""
        if not os.path.isfile('/app/freqresp'):
            pytest.skip("freqresp not built")

        mod = load_module()
        try:
            z, p, k = mod.elliptic_filter_poles_zeros(3, 1.0, 40.0)
        except Exception:
            pytest.skip("elliptic_filter_poles_zeros not working")

        z = np.array(z, dtype=complex)
        p = np.array(p, dtype=complex)
        k = float(k)

        zpk_content = f"{len(z)} {len(p)} {k:.15e}\n"
        for zi in z:
            zpk_content += f"{zi.real:.15e} {zi.imag:.15e}\n"
        for pi in p:
            zpk_content += f"{pi.real:.15e} {pi.imag:.15e}\n"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, dir='/tmp') as f:
            f.write(zpk_content)
            zpk_path = f.name

        try:
            # Check DC gain (w = 0.01)
            result = subprocess.run(
                ['/app/freqresp', zpk_path, '0.01', '0.01', '1'],
                capture_output=True, text=True, timeout=10
            )
            assert result.returncode == 0, f"freqresp failed: {result.stderr}"
            lines = [l for l in result.stdout.strip().split('\n') if l.strip() and not l.startswith('#')]
            dc_db = float(lines[0].split()[2])

            # For 3rd order (odd), DC gain should be ~0 dB
            assert abs(dc_db) < 1.0, f"DC gain = {dc_db:.2f} dB, expected ~0 dB"

            # Compare C tool magnitude with direct Python computation at w=1.0
            result = subprocess.run(
                ['/app/freqresp', zpk_path, '1.0', '1.0', '1'],
                capture_output=True, text=True, timeout=10
            )
            c_mag = float(result.stdout.strip().split('\n')[-1].split()[1])

            s = 1j * 1.0
            py_mag = abs(k * np.prod(s - z) / np.prod(s - p))
            assert abs(c_mag - py_mag) < 0.001, \
                f"C tool: {c_mag:.6f}, Python: {py_mag:.6f}"
        finally:
            os.unlink(zpk_path)


# ============================================================
# Test validation report
# ============================================================
class TestValidationReport:
    def test_report_exists(self):
        """validation_report.json must exist at /app/."""
        assert os.path.isfile('/app/validation_report.json'), \
            "validation_report.json not found at /app/"

    def test_report_valid_json(self):
        """Report must be valid JSON."""
        if not os.path.isfile('/app/validation_report.json'):
            pytest.skip("validation_report.json not found")
        with open('/app/validation_report.json') as f:
            data = json.load(f)
        assert isinstance(data, dict), "Report root must be a JSON object"

    def test_report_has_all_specs(self):
        """Report must contain entries for all 6 filter specifications."""
        if not os.path.isfile('/app/validation_report.json'):
            pytest.skip("validation_report.json not found")
        with open('/app/validation_report.json') as f:
            report = json.load(f)
        with open('/app/filter_specs.json') as f:
            specs = json.load(f)
        assert 'filters' in report, "Report missing 'filters' key"
        assert len(report['filters']) == len(specs), \
            f"Report has {len(report['filters'])} entries, expected {len(specs)}"

    def test_report_required_fields(self):
        """Each entry must have required fields."""
        if not os.path.isfile('/app/validation_report.json'):
            pytest.skip("validation_report.json not found")
        with open('/app/validation_report.json') as f:
            report = json.load(f)
        required = ['N', 'Rp', 'Rs', 'dc_gain_db', 'passband_edge_db', 'num_zeros', 'num_poles']
        for entry in report.get('filters', []):
            for field in required:
                assert field in entry, \
                    f"Missing field '{field}' in entry for N={entry.get('N', '?')}"

    def test_dc_gain_reasonable(self):
        """DC gain should be close to 0 dB (within Rp + 1 dB)."""
        if not os.path.isfile('/app/validation_report.json'):
            pytest.skip("validation_report.json not found")
        with open('/app/validation_report.json') as f:
            report = json.load(f)
        for entry in report['filters']:
            assert abs(entry['dc_gain_db']) < entry['Rp'] + 1.0, \
                f"N={entry['N']}: DC gain = {entry['dc_gain_db']:.2f} dB, " \
                f"expected within +/-{entry['Rp'] + 1.0:.1f} dB of 0"

    def test_passband_edge_within_spec(self):
        """Passband edge gain must satisfy the ripple specification."""
        if not os.path.isfile('/app/validation_report.json'):
            pytest.skip("validation_report.json not found")
        with open('/app/validation_report.json') as f:
            report = json.load(f)
        for entry in report['filters']:
            assert entry['passband_edge_db'] >= -entry['Rp'] - 1.0, \
                f"N={entry['N']}: passband edge = {entry['passband_edge_db']:.2f} dB, " \
                f"spec requires >= {-entry['Rp']:.1f} dB"
            assert entry['passband_edge_db'] <= 1.0, \
                f"N={entry['N']}: passband edge = {entry['passband_edge_db']:.2f} dB > 1.0 dB"

    def test_pole_zero_counts(self):
        """Pole and zero counts must match filter order."""
        if not os.path.isfile('/app/validation_report.json'):
            pytest.skip("validation_report.json not found")
        with open('/app/validation_report.json') as f:
            report = json.load(f)
        for entry in report['filters']:
            N = entry['N']
            assert entry['num_poles'] == N, \
                f"N={N}: expected {N} poles, got {entry['num_poles']}"
            expected_z = N - 1 if N % 2 == 1 else N
            assert entry['num_zeros'] == expected_z, \
                f"N={N}: expected {expected_z} zeros, got {entry['num_zeros']}"
