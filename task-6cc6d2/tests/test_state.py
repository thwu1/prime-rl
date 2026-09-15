"""
Tests for elliptic (Cauer) filter design module.

"""

import os
import sys
import numpy as np
import pytest

sys.path.insert(0, "/app")


# -- helpers ------------------------------------------------------------------

def _ref_K(k):
    """Reference K(k) via scipy."""
    from scipy.special import ellipk
    return ellipk(k ** 2)


def _ref_ellipj(u, k):
    """Reference sn, cn, dn, cd via scipy."""
    from scipy.special import ellipj
    sn, cn, dn, _ph = ellipj(u, k ** 2)
    cd = cn / dn
    return sn, cn, dn, cd


def _ref_filter(N, rp, rs):
    """Reference elliptic filter via scipy."""
    from scipy.signal import ellip
    z, p, k = ellip(N, rp, rs, 1, analog=True, output='zpk')
    return z, p, k


def _zpk_freqresp(z, p, k, w):
    """Evaluate |H(jw)| from zpk."""
    s = 1j * w
    num = k
    for zi in z:
        num = num * (s - zi)
    den = 1.0
    for pi in p:
        den = den * (s - pi)
    return np.abs(num / den)


# -- 1. Complete elliptic integral K(k) --------------------------------------

class TestCompleteEllipticK:

    def _get_fn(self):
        from elliptic_filter import complete_elliptic_K
        return complete_elliptic_K

    @pytest.mark.parametrize("k", [0.01, 0.1, 0.3, 0.5, 0.7, 0.9, 0.95, 0.99, 0.999])
    def test_K_values(self, k):
        fn = self._get_fn()
        ref = _ref_K(k)
        val = fn(k)
        assert abs(val - ref) / ref < 1e-10, (
            f"K({k}): got {val}, expected {ref}, relerr={abs(val-ref)/ref:.2e}"
        )

    def test_K_small(self):
        fn = self._get_fn()
        val = fn(1e-6)
        assert abs(val - np.pi / 2) < 1e-8

    def test_K_large(self):
        fn = self._get_fn()
        v1 = fn(0.99)
        v2 = fn(0.999)
        v3 = fn(0.9999)
        assert v1 < v2 < v3

    def test_K_complementary_symmetry(self):
        fn = self._get_fn()
        k = 0.6
        kp = np.sqrt(1 - k ** 2)
        Kk = fn(k)
        Kkp = fn(kp)
        ref_K = _ref_K(k)
        ref_Kp = _ref_K(kp)
        assert abs(Kk - ref_K) / ref_K < 1e-10
        assert abs(Kkp - ref_Kp) / ref_Kp < 1e-10


# -- 2. Jacobian elliptic cosine cd(u, k) ------------------------------------

class TestCdJacobi:

    def _get_fn(self):
        from elliptic_filter import cd_jacobi
        return cd_jacobi

    def test_cd_at_zero(self):
        fn = self._get_fn()
        for k in [0.3, 0.5, 0.8, 0.99]:
            val = fn(0.0, k)
            assert abs(val - 1.0) < 1e-12, f"cd(0, {k}) should be 1, got {val}"

    def test_cd_at_K(self):
        fn = self._get_fn()
        from elliptic_filter import complete_elliptic_K
        for k in [0.3, 0.5, 0.8, 0.99]:
            K = complete_elliptic_K(k)
            val = fn(K, k)
            assert abs(val) < 1e-10, f"cd(K, {k}) should be 0, got {val}"

    @pytest.mark.parametrize("u,k", [
        (0.5, 0.5), (1.0, 0.5), (0.3, 0.9), (1.5, 0.99), (2.0, 0.8),
    ])
    def test_cd_real_values(self, u, k):
        fn = self._get_fn()
        _, _, _, cd_ref = _ref_ellipj(u, k)
        val = fn(u, k)
        assert abs(val - cd_ref) < 1e-10, (
            f"cd({u}, {k}): got {val}, expected {cd_ref}"
        )

    def test_cd_even_symmetry(self):
        fn = self._get_fn()
        k = 0.7
        for u in [0.3, 0.8, 1.5]:
            assert abs(fn(-u, k) - fn(u, k)) < 1e-12

    def test_cd_periodicity(self):
        fn = self._get_fn()
        from elliptic_filter import complete_elliptic_K
        k = 0.7
        K = complete_elliptic_K(k)
        for u in [0.2, 0.9, 1.4]:
            v1 = fn(u, k)
            v2 = fn(u + 4 * K, k)
            assert abs(v1 - v2) < 1e-9, f"cd periodicity failed at u={u}"


