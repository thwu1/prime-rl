
"""
Verification suite for the elliptic filter design and digitization pipeline.
Tests analog prototype accuracy, bilinear transform, SOS decomposition,
and minimum-order evaluation across diverse scenarios.
"""

import json
import os
import sys
import numpy as np
import pytest

sys.path.insert(0, "/app")

from elliptic_filter import (
    landen_sequence,
    complete_elliptic_K,
    elliptic_cd,
    elliptic_cd_inv,
    elliptic_rational_function,
    design_elliptic_lowpass,
)

from scipy.special import ellipk, ellipj
from scipy.signal import ellip, freqs_zpk

try:
    from digitize import bilinear_zpk, zpk_to_sos, min_order_for_spec
    HAS_DIGITIZE = True
except Exception:
    HAS_DIGITIZE = False


# ============================================================
# Analog Pipeline Tests
# ============================================================

class TestLandenSequence:
    def test_descending_convergence(self):
        k = 0.9
        seq = landen_sequence(k, n=10)
        assert len(seq) >= 3
        assert seq[0] == pytest.approx(k, abs=1e-15)
        for i in range(1, len(seq)):
            assert seq[i] < seq[i - 1]
        assert seq[-1] < 1e-10

    def test_landen_recurrence(self):
        k = 0.8
        seq = landen_sequence(k, n=5)
        for i in range(len(seq) - 1):
            ki = seq[i]
            kp = np.sqrt(1 - ki ** 2)
            expected = (ki / (1 + kp)) ** 2
            assert seq[i + 1] == pytest.approx(expected, rel=1e-12)

    def test_extreme_moduli(self):
        seq_small = landen_sequence(0.01, n=5)
        assert seq_small[-1] < 1e-15
        seq_large = landen_sequence(0.9999, n=12)
        assert seq_large[-1] < 1e-8


class TestCompleteEllipticK:
    @pytest.mark.parametrize("k", [0.1, 0.3, 0.5, 0.7, 0.9, 0.99, 0.999])
    def test_against_scipy(self, k):
        computed = complete_elliptic_K(k)
        expected = ellipk(k ** 2)
        assert computed == pytest.approx(expected, rel=1e-10)

    def test_k_zero(self):
        assert complete_elliptic_K(1e-15) == pytest.approx(np.pi / 2, rel=1e-10)

    def test_k_near_one(self):
        K_99 = complete_elliptic_K(0.99)
        K_999 = complete_elliptic_K(0.999)
        assert K_999 > K_99 > 2.0


class TestEllipticCd:
    def test_real_argument_basic(self):
        for k in [0.1, 0.5, 0.9]:
            assert elliptic_cd(0.0, k) == pytest.approx(1.0, abs=1e-12)

    def test_against_scipy_real(self):
        for k in [0.3, 0.7, 0.95]:
            K = ellipk(k ** 2)
            for u_frac in [0.1, 0.25, 0.5, 0.75, 0.9]:
                u = u_frac * K
                sn, cn, dn, _ = ellipj(u, k ** 2)
                expected_cd = cn / dn
                computed = elliptic_cd(u, k)
                assert np.real(computed) == pytest.approx(
                    expected_cd, rel=1e-9, abs=1e-12
                )
                assert abs(np.imag(computed)) < 1e-10

    def test_at_quarter_period(self):
        for k in [0.3, 0.7, 0.99]:
            K = complete_elliptic_K(k)
            val = elliptic_cd(K, k)
            assert abs(val) < 1e-8

    def test_complex_argument(self):
        k = 0.8
        K = complete_elliptic_K(k)
        kp = np.sqrt(1 - k ** 2)
        Kp = complete_elliptic_K(kp)
        for u_re in [0.0, 0.3 * K, 0.7 * K, K]:
            u = complex(u_re, Kp / 2)
            val = elliptic_cd(u, k)
            assert abs(val) == pytest.approx(1.0 / np.sqrt(k), rel=1e-6)

    def test_evenness(self):
        k = 0.7
        for u in [0.5, 1.0, 1.5, complex(0.3, 0.2)]:
            assert elliptic_cd(-u, k) == pytest.approx(
                elliptic_cd(u, k), rel=1e-10, abs=1e-12
            )


