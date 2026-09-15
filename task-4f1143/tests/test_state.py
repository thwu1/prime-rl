
import ctypes
import os
import sys

import numpy as np
import pytest
from scipy import signal
from scipy.special import ellipk as scipy_ellipk, ellipj


# ──────────────────────────────────────────────────────────────
# Section 0: C Shared Library Tests (independent of Python module)
# ──────────────────────────────────────────────────────────────

class TestCLibrary:
    """Test the C shared library directly via ctypes."""

    def test_library_exists(self):
        assert os.path.exists("/app/libelliptic.so"), \
            "/app/libelliptic.so not found — compile elliptic_core.c as a shared library"

    @pytest.mark.parametrize("k", [0.01, 0.1, 0.5, 0.9, 0.99])
    def test_ellipk_c_values(self, k):
        lib = ctypes.CDLL("/app/libelliptic.so")
        lib.ellipk_c.argtypes = [ctypes.c_double,
                                  ctypes.POINTER(ctypes.c_double),
                                  ctypes.POINTER(ctypes.c_double)]
        lib.ellipk_c.restype = None

        K_out = ctypes.c_double()
        Kp_out = ctypes.c_double()
        lib.ellipk_c(k, ctypes.byref(K_out), ctypes.byref(Kp_out))

        K_ref = scipy_ellipk(k ** 2)
        kp = np.sqrt(1 - k ** 2)
        Kp_ref = scipy_ellipk(kp ** 2)

        assert abs(K_out.value - K_ref) < 1e-10, \
            f"ellipk_c K({k}): got {K_out.value}, expected {K_ref}"
        assert abs(Kp_out.value - Kp_ref) < 1e-10, \
            f"ellipk_c K'({k}): got {Kp_out.value}, expected {Kp_ref}"

    @pytest.mark.parametrize("k", [0.3, 0.7])
    def test_cd_c_values(self, k):
        lib = ctypes.CDLL("/app/libelliptic.so")
        lib.cd_c.argtypes = [ctypes.c_double, ctypes.c_double]
        lib.cd_c.restype = ctypes.c_double

        for u in [0.0, 0.25, 0.5, 0.75, 1.0]:
            val = lib.cd_c(u, k)
            K_ref = scipy_ellipk(k ** 2)
            u_actual = u * K_ref
            sn, cn, dn, _ = ellipj(u_actual, k ** 2)
            ref = cn / dn if abs(dn) > 1e-15 else 0.0
            assert abs(val - ref) < 1e-9, \
                f"cd_c({u}, {k}): got {val}, expected {ref}"

    def test_cd_c_boundary(self):
        lib = ctypes.CDLL("/app/libelliptic.so")
        lib.cd_c.argtypes = [ctypes.c_double, ctypes.c_double]
        lib.cd_c.restype = ctypes.c_double

        for k in [0.3, 0.5, 0.7]:
            assert abs(lib.cd_c(0.0, k) - 1.0) < 1e-12, \
                f"cd_c(0, {k}) should be 1"
            assert abs(lib.cd_c(1.0, k)) < 1e-9, \
                f"cd_c(1, {k}) should be 0"


# ──────────────────────────────────────────────────────────────
# Import Python module (with fallback for targeted error messages)
# ──────────────────────────────────────────────────────────────

sys.path.insert(0, "/app")
try:
    import elliptic
    _IMPORT_OK = True
    _IMPORT_ERR = ""
except Exception as e:
    elliptic = None
    _IMPORT_OK = False
    _IMPORT_ERR = str(e)


def _require_module():
    if not _IMPORT_OK:
        pytest.fail(f"elliptic module import failed: {_IMPORT_ERR}")


# ──────────────────────────────────────────────────────────────
# Section 1: Complete elliptic integral K(k)
# ──────────────────────────────────────────────────────────────