# -- 3. Jacobian elliptic sine sn(u, k) --------------------------------------

class TestSnJacobi:

    def _get_fn(self):
        from elliptic_filter import sn_jacobi
        return sn_jacobi

    def test_sn_at_zero(self):
        fn = self._get_fn()
        for k in [0.3, 0.5, 0.8, 0.99]:
            val = fn(0.0, k)
            assert abs(val) < 1e-12, f"sn(0, {k}) should be 0, got {val}"

    def test_sn_at_K(self):
        fn = self._get_fn()
        from elliptic_filter import complete_elliptic_K
        for k in [0.3, 0.5, 0.8, 0.99]:
            K = complete_elliptic_K(k)
            val = fn(K, k)
            assert abs(val - 1.0) < 1e-10, f"sn(K, {k}) should be 1, got {val}"

    @pytest.mark.parametrize("u,k", [
        (0.5, 0.5), (1.0, 0.5), (0.3, 0.9), (1.5, 0.99), (2.0, 0.8),
    ])
    def test_sn_real_values(self, u, k):
        fn = self._get_fn()
        sn_ref, _, _, _ = _ref_ellipj(u, k)
        val = fn(u, k)
        assert abs(val - sn_ref) < 1e-10, (
            f"sn({u}, {k}): got {val}, expected {sn_ref}"
        )

    def test_sn_odd_symmetry(self):
        fn = self._get_fn()
        k = 0.7
        for u in [0.3, 0.8, 1.5]:
            assert abs(fn(-u, k) + fn(u, k)) < 1e-12

    def test_sn_cd_consistency(self):
        from elliptic_filter import sn_jacobi, cd_jacobi, complete_elliptic_K
        k = 0.6
        K = complete_elliptic_K(k)
        for u in [0.3, 0.7, 1.2, K]:
            sn_val = sn_jacobi(u, k)
            cd_val = cd_jacobi(u - K, k)
            assert abs(sn_val - cd_val) < 1e-9, (
                f"sn({u})={sn_val} != cd({u}-K)={cd_val}"
            )


# -- 4. Inverse Jacobian elliptic functions -----------------------------------

class TestCdInverse:

    def _get_fns(self):
        from elliptic_filter import cd_jacobi, cd_inverse, complete_elliptic_K
        return cd_jacobi, cd_inverse, complete_elliptic_K

    @pytest.mark.parametrize("k", [0.3, 0.5, 0.8, 0.95, 0.99])
    def test_cd_inverse_roundtrip_real(self, k):
        cd, cdinv, K_fn = self._get_fns()
        K = K_fn(k)
        for u in [0.1 * K, 0.3 * K, 0.5 * K, 0.7 * K, 0.9 * K]:
            y = cd(u, k)
            u_rec = cdinv(y, k)
            assert abs(float(np.real(u_rec)) - u) < 1e-8, (
                f"cd_inverse roundtrip failed: k={k}, u={u}, y={y}, u_rec={u_rec}"
            )

    def test_cd_inverse_at_one(self):
        _, cdinv, _ = self._get_fns()
        for k in [0.3, 0.7, 0.99]:
            val = cdinv(1.0, k)
            assert abs(val) < 1e-6, f"cd_inverse(1, {k}) = {val}, expected ~0"

    def test_cd_inverse_at_zero(self):
        _, cdinv, K_fn = self._get_fns()
        for k in [0.3, 0.7, 0.99]:
            K = K_fn(k)
            val = cdinv(0.0, k)
            assert abs(float(np.real(val)) - K) < 1e-8


class TestSnInverse:

    def _get_fns(self):
        from elliptic_filter import sn_jacobi, sn_inverse, complete_elliptic_K
        return sn_jacobi, sn_inverse, complete_elliptic_K

    @pytest.mark.parametrize("k", [0.3, 0.5, 0.8, 0.95, 0.99])
    def test_sn_inverse_roundtrip_real(self, k):
        sn, sninv, K_fn = self._get_fns()
        K = K_fn(k)
        for u in [0.1 * K, 0.3 * K, 0.5 * K, 0.7 * K, 0.9 * K]:
            y = sn(u, k)
            u_rec = sninv(y, k)
            assert abs(float(np.real(u_rec)) - u) < 1e-8, (
                f"sn_inverse roundtrip failed: k={k}, u={u}, y={y}, u_rec={u_rec}"
            )

    def test_sn_inverse_at_zero(self):
        _, sninv, _ = self._get_fns()
        for k in [0.3, 0.7, 0.99]:
            val = sninv(0.0, k)
            assert abs(val) < 1e-10

    def test_sn_inverse_at_one(self):
        _, sninv, K_fn = self._get_fns()
        for k in [0.3, 0.7, 0.99]:
            K = K_fn(k)
            val = sninv(1.0, k)
            assert abs(float(np.real(val)) - K) < 1e-8