class TestEllipticCdInv:
    def test_roundtrip_real(self):
        k = 0.8
        for w in [-0.9, -0.5, 0.0, 0.5, 0.9]:
            u = elliptic_cd_inv(w, k)
            reconstructed = elliptic_cd(u, k)
            assert np.real(reconstructed) == pytest.approx(
                w, rel=1e-8, abs=1e-10
            )

    def test_roundtrip_transition_band(self):
        k = 0.8
        for w in [1.01, 1.1, 1.0 / k - 0.01]:
            u = elliptic_cd_inv(w, k)
            reconstructed = elliptic_cd(u, k)
            assert reconstructed == pytest.approx(w, rel=1e-7, abs=1e-9)

    def test_roundtrip_complex(self):
        k = 0.7
        for theta in [0.3, 1.0, 2.0, 2.8]:
            w = np.exp(1j * theta)
            u = elliptic_cd_inv(w, k)
            reconstructed = elliptic_cd(u, k)
            assert reconstructed == pytest.approx(w, rel=1e-7, abs=1e-9)


class TestEllipticRationalFunction:
    def test_R_at_one(self):
        for N in [3, 4, 5, 7]:
            for k in [0.9, 0.99]:
                val = elliptic_rational_function(1.0, N, k)
                assert np.real(val) == pytest.approx(1.0, abs=1e-8)

    def test_R_at_minus_one(self):
        for N in [3, 4, 5]:
            for k in [0.9, 0.99]:
                val = elliptic_rational_function(-1.0, N, k)
                assert np.real(val) == pytest.approx((-1) ** N, abs=1e-8)

    def test_passband_equiripple(self):
        N = 5
        k = 0.98
        xs = np.linspace(-0.99, 0.99, 50)
        for x in xs:
            val = elliptic_rational_function(x, N, k)
            assert abs(val) <= 1.0 + 1e-6


class TestEllipticFilterDesign:
    def _get_scipy_reference(self, N, rp, rs):
        z, p, k = ellip(N, rp, rs, 1.0, btype="low", analog=True, output="zpk")
        return np.sort_complex(z), np.sort_complex(p), k

    def test_5th_order(self):
        N, rp, rs = 5, 1.0, 60.0
        z_ref, p_ref, k_ref = self._get_scipy_reference(N, rp, rs)
        omega_s = np.min(np.abs(z_ref))
        z, p, k = design_elliptic_lowpass(N, rp, rs, omega_s)
        z = np.sort_complex(z)
        p = np.sort_complex(p)
        for i in range(len(p)):
            assert p[i] == pytest.approx(p_ref[i], rel=1e-6, abs=1e-8)
        for i in range(len(z)):
            assert z[i] == pytest.approx(z_ref[i], rel=1e-6, abs=1e-8)

    def test_4th_order(self):
        N, rp, rs = 4, 0.5, 40.0
        z_ref, p_ref, k_ref = self._get_scipy_reference(N, rp, rs)
        omega_s = np.min(np.abs(z_ref))
        z, p, k = design_elliptic_lowpass(N, rp, rs, omega_s)
        z = np.sort_complex(z)
        p = np.sort_complex(p)
        for i in range(len(p)):
            assert p[i] == pytest.approx(p_ref[i], rel=1e-6, abs=1e-8)
        for i in range(len(z)):
            assert z[i] == pytest.approx(z_ref[i], rel=1e-6, abs=1e-8)

    def test_frequency_response_vs_scipy(self):
        N, rp, rs = 5, 1.0, 60.0
        z_ref, p_ref, k_ref = self._get_scipy_reference(N, rp, rs)
        omega_s = np.min(np.abs(z_ref))
        z, p, k = design_elliptic_lowpass(N, rp, rs, omega_s)
        freqs = np.logspace(-1, 1, 100)
        _, h_ref = freqs_zpk(z_ref, p_ref, k_ref, freqs)
        _, h_our = freqs_zpk(z, p, k, freqs)
        mag_ref = np.abs(h_ref)
        mag_our = np.abs(h_our)
        rel_err = np.abs(mag_our - mag_ref) / (mag_ref + 1e-15)
        assert np.max(rel_err) < 1e-4

    def test_7th_order(self):
        N, rp, rs = 7, 0.1, 80.0
        z_ref, p_ref, k_ref = self._get_scipy_reference(N, rp, rs)
        omega_s = np.min(np.abs(z_ref))
        z, p, k = design_elliptic_lowpass(N, rp, rs, omega_s)
        z = np.sort_complex(z)
        p = np.sort_complex(p)
        for i in range(len(p)):
            assert p[i] == pytest.approx(p_ref[i], rel=1e-5, abs=1e-7)
        for i in range(len(z)):
            assert z[i] == pytest.approx(z_ref[i], rel=1e-5, abs=1e-7)

    def test_3rd_order(self):
        N, rp, rs = 3, 2.0, 30.0
        z_ref, p_ref, k_ref = self._get_scipy_reference(N, rp, rs)
        omega_s = np.min(np.abs(z_ref))
        z, p, k = design_elliptic_lowpass(N, rp, rs, omega_s)
        z = np.sort_complex(z)
        p = np.sort_complex(p)
        for i in range(len(p)):
            assert p[i] == pytest.approx(p_ref[i], rel=1e-6, abs=1e-8)

    def test_pole_stability(self):
        for N, rp, rs in [(3, 1.0, 40.0), (5, 0.5, 60.0), (7, 0.1, 80.0)]:
            z_ref, p_ref, k_ref = self._get_scipy_reference(N, rp, rs)
            omega_s = np.min(np.abs(z_ref))
            z, p, k = design_elliptic_lowpass(N, rp, rs, omega_s)
            for pole in p:
                assert np.real(pole) < 0, f"Unstable pole: {pole}"

    def test_zero_locations(self):
        N, rp, rs = 5, 1.0, 60.0
        z_ref, p_ref, k_ref = self._get_scipy_reference(N, rp, rs)
        omega_s = np.min(np.abs(z_ref))
        z, p, k = design_elliptic_lowpass(N, rp, rs, omega_s)
        for zero in z:
            assert abs(np.real(zero)) < 1e-8, f"Zero not on imaginary axis: {zero}"

    def test_conjugate_symmetry(self):
        N, rp, rs = 5, 1.0, 60.0
        z_ref, p_ref, k_ref = self._get_scipy_reference(N, rp, rs)
        omega_s = np.min(np.abs(z_ref))
        z, p, k = design_elliptic_lowpass(N, rp, rs, omega_s)
        for pole in p:
            if abs(np.imag(pole)) > 1e-10:
                conj = np.conj(pole)
                dists = np.abs(p - conj)
                assert np.min(dists) < 1e-8, f"Missing conjugate for pole {pole}"