class TestEllipticIntegralK:
    """Verify K(k) against scipy.special.ellipk (which takes m=k^2)."""

    def setup_method(self):
        _require_module()

    @pytest.mark.parametrize("k", [0.01, 0.1, 0.3, 0.5, 0.7, 0.9, 0.99, 0.999])
    def test_K_values(self, k):
        K_ours, Kp_ours = elliptic.ellipk(k)
        K_ref = scipy_ellipk(k ** 2)
        kp = np.sqrt(1 - k ** 2)
        Kp_ref = scipy_ellipk(kp ** 2)
        assert abs(K_ours - K_ref) < 1e-10, f"K({k}): got {K_ours}, expected {K_ref}"
        assert abs(Kp_ours - Kp_ref) < 1e-10, f"K'({k}): got {Kp_ours}, expected {Kp_ref}"

    def test_K_zero(self):
        K, Kp = elliptic.ellipk(1e-15)
        assert abs(K - np.pi / 2) < 1e-6

    def test_K_ratio_monotone(self):
        """K'/K must decrease as k increases."""
        ratios = []
        for k in [0.1, 0.3, 0.5, 0.7, 0.9]:
            K, Kp = elliptic.ellipk(k)
            ratios.append(Kp / K)
        for i in range(len(ratios) - 1):
            assert ratios[i] > ratios[i + 1]


# ──────────────────────────────────────────────────────────────
# Section 2: Jacobian elliptic function cd(u, k)
# ──────────────────────────────────────────────────────────────

class TestCd:
    """Test cd(u, k) against scipy.special.ellipj."""

    def setup_method(self):
        _require_module()

    def _ref_cd(self, u_normalized, k):
        """Compute cd using scipy. u_normalized is in units of K."""
        K_ref = scipy_ellipk(k ** 2)
        u_actual = u_normalized * K_ref
        sn, cn, dn, _ = ellipj(u_actual, k ** 2)
        return cn / dn

    @pytest.mark.parametrize("k", [0.1, 0.5, 0.8, 0.95])
    def test_cd_real_values(self, k):
        for u in [0.0, 0.25, 0.5, 0.75, 1.0]:
            val = elliptic.cd(u, k)
            ref = self._ref_cd(u, k)
            assert abs(val - ref) < 1e-9, f"cd({u}, {k}): got {val}, expected {ref}"

    @pytest.mark.parametrize("k", [0.3, 0.7])
    def test_cd_at_zero(self, k):
        """cd(0, k) = 1."""
        assert abs(elliptic.cd(0.0, k) - 1.0) < 1e-12

    @pytest.mark.parametrize("k", [0.3, 0.7])
    def test_cd_at_K(self, k):
        """cd(K, k) = 0 in normalized units means cd(1, k) = 0."""
        assert abs(elliptic.cd(1.0, k)) < 1e-9

    def test_cd_reduces_to_cos(self):
        """At k=0, cd(u,0) = cos(pi/2 * u)."""
        for u in [0.0, 0.3, 0.7, 1.0, 1.5]:
            val = elliptic.cd(u, 0.0)
            ref = np.cos(np.pi / 2 * u)
            assert abs(val - ref) < 1e-9, f"cd({u}, 0): got {val}, expected {ref}"


# ──────────────────────────────────────────────────────────────
# Section 3: Inverse cd
# ──────────────────────────────────────────────────────────────

class TestCdInverse:

    def setup_method(self):
        _require_module()

    @pytest.mark.parametrize("k", [0.2, 0.5, 0.8])
    def test_roundtrip(self, k):
        """cd_inv(cd(u, k), k) == u for real u in [0, 1)."""
        for u in [0.0, 0.1, 0.25, 0.5, 0.75, 0.99]:
            w = elliptic.cd(u, k)
            u_recovered = elliptic.cd_inv(w, k)
            assert abs(u_recovered.real - u) < 1e-7, (
                f"roundtrip cd_inv(cd({u},{k}),{k}) = {u_recovered}, expected {u}"
            )
            assert abs(u_recovered.imag) < 1e-7

    @pytest.mark.parametrize("k", [0.3, 0.7])
    def test_cd_inv_at_1(self, k):
        """cd_inv(1, k) = 0."""
        val = elliptic.cd_inv(1.0, k)
        assert abs(val) < 1e-8

    @pytest.mark.parametrize("k", [0.3, 0.7])
    def test_cd_inv_at_0(self, k):
        """cd_inv(0, k) = 1 (i.e. K in normalized units)."""
        val = elliptic.cd_inv(0.0, k)
        assert abs(val - 1.0) < 1e-7


# ──────────────────────────────────────────────────────────────
# Section 4: Elliptic rational function R_N and degree equation
# ──────────────────────────────────────────────────────────────