# -- 5. Elliptic filter design -----------------------------------------------

class TestEllipticFilterDesign:

    def _get_fn(self):
        from elliptic_filter import elliptic_filter_design
        return elliptic_filter_design

    def _compare_zpk(self, N, rp, rs, tol_z=1e-4, tol_p=1e-4, tol_gain=1e-3):
        fn = self._get_fn()
        z, p, k = fn(N, rp, rs)
        z_ref, p_ref, k_ref = _ref_filter(N, rp, rs)

        z = np.array(z, dtype=complex)
        p = np.array(p, dtype=complex)
        z_ref = np.array(z_ref, dtype=complex)
        p_ref = np.array(p_ref, dtype=complex)

        z = z[np.argsort(np.imag(z))]
        p = p[np.argsort(np.imag(p))]
        z_ref = z_ref[np.argsort(np.imag(z_ref))]
        p_ref = p_ref[np.argsort(np.imag(p_ref))]

        assert len(z) == len(z_ref), (
            f"N={N}: wrong number of zeros: {len(z)} vs {len(z_ref)}"
        )
        assert len(p) == len(p_ref), (
            f"N={N}: wrong number of poles: {len(p)} vs {len(p_ref)}"
        )

        for i in range(len(z)):
            err = abs(z[i] - z_ref[i])
            assert err < tol_z, (
                f"N={N}: zero[{i}] mismatch: {z[i]} vs {z_ref[i]}, err={err:.2e}"
            )

        for i in range(len(p)):
            err = abs(p[i] - p_ref[i])
            assert err < tol_p, (
                f"N={N}: pole[{i}] mismatch: {p[i]} vs {p_ref[i]}, err={err:.2e}"
            )

        gain_err = abs(k - k_ref) / max(abs(k_ref), 1e-15)
        assert gain_err < tol_gain, (
            f"N={N}: gain mismatch: {k} vs {k_ref}, relerr={gain_err:.2e}"
        )

    def test_filter_order5(self):
        self._compare_zpk(5, 1.0, 40.0)

    def test_filter_order4(self):
        self._compare_zpk(4, 0.5, 60.0)

    def test_filter_order3(self):
        self._compare_zpk(3, 3.0, 30.0)

    def test_filter_order7(self):
        self._compare_zpk(7, 0.1, 80.0)

    def test_poles_left_half_plane(self):
        fn = self._get_fn()
        for N, rp, rs in [(3, 1, 30), (5, 1, 40), (4, 0.5, 60), (7, 0.1, 80)]:
            _, p, _ = fn(N, rp, rs)
            for pi in p:
                assert np.real(pi) < 0, (
                    f"N={N}: pole {pi} is not in the left half-plane"
                )

    def test_zeros_imaginary_axis(self):
        fn = self._get_fn()
        for N, rp, rs in [(3, 1, 30), (5, 1, 40), (4, 0.5, 60)]:
            z, _, _ = fn(N, rp, rs)
            for zi in z:
                assert abs(np.real(zi)) < 1e-8, (
                    f"N={N}: zero {zi} should be purely imaginary"
                )

    def test_poles_conjugate_symmetry(self):
        fn = self._get_fn()
        for N, rp, rs in [(4, 0.5, 60), (5, 1, 40)]:
            _, p, _ = fn(N, rp, rs)
            p = np.array(p, dtype=complex)
            for pi in p:
                if abs(np.imag(pi)) > 1e-10:
                    conj = np.conj(pi)
                    dists = np.abs(p - conj)
                    assert np.min(dists) < 1e-8, (
                        f"Pole {pi} has no conjugate partner"
                    )

    def test_correct_number_of_zeros_and_poles(self):
        fn = self._get_fn()
        for N, rp, rs, expected_nz in [(3, 1, 30, 2), (5, 1, 40, 4),
                                        (4, 0.5, 60, 4), (7, 0.1, 80, 6)]:
            z, p, _ = fn(N, rp, rs)
            assert len(p) == N, f"N={N}: expected {N} poles, got {len(p)}"
            assert len(z) == expected_nz, (
                f"N={N}: expected {expected_nz} zeros, got {len(z)}"
            )

    def test_frequency_response_passband(self):
        fn = self._get_fn()
        rp = 1.0
        rs = 40.0
        z, p, k = fn(5, rp, rs)
        lower_bound = 10 ** (-rp / 20)
        omegas = np.linspace(0, 1.0, 200)
        for w in omegas:
            H = _zpk_freqresp(z, p, k, w)
            assert H <= 1.0 + 1e-6, f"|H(j{w})| = {H} > 1"
            assert H >= lower_bound - 1e-4, (
                f"|H(j{w})| = {H} < {lower_bound}"
            )

    def test_frequency_response_stopband(self):
        fn = self._get_fn()
        rp = 1.0
        rs = 40.0
        z, p, k = fn(5, rp, rs)
        z_ref, p_ref, _ = _ref_filter(5, rp, rs)
        z_ref_mags = np.abs(np.imag(z_ref))
        ws = np.min(z_ref_mags)
        upper_bound = 10 ** (-rs / 20)
        omegas = np.linspace(ws, 5.0, 200)
        for w in omegas:
            H = _zpk_freqresp(z, p, k, w)
            assert H <= upper_bound + 1e-4, (
                f"|H(j{w})| = {H} > {upper_bound} in stopband"
            )

    def test_dc_gain_odd(self):
        fn = self._get_fn()
        for N, rp, rs in [(3, 3, 30), (5, 1, 40), (7, 0.1, 80)]:
            z, p, k = fn(N, rp, rs)
            H0 = _zpk_freqresp(z, p, k, 0.0)
            assert abs(H0 - 1.0) < 1e-4, (
                f"N={N}: DC gain = {H0}, expected 1.0"
            )

    def test_dc_gain_even(self):
        fn = self._get_fn()
        rp = 0.5
        rs = 60.0
        z, p, k = fn(4, rp, rs)
        expected = 10 ** (-rp / 20)
        H0 = _zpk_freqresp(z, p, k, 0.0)
        assert abs(H0 - expected) < 1e-4, (
            f"N=4: DC gain = {H0}, expected {expected}"
        )