# ============================================================
# Digital Pipeline Tests
# ============================================================

@pytest.mark.skipif(not HAS_DIGITIZE, reason="digitize module not implemented")
class TestBilinearTransform:
    def _scipy_bilinear(self, z, p, k, fs):
        from scipy.signal import bilinear_zpk as _bz
        return _bz(z, p, k, fs)

    def test_2nd_order_butterworth(self):
        from scipy.signal import butter
        z_a, p_a, k_a = butter(2, 1.0, btype="low", analog=True, output="zpk")
        z_ref, p_ref, k_ref = self._scipy_bilinear(z_a, p_a, k_a, 8000)
        z_d, p_d, k_d = bilinear_zpk(z_a, p_a, k_a, 8000)
        z_d = np.sort_complex(z_d)
        z_ref = np.sort_complex(z_ref)
        p_d = np.sort_complex(p_d)
        p_ref = np.sort_complex(p_ref)
        for i in range(len(z_ref)):
            assert z_d[i] == pytest.approx(z_ref[i], rel=1e-10, abs=1e-12)
        for i in range(len(p_ref)):
            assert p_d[i] == pytest.approx(p_ref[i], rel=1e-10, abs=1e-12)
        assert k_d == pytest.approx(k_ref, rel=1e-10)

    def test_elliptic_5th_order(self):
        z_a, p_a, k_a = ellip(5, 1.0, 60.0, 1.0, btype="low", analog=True, output="zpk")
        z_ref, p_ref, k_ref = self._scipy_bilinear(z_a, p_a, k_a, 48000)
        z_d, p_d, k_d = bilinear_zpk(z_a, p_a, k_a, 48000)
        z_d = np.sort_complex(z_d)
        z_ref = np.sort_complex(z_ref)
        p_d = np.sort_complex(p_d)
        p_ref = np.sort_complex(p_ref)
        for i in range(len(z_ref)):
            assert z_d[i] == pytest.approx(z_ref[i], rel=1e-8, abs=1e-10)
        for i in range(len(p_ref)):
            assert p_d[i] == pytest.approx(p_ref[i], rel=1e-8, abs=1e-10)
        assert k_d == pytest.approx(k_ref, rel=1e-8)

    def test_degree_matching_zeros(self):
        z_a, p_a, k_a = ellip(5, 1.0, 60.0, 1.0, btype="low", analog=True, output="zpk")
        z_d, p_d, k_d = bilinear_zpk(z_a, p_a, k_a, 48000)
        assert len(z_d) == len(p_d), "Must have equal zeros and poles"
        n_neg1 = sum(1 for zi in z_d if abs(zi + 1) < 1e-10)
        assert n_neg1 >= 1, "Must have at least one zero at z=-1 for degree matching"

    def test_digital_pole_stability(self):
        z_a, p_a, k_a = ellip(7, 0.1, 80.0, 1.0, btype="low", analog=True, output="zpk")
        z_d, p_d, k_d = bilinear_zpk(z_a, p_a, k_a, 44100)
        for pole in p_d:
            assert abs(pole) < 1.0, f"Digital pole outside unit circle: |p|={abs(pole)}"

    def test_4th_order_even(self):
        z_a, p_a, k_a = ellip(4, 0.5, 40.0, 1.0, btype="low", analog=True, output="zpk")
        z_ref, p_ref, k_ref = self._scipy_bilinear(z_a, p_a, k_a, 16000)
        z_d, p_d, k_d = bilinear_zpk(z_a, p_a, k_a, 16000)
        assert len(z_d) == len(p_d)
        assert k_d == pytest.approx(k_ref, rel=1e-8)