class TestEllipticRational:

    def setup_method(self):
        _require_module()

    def test_RN_at_one(self):
        """R_N(1) = 1 for all N and k."""
        for N in [3, 5, 7]:
            for k in [0.3, 0.7]:
                val, _ = elliptic.elliptic_rational(1.0, N, k)
                assert abs(val - 1.0) < 1e-7, f"R_{N}(1, {k}) = {val}"

    def test_RN_equiripple_passband(self):
        """In the passband |x| <= 1, R_N oscillates between -1 and +1."""
        N, k = 5, 0.5
        xs = np.linspace(-0.99, 0.99, 500)
        vals = np.array([elliptic.elliptic_rational(x, N, k)[0] for x in xs])
        assert np.all(np.abs(vals) <= 1.0 + 1e-5), "R_N exceeds 1 in passband"

    def test_RN_passband_extrema_count(self):
        """R_N should have equiripple behavior with multiple extrema in [-1, 1]."""
        N, k = 5, 0.5
        xs = np.linspace(-0.999, 0.999, 2000)
        vals = np.array([elliptic.elliptic_rational(x, N, k)[0] for x in xs])
        diffs = np.diff(vals)
        sign_changes = np.sum(np.diff(np.sign(diffs)) != 0)
        assert sign_changes >= N - 2, (
            f"Expected >= {N-2} direction changes, got {sign_changes}"
        )

    def test_RN_bounded_in_passband(self):
        """R_N values must stay bounded in the passband."""
        N, k = 5, 0.5
        xs = np.linspace(0.01, 0.99, 50)
        vals = [elliptic.elliptic_rational(x, N, k)[0] for x in xs]
        assert all(abs(v) <= 1.0 + 1e-5 for v in vals), (
            "R_N values exceed 1 in passband"
        )

    def test_degree_equation_consistency(self):
        """Verify that ellipdeg produces consistent K ratios."""
        for N in [3, 5, 7]:
            k = 0.6
            m = k * k
            m_tilde = elliptic.ellipdeg(N, m)
            k_tilde = np.sqrt(m_tilde)
            K, Kp = elliptic.ellipk(k)
            Kt, Ktp = elliptic.ellipk(k_tilde)
            lhs = N * Ktp / Kt
            rhs = Kp / K
            assert abs(lhs - rhs) < 1e-6, (
                f"Degree eq for N={N}: N*K_tilde'/K_tilde={lhs}, K'/K={rhs}"
            )


# ──────────────────────────────────────────────────────────────
# Section 5: Full elliptic filter design vs scipy.signal.ellipap
# ──────────────────────────────────────────────────────────────

def _sort_complex(arr):
    """Sort complex array by imaginary part then real part for comparison."""
    arr = np.array(arr, dtype=complex)
    idx = np.lexsort((arr.real, arr.imag))
    return arr[idx]