# -- 6. Bode plot SVG generation ---------------------------------------------

class TestBodePlots:
    """Verify that Bode magnitude plot SVGs were generated for all configs."""

    def test_bode_svgs_exist(self):
        """Each reference config must have a corresponding SVG in /app/output/."""
        import glob as globmod
        ref_files = sorted(globmod.glob("/app/reference_data/*.json"))
        assert len(ref_files) >= 4, (
            f"Expected >= 4 reference files, found {len(ref_files)}"
        )
        for ref_file in ref_files:
            basename = os.path.splitext(os.path.basename(ref_file))[0]
            svg_path = f"/app/output/{basename}.svg"
            assert os.path.exists(svg_path), (
                f"Missing Bode plot: {svg_path} -- "
                f"generate with: python3 tools/filterspec.py pipeline "
                f"--configs reference_data/ --output output/"
            )

    def test_bode_svgs_valid_content(self):
        """SVG files must contain valid gnuplot-generated markup."""
        import glob as globmod
        svg_files = sorted(globmod.glob("/app/output/*.svg"))
        assert len(svg_files) >= 4, (
            f"Expected >= 4 SVG Bode plots in /app/output/, found {len(svg_files)}"
        )
        for svg_file in svg_files:
            with open(svg_file) as f:
                content = f.read()
            assert "<svg" in content.lower(), (
                f"{svg_file} does not contain valid SVG markup"
            )
            assert len(content) > 1000, (
                f"{svg_file} is too small ({len(content)} bytes), "
                f"expected > 1000 bytes of gnuplot SVG output"
            )


# -- 7. No forbidden imports -------------------------------------------------

class TestNoForbiddenImports:

    def test_no_scipy(self):
        source_path = "/app/elliptic_filter.py"
        with open(source_path, "r") as f:
            source = f.read()
        forbidden = ["scipy", "mpmath"]
        for lib in forbidden:
            lines = source.split("\n")
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if f"import {lib}" in stripped or f"from {lib}" in stripped:
                    pytest.fail(
                        f"Forbidden import found: '{stripped}' -- "
                        f"implementation must not use {lib}"
                    )