@pytest.mark.skipif(not HAS_DIGITIZE, reason="digitize module not implemented")
class TestSOSDecomposition:
    def _get_digital_zpk(self, N, rp, rs, fs):
        from scipy.signal import bilinear_zpk as _bz
        z_a, p_a, k_a = ellip(N, rp, rs, 1.0, btype="low", analog=True, output="zpk")
        return _bz(z_a, p_a, k_a, fs)

    def test_frequency_response_match(self):
        z_d, p_d, k_d = self._get_digital_zpk(5, 1.0, 60.0, 48000)
        sos = zpk_to_sos(z_d, p_d, k_d)

        w = np.linspace(0.01, np.pi, 500)
        ejw = np.exp(1j * w)

        h_zpk = np.ones(len(w), dtype=complex) * k_d
        for zi in z_d:
            h_zpk *= (ejw - zi)
        for pi in p_d:
            h_zpk /= (ejw - pi)

        h_sos = np.ones(len(w), dtype=complex)
        for section in sos:
            b0, b1, b2, a0, a1, a2 = section
            num = b0 + b1 * ejw ** (-1) + b2 * ejw ** (-2)
            den = a0 + a1 * ejw ** (-1) + a2 * ejw ** (-2)
            h_sos *= num / den

        rel_err = np.abs(np.abs(h_zpk) - np.abs(h_sos)) / (np.abs(h_zpk) + 1e-20)
        assert np.max(rel_err) < 1e-5, f"Max relative error: {np.max(rel_err)}"

    def test_section_count(self):
        for N in [3, 4, 5, 6, 7]:
            z_d, p_d, k_d = self._get_digital_zpk(N, 1.0, 60.0, 48000)
            sos = zpk_to_sos(z_d, p_d, k_d)
            expected = (N + 1) // 2
            assert sos.shape[0] == expected, f"Order {N}: expected {expected} sections, got {sos.shape[0]}"
            assert sos.shape[1] == 6

    def test_a0_normalized(self):
        z_d, p_d, k_d = self._get_digital_zpk(5, 1.0, 60.0, 48000)
        sos = zpk_to_sos(z_d, p_d, k_d)
        for i, section in enumerate(sos):
            assert section[3] == pytest.approx(1.0, abs=1e-12), \
                f"Section {i}: a0 = {section[3]}, expected 1.0"

    def test_section_ordering_by_pole_radius(self):
        z_d, p_d, k_d = self._get_digital_zpk(7, 0.5, 60.0, 48000)
        sos = zpk_to_sos(z_d, p_d, k_d)
        radii = []
        for section in sos:
            a1, a2 = section[4], section[5]
            if abs(a2) < 1e-15:
                radii.append(abs(a1))
            else:
                radii.append(np.sqrt(abs(a2)))
        for i in range(len(radii) - 1):
            assert radii[i] <= radii[i + 1] + 1e-8, \
                f"Sections not ordered by pole radius: {radii}"

    def test_odd_order_handling(self):
        z_d, p_d, k_d = self._get_digital_zpk(3, 1.0, 40.0, 48000)
        sos = zpk_to_sos(z_d, p_d, k_d)
        assert sos.shape[0] == 2
        has_first_order = False
        for section in sos:
            if abs(section[5]) < 1e-12:
                has_first_order = True
        assert has_first_order, "Odd-order filter must have a first-order section (a2=0)"