class TestEllipticFilter:

    def setup_method(self):
        _require_module()

    CASES = [
        (3, 1.0, 40.0),
        (4, 0.5, 50.0),
        (5, 1.0, 60.0),
        (5, 0.1, 40.0),
        (6, 0.5, 45.0),
        (7, 1.0, 80.0),
        (9, 0.5, 60.0),
    ]

    @pytest.mark.parametrize("N,Rp,Rs", CASES)
    def test_pole_locations(self, N, Rp, Rs):
        """Poles must match scipy.signal.ellipap within tolerance."""
        z_ours, p_ours, k_ours = elliptic.elliptic_filter(N, Rp, Rs)
        z_ref, p_ref, k_ref = signal.ellipap(N, Rp, Rs)

        p_ours_sorted = _sort_complex(p_ours)
        p_ref_sorted = _sort_complex(p_ref)

        assert len(p_ours_sorted) == len(p_ref_sorted), (
            f"N={N}: pole count {len(p_ours_sorted)} != {len(p_ref_sorted)}"
        )
        for i in range(len(p_ref_sorted)):
            assert abs(p_ours_sorted[i] - p_ref_sorted[i]) < 1e-7, (
                f"N={N},Rp={Rp},Rs={Rs} pole[{i}]: "
                f"got {p_ours_sorted[i]}, expected {p_ref_sorted[i]}"
            )

    @pytest.mark.parametrize("N,Rp,Rs", CASES)
    def test_zero_locations(self, N, Rp, Rs):
        """Zeros must match scipy.signal.ellipap within tolerance."""
        z_ours, p_ours, k_ours = elliptic.elliptic_filter(N, Rp, Rs)
        z_ref, p_ref, k_ref = signal.ellipap(N, Rp, Rs)

        z_ours_sorted = _sort_complex(z_ours)
        z_ref_sorted = _sort_complex(z_ref)

        assert len(z_ours_sorted) == len(z_ref_sorted), (
            f"N={N}: zero count {len(z_ours_sorted)} != {len(z_ref_sorted)}"
        )
        for i in range(len(z_ref_sorted)):
            assert abs(z_ours_sorted[i] - z_ref_sorted[i]) < 1e-7, (
                f"N={N},Rp={Rp},Rs={Rs} zero[{i}]: "
                f"got {z_ours_sorted[i]}, expected {z_ref_sorted[i]}"
            )

    @pytest.mark.parametrize("N,Rp,Rs", CASES)
    def test_gain(self, N, Rp, Rs):
        """Gain factor must match."""
        z_ours, p_ours, k_ours = elliptic.elliptic_filter(N, Rp, Rs)
        z_ref, p_ref, k_ref = signal.ellipap(N, Rp, Rs)
        assert abs(k_ours - k_ref) < 1e-7, (
            f"N={N},Rp={Rp},Rs={Rs} gain: got {k_ours}, expected {k_ref}"
        )

    @pytest.mark.parametrize("N,Rp,Rs", CASES)
    def test_frequency_response_passband_edge(self, N, Rp, Rs):
        """At omega=1 (passband edge), magnitude should be -Rp dB."""
        z, p, k = elliptic.elliptic_filter(N, Rp, Rs)
        b, a = signal.zpk2tf(z, p, k)
        w_test = np.array([1.0])
        _, h = signal.freqs(b, a, w_test)
        mag_db = 20 * np.log10(np.abs(h[0]))
        assert abs(mag_db - (-Rp)) < 0.01, (
            f"N={N}: passband edge mag = {mag_db:.4f} dB, expected {-Rp} dB"
        )

    @pytest.mark.parametrize("N,Rp,Rs", CASES)
    def test_frequency_response_dc(self, N, Rp, Rs):
        """At DC (omega=0), check correct behavior."""
        z, p, k = elliptic.elliptic_filter(N, Rp, Rs)
        b, a = signal.zpk2tf(z, p, k)
        w_test = np.array([1e-10])
        _, h = signal.freqs(b, a, w_test)
        mag = np.abs(h[0])
        if N % 2 == 1:
            assert abs(mag - 1.0) < 1e-4, f"N={N} odd: H(0)={mag}, expected 1"
        else:
            expected = 10 ** (-Rp / 20)
            assert abs(mag - expected) < 1e-4, (
                f"N={N} even: H(0)={mag}, expected {expected}"
            )

    @pytest.mark.parametrize("N,Rp,Rs", CASES)
    def test_frequency_response_stopband(self, N, Rp, Rs):
        """In the stopband, magnitude must be <= -Rs dB."""
        z, p, k = elliptic.elliptic_filter(N, Rp, Rs)
        b, a = signal.zpk2tf(z, p, k)

        z_imag = np.abs(z.imag[z.imag != 0])
        if len(z_imag) > 0:
            ws = np.min(z_imag)
        else:
            ws = 2.0

        w_test = np.linspace(ws * 1.5, ws * 5, 50)
        if len(w_test) > 0:
            _, h = signal.freqs(b, a, w_test)
            mag_db = 20 * np.log10(np.abs(h) + 1e-30)
            assert np.all(mag_db < -Rs + 1.0), (
                f"N={N}: stopband violation, max mag = {np.max(mag_db):.2f} dB"
            )

    @pytest.mark.parametrize("N,Rp,Rs", CASES)
    def test_all_poles_in_left_half_plane(self, N, Rp, Rs):
        """All poles must have negative real part (stability)."""
        _, p, _ = elliptic.elliptic_filter(N, Rp, Rs)
        for i, pole in enumerate(p):
            assert pole.real < 0, (
                f"N={N}: pole[{i}] = {pole} is not in left half plane"
            )

    @pytest.mark.parametrize("N,Rp,Rs", CASES)
    def test_zeros_on_imaginary_axis(self, N, Rp, Rs):
        """All zeros must lie on the imaginary axis."""
        z, _, _ = elliptic.elliptic_filter(N, Rp, Rs)
        for i, zero in enumerate(z):
            assert abs(zero.real) < 1e-9, (
                f"N={N}: zero[{i}] = {zero} is not on imaginary axis"
            )

    @pytest.mark.parametrize("N,Rp,Rs", CASES)
    def test_transfer_function_matches_reference(self, N, Rp, Rs):
        """Full frequency response must match scipy reference."""
        z_ours, p_ours, k_ours = elliptic.elliptic_filter(N, Rp, Rs)
        z_ref, p_ref, k_ref = signal.ellipap(N, Rp, Rs)

        b_ours, a_ours = signal.zpk2tf(z_ours, p_ours, k_ours)
        b_ref, a_ref = signal.zpk2tf(z_ref, p_ref, k_ref)

        w = np.logspace(-2, 2, 500)
        _, h_ours = signal.freqs(b_ours, a_ours, w)
        _, h_ref = signal.freqs(b_ref, a_ref, w)

        mag_ours = 20 * np.log10(np.abs(h_ours) + 1e-30)
        mag_ref = 20 * np.log10(np.abs(h_ref) + 1e-30)
        max_diff = np.max(np.abs(mag_ours - mag_ref))
        assert max_diff < 0.01, (
            f"N={N},Rp={Rp},Rs={Rs}: max magnitude diff = {max_diff:.4f} dB"
        )