@pytest.mark.skipif(not HAS_DIGITIZE, reason="digitize module not implemented")
class TestMinOrderEvaluation:
    def _load_results(self):
        with open("/app/results.json") as f:
            return json.load(f)

    def _load_scenarios(self):
        with open("/app/scenarios.json") as f:
            return json.load(f)

    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found at /app/results.json"

    def test_all_scenarios_present(self):
        results = self._load_results()
        scenarios = self._load_scenarios()
        for name in scenarios:
            assert name in results, f"Missing scenario in results: {name}"
            r = results[name]
            assert "min_order" in r, f"{name}: missing min_order"
            assert "ripple_db" in r, f"{name}: missing ripple_db"
            assert "atten_db" in r, f"{name}: missing atten_db"

    def test_min_order_in_range(self):
        results = self._load_results()
        for name, r in results.items():
            assert 2 <= r["min_order"] <= 15, \
                f"{name}: min_order={r['min_order']} out of range [2,15]"

    def test_achieved_values_reasonable(self):
        results = self._load_results()
        scenarios = self._load_scenarios()
        for name, r in results.items():
            rp = scenarios[name]["ripple_db"]
            rs = scenarios[name]["atten_db"]
            assert 0 < r["ripple_db"] <= rp + 0.5, \
                f"{name}: achieved ripple {r['ripple_db']:.4f} unreasonable (spec={rp})"
            assert r["atten_db"] >= rs - 1.0, \
                f"{name}: achieved atten {r['atten_db']:.4f} too low (spec={rs})"

    def test_min_order_meets_specs_via_scipy(self):
        from scipy.signal import bilinear_zpk as _bz, freqz_zpk

        results = self._load_results()
        scenarios = self._load_scenarios()

        for name, spec in scenarios.items():
            N = results[name]["min_order"]
            fp = spec["passband_hz"]
            fstop = spec["stopband_hz"]
            rp = spec["ripple_db"]
            rs = spec["atten_db"]
            fs = spec["sample_rate_hz"]

            wp = 2 * fs * np.tan(np.pi * fp / fs)

            z_a, p_a, k_a = ellip(N, rp, rs, wp, btype="low", analog=True, output="zpk")
            z_d, p_d, k_d = _bz(z_a, p_a, k_a, fs)

            f_pb = np.linspace(0.01 * fp, fp, 300)
            w_pb = 2 * np.pi * f_pb / fs
            _, h_pb = freqz_zpk(z_d, p_d, k_d, worN=w_pb)
            pb_dev = -20 * np.log10(np.abs(h_pb).min())

            f_sb = np.linspace(fstop, fs / 2 * 0.98, 300)
            w_sb = 2 * np.pi * f_sb / fs
            _, h_sb = freqz_zpk(z_d, p_d, k_d, worN=w_sb)
            sb_atten = -20 * np.log10(np.abs(h_sb).max() + 1e-30)

            assert pb_dev <= rp + 0.5, \
                f"{name}: passband ripple {pb_dev:.3f} dB exceeds spec {rp} + 0.5"
            assert sb_atten >= rs - 1.0, \
                f"{name}: stopband atten {sb_atten:.3f} dB below spec {rs} - 1.0"

    def test_min_order_vs_scipy_ellipord(self):
        from scipy.signal import ellipord

        results = self._load_results()
        scenarios = self._load_scenarios()

        for name, spec in scenarios.items():
            fp = spec["passband_hz"]
            fstop = spec["stopband_hz"]
            rp = spec["ripple_db"]
            rs = spec["atten_db"]
            fs = spec["sample_rate_hz"]

            N_scipy, _ = ellipord(fp, fstop, rp, rs, fs=fs)
            N_ours = results[name]["min_order"]

            assert abs(N_ours - N_scipy) <= 1, \
                f"{name}: our order {N_ours} vs scipy {N_scipy} (diff > 1)"


@pytest.mark.skipif(not HAS_DIGITIZE, reason="digitize module not implemented")
class TestNoScipyInDigitize:
    def test_no_scipy_import(self):
        import ast
        with open("/app/digitize.py") as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "scipy" not in alias.name, \
                        f"digitize.py must not import scipy (found: import {alias.name})"
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "scipy" not in node.module, \
                        f"digitize.py must not import from scipy (found: from {node.module})"