# ──────────────────────────────────────────────────────────────
# Section 6: Digital filter discretization
# ──────────────────────────────────────────────────────────────

def _sos_freqresp(sos, worN):
    """Compute frequency response of SOS by multiplying section responses."""
    h = np.ones(len(worN), dtype=complex)
    for i in range(sos.shape[0]):
        _, hi = signal.freqz(sos[i, :3], sos[i, 3:], worN=worN)
        h *= hi
    return h


class TestDiscretizeElliptic:
    """Test digital elliptic filter discretization."""

    def setup_method(self):
        _require_module()

    DIGITAL_CASES = [
        (3, 1.0, 40.0, 44100.0, 1000.0),
        (4, 0.5, 50.0, 48000.0, 5000.0),
        (5, 1.0, 60.0, 48000.0, 8000.0),
        (5, 0.1, 40.0, 96000.0, 10000.0),
        (7, 0.5, 50.0, 44100.0, 2000.0),
        (6, 1.0, 45.0, 48000.0, 6000.0),
    ]

    @pytest.mark.parametrize("N,Rp,Rs,fs,fc", DIGITAL_CASES)
    def test_sos_shape(self, N, Rp, Rs, fs, fc):
        """SOS array must have correct shape."""
        sos = elliptic.discretize_elliptic(N, Rp, Rs, fs, fc)
        n_sections = (N + 1) // 2
        assert sos.shape == (n_sections, 6), (
            f"N={N}: SOS shape {sos.shape}, expected ({n_sections}, 6)"
        )

    @pytest.mark.parametrize("N,Rp,Rs,fs,fc", DIGITAL_CASES)
    def test_sos_real_coefficients(self, N, Rp, Rs, fs, fc):
        """All SOS coefficients must be real."""
        sos = elliptic.discretize_elliptic(N, Rp, Rs, fs, fc)
        assert np.all(np.isreal(sos)), "SOS contains non-real coefficients"
        assert np.all(np.isfinite(sos)), "SOS contains non-finite values"

    @pytest.mark.parametrize("N,Rp,Rs,fs,fc", DIGITAL_CASES)
    def test_digital_stability(self, N, Rp, Rs, fs, fc):
        """All digital poles must be strictly inside the unit circle."""
        sos = elliptic.discretize_elliptic(N, Rp, Rs, fs, fc)
        for i in range(sos.shape[0]):
            a = sos[i, 3:]
            if abs(a[2]) < 1e-15:
                # First-order section
                if abs(a[1]) > 1e-15:
                    assert abs(-a[1]) < 1.0, (
                        f"Section {i}: pole at {-a[1]:.6f} outside unit circle"
                    )
            else:
                roots = np.roots(a)
                for r in roots:
                    assert abs(r) < 1.0 - 1e-10, (
                        f"Section {i}: pole at |z|={abs(r):.8f} outside unit circle"
                    )

    @pytest.mark.parametrize("N,Rp,Rs,fs,fc", DIGITAL_CASES)
    def test_frequency_response_matches_scipy(self, N, Rp, Rs, fs, fc):
        """Overall frequency response must match scipy.signal.ellip."""
        sos_ours = elliptic.discretize_elliptic(N, Rp, Rs, fs, fc)
        sos_ref = signal.ellip(N, Rp, Rs, fc, fs=fs, output='sos')

        # Evaluate at 500 log-spaced frequencies in [0.01, 0.95*pi]
        w = np.logspace(-2, np.log10(0.95 * np.pi), 500)

        h_ours = _sos_freqresp(sos_ours, w)
        h_ref = _sos_freqresp(sos_ref, w)

        mag_ours = 20 * np.log10(np.abs(h_ours) + 1e-30)
        mag_ref = 20 * np.log10(np.abs(h_ref) + 1e-30)
        max_diff = np.max(np.abs(mag_ours - mag_ref))
        assert max_diff < 0.05, (
            f"N={N},Rp={Rp},Rs={Rs},fs={fs},fc={fc}: "
            f"max magnitude diff = {max_diff:.4f} dB"
        )

    @pytest.mark.parametrize("N,Rp,Rs,fs,fc", DIGITAL_CASES)
    def test_passband_edge_response(self, N, Rp, Rs, fs, fc):
        """At the cutoff frequency, magnitude should be near -Rp dB."""
        sos = elliptic.discretize_elliptic(N, Rp, Rs, fs, fc)
        w_cutoff = 2.0 * np.pi * fc / fs
        h = _sos_freqresp(sos, [w_cutoff])
        mag_db = 20 * np.log10(np.abs(h[0]))
        assert abs(mag_db - (-Rp)) < 0.1, (
            f"N={N}: passband edge {mag_db:.3f} dB, expected {-Rp} dB"
        )

    @pytest.mark.parametrize("N,Rp,Rs,fs,fc", DIGITAL_CASES)
    def test_dc_gain(self, N, Rp, Rs, fs, fc):
        """DC gain must match expected value for odd/even order."""
        sos = elliptic.discretize_elliptic(N, Rp, Rs, fs, fc)
        h = _sos_freqresp(sos, [1e-8])
        mag_db = 20 * np.log10(np.abs(h[0]))
        if N % 2 == 1:
            assert abs(mag_db) < 0.01, f"N={N} odd: DC gain = {mag_db:.4f} dB"
        else:
            assert abs(mag_db - (-Rp)) < 0.1, (
                f"N={N} even: DC gain = {mag_db:.4f} dB, expected {-Rp} dB"
            )

    @pytest.mark.parametrize("N,Rp,Rs,fs,fc", DIGITAL_CASES)
    def test_stopband_attenuation(self, N, Rp, Rs, fs, fc):
        """Well into the stopband, attenuation must exceed Rs dB."""
        sos = elliptic.discretize_elliptic(N, Rp, Rs, fs, fc)
        # Evaluate at frequencies from 3*fc to Nyquist (if they exist)
        f_stop = min(3.0 * fc, 0.45 * fs)
        if f_stop <= fc:
            return  # cutoff too close to Nyquist for meaningful test
        w_stop = np.linspace(
            2.0 * np.pi * f_stop / fs,
            0.9 * np.pi,
            50
        )
        h = _sos_freqresp(sos, w_stop)
        mag_db = 20 * np.log10(np.abs(h) + 1e-30)
        assert np.all(mag_db < -Rs + 2.0), (
            f"N={N}: stopband violation, max = {np.max(mag_db):.2f} dB"
        )

    @pytest.mark.parametrize("N,Rp,Rs,fs,fc", DIGITAL_CASES)
    def test_phase_response_continuous(self, N, Rp, Rs, fs, fc):
        """Phase response should be monotonically decreasing (no wrapping artifacts)."""
        sos = elliptic.discretize_elliptic(N, Rp, Rs, fs, fc)
        w = np.linspace(0.001, 0.3 * np.pi, 200)
        h = _sos_freqresp(sos, w)
        phase = np.unwrap(np.angle(h))
        # Phase should generally decrease for a lowpass filter
        diffs = np.diff(phase)
        assert np.sum(diffs > 0.01) < len(diffs) * 0.1, (
            "Phase response is not predominantly decreasing"
        )
