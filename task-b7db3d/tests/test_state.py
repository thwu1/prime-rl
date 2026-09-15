"""Tests for the PBR multi-backend BRDF pipeline."""

import ctypes
import json
import math
import os
import sys
import pytest

sys.path.insert(0, '/app')


# ──────────────────────────────────────────────────────────────────────
# Build system tests
# ──────────────────────────────────────────────────────────────────────

class TestBuildSystem:
    """Verify the C shared library builds correctly."""

    def test_libbrdf_exists(self):
        assert os.path.isfile('/app/libbrdf.so'), "libbrdf.so not found"

    def test_libbrdf_loads(self):
        lib = ctypes.CDLL('/app/libbrdf.so')
        assert lib is not None

    def test_libbrdf_has_brdf_symbols(self):
        lib = ctypes.CDLL('/app/libbrdf.so')
        for name in ['brdf_D_GGX', 'brdf_V_SmithGGX', 'brdf_F_Schlick_scalar',
                      'brdf_D_Charlie', 'brdf_V_Neubelt']:
            assert hasattr(lib, name), f"Symbol {name} not found in libbrdf.so"

    def test_libbrdf_has_sampling_symbols(self):
        lib = ctypes.CDLL('/app/libbrdf.so')
        for name in ['sample_GGX', 'sample_hemisphere_cosine',
                      'sample_hemisphere_uniform', 'sample_Charlie',
                      'hammersley_radical_inverse']:
            assert hasattr(lib, name), f"Symbol {name} not found in libbrdf.so"


# ──────────────────────────────────────────────────────────────────────
# C BRDF function tests (direct ctypes calls)
# ──────────────────────────────────────────────────────────────────────

class TestCBRDF:
    """Verify C BRDF functions produce correct values."""

    @pytest.fixture(autouse=True)
    def setup_lib(self):
        self.lib = ctypes.CDLL('/app/libbrdf.so')
        self.lib.brdf_D_GGX.argtypes = [ctypes.c_double, ctypes.c_double]
        self.lib.brdf_D_GGX.restype = ctypes.c_double
        self.lib.brdf_V_SmithGGX.argtypes = [ctypes.c_double, ctypes.c_double,
                                              ctypes.c_double]
        self.lib.brdf_V_SmithGGX.restype = ctypes.c_double
        self.lib.brdf_F_Schlick_scalar.argtypes = [ctypes.c_double, ctypes.c_double]
        self.lib.brdf_F_Schlick_scalar.restype = ctypes.c_double
        self.lib.brdf_D_Charlie.argtypes = [ctypes.c_double, ctypes.c_double]
        self.lib.brdf_D_Charlie.restype = ctypes.c_double
        self.lib.brdf_V_Neubelt.argtypes = [ctypes.c_double, ctypes.c_double]
        self.lib.brdf_V_Neubelt.restype = ctypes.c_double

    def test_D_GGX_peak(self):
        alpha = 0.5
        a2 = alpha * alpha
        f = 1.0 * (a2 - 1.0) + 1.0
        expected = a2 / (math.pi * f * f)
        result = self.lib.brdf_D_GGX(1.0, alpha)
        assert abs(result - expected) < 1e-6, (
            f"D_GGX(1.0, 0.5) = {result:.6f}, expected {expected:.6f}"
        )

    def test_D_GGX_off_peak(self):
        alpha = 0.5
        a2 = alpha * alpha
        NoH = 0.5
        f = NoH * NoH * (a2 - 1.0) + 1.0
        expected = a2 / (math.pi * f * f)
        result = self.lib.brdf_D_GGX(NoH, alpha)
        assert abs(result - expected) < 1e-6

    def test_D_GGX_multiple(self):
        for alpha in [0.1, 0.3, 0.7, 0.9]:
            a2 = alpha * alpha
            for NoH in [0.3, 0.6, 0.9]:
                f = NoH * NoH * (a2 - 1.0) + 1.0
                expected = a2 / (math.pi * f * f)
                result = self.lib.brdf_D_GGX(NoH, alpha)
                assert abs(result - expected) < 1e-5, (
                    f"D_GGX({NoH}, {alpha}) = {result:.6f}, expected {expected:.6f}"
                )

    def test_V_SmithGGX_exact(self):
        NoV, NoL, alpha = 0.5, 0.5, 0.5
        a2 = alpha * alpha
        ggxv = NoL * math.sqrt(NoV * NoV * (1.0 - a2) + a2)
        ggxl = NoV * math.sqrt(NoL * NoL * (1.0 - a2) + a2)
        expected = 0.5 / (ggxv + ggxl + 1e-7)
        result = self.lib.brdf_V_SmithGGX(NoV, NoL, alpha)
        assert abs(result - expected) < 1e-4, (
            f"V_SmithGGX = {result:.6f}, expected {expected:.6f}"
        )

    def test_V_SmithGGX_not_fast_approx(self):
        NoV, NoL, alpha = 0.5, 0.5, 0.5
        a2 = alpha * alpha
        fast_v = NoL * (NoV * (1.0 - alpha) + alpha)
        fast_l = NoV * (NoL * (1.0 - alpha) + alpha)
        fast_result = 0.5 / (fast_v + fast_l + 1e-7)
        exact_v = NoL * math.sqrt(NoV * NoV * (1.0 - a2) + a2)
        exact_l = NoV * math.sqrt(NoL * NoL * (1.0 - a2) + a2)
        exact_result = 0.5 / (exact_v + exact_l + 1e-7)
        result = self.lib.brdf_V_SmithGGX(NoV, NoL, alpha)
        assert abs(result - exact_result) < abs(fast_result - exact_result), (
            f"V_SmithGGX appears to use fast approximation"
        )

    def test_V_SmithGGX_multiple(self):
        for NoV, NoL, alpha in [(0.3, 0.7, 0.2), (0.6, 0.4, 0.6),
                                 (0.9, 0.1, 0.8), (0.2, 0.9, 0.4)]:
            a2 = alpha * alpha
            gv = NoL * math.sqrt(NoV * NoV * (1.0 - a2) + a2)
            gl = NoV * math.sqrt(NoL * NoL * (1.0 - a2) + a2)
            expected = 0.5 / (gv + gl + 1e-7)
            result = self.lib.brdf_V_SmithGGX(NoV, NoL, alpha)
            assert abs(result - expected) < 1e-4

    def test_F_Schlick_fifth_power(self):
        for VoH in [0.2, 0.4, 0.6, 0.8]:
            f0 = 0.04
            expected = f0 + (1.0 - f0) * (1.0 - VoH) ** 5
            result = self.lib.brdf_F_Schlick_scalar(VoH, f0)
            assert abs(result - expected) < 1e-6, (
                f"F_Schlick({VoH}, {f0}) = {result:.6f}, expected {expected:.6f}"
            )

    def test_F_Schlick_grazing(self):
        result = self.lib.brdf_F_Schlick_scalar(0.0, 0.04)
        assert abs(result - 1.0) < 1e-6

    def test_F_Schlick_normal(self):
        result = self.lib.brdf_F_Schlick_scalar(1.0, 0.04)
        assert abs(result - 0.04) < 1e-6

    def test_D_Charlie_zero_at_normal(self):
        result = self.lib.brdf_D_Charlie(1.0, 0.5)
        assert abs(result) < 1e-10

    def test_D_Charlie_value(self):
        NoH, roughness = 0.8, 0.5
        sin2h = max(1.0 - NoH * NoH, 0.0)
        inv_r = 1.0 / roughness
        expected = (2.0 + inv_r) * math.pow(sin2h, inv_r * 0.5) / (2.0 * math.pi)
        result = self.lib.brdf_D_Charlie(NoH, roughness)
        assert abs(result - expected) < 1e-5, (
            f"D_Charlie({NoH}, {roughness}) = {result:.6f}, expected {expected:.6f}"
        )

    def test_D_Charlie_multiple(self):
        for roughness in [0.1, 0.3, 0.5, 0.7, 0.9]:
            for NoH in [0.3, 0.5, 0.8]:
                sin2h = max(1.0 - NoH * NoH, 0.0)
                inv_r = 1.0 / roughness
                expected = (2.0 + inv_r) * math.pow(sin2h, inv_r * 0.5) / \
                           (2.0 * math.pi)
                result = self.lib.brdf_D_Charlie(NoH, roughness)
                assert abs(result - expected) < 1e-5

    def test_V_Neubelt(self):
        for NoV, NoL in [(0.5, 0.5), (0.3, 0.8), (0.8, 0.3)]:
            expected = 1.0 / (4.0 * (NoL + NoV - NoL * NoV) + 1e-7)
            result = self.lib.brdf_V_Neubelt(NoV, NoL)
            assert abs(result - expected) < 1e-5


# ──────────────────────────────────────────────────────────────────────
# C sampling function tests
# ──────────────────────────────────────────────────────────────────────

class TestCSampling:
    """Verify C importance sampling functions."""

    @pytest.fixture(autouse=True)
    def setup_lib(self):
        self.lib = ctypes.CDLL('/app/libbrdf.so')

        class Vec3(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double),
                        ("y", ctypes.c_double),
                        ("z", ctypes.c_double)]

        self.Vec3 = Vec3
        self.lib.sample_GGX.argtypes = [ctypes.c_double, ctypes.c_double,
                                         ctypes.c_double]
        self.lib.sample_GGX.restype = Vec3
        self.lib.sample_hemisphere_cosine.argtypes = [ctypes.c_double,
                                                       ctypes.c_double]
        self.lib.sample_hemisphere_cosine.restype = Vec3
        self.lib.sample_hemisphere_uniform.argtypes = [ctypes.c_double,
                                                        ctypes.c_double]
        self.lib.sample_hemisphere_uniform.restype = Vec3
        self.lib.sample_Charlie.argtypes = [ctypes.c_double, ctypes.c_double,
                                             ctypes.c_double]
        self.lib.sample_Charlie.restype = Vec3
        self.lib.hammersley_radical_inverse.argtypes = [ctypes.c_uint]
        self.lib.hammersley_radical_inverse.restype = ctypes.c_double

    def test_ggx_sample_uses_alpha_squared(self):
        alpha = 0.5
        a2 = alpha * alpha
        xi_y = 0.5
        expected_ct2 = (1.0 - xi_y) / (1.0 + (a2 - 1.0) * xi_y)
        expected_hz = math.sqrt(expected_ct2)
        H = self.lib.sample_GGX(0.0, xi_y, alpha)
        assert abs(H.z - expected_hz) < 1e-4, (
            f"Hz = {H.z:.6f}, expected {expected_hz:.6f}"
        )

    def test_ggx_sample_unit_vector(self):
        for alpha in [0.1, 0.5, 0.9]:
            for xi_x, xi_y in [(0.0, 0.5), (0.25, 0.3), (0.7, 0.8)]:
                H = self.lib.sample_GGX(xi_x, xi_y, alpha)
                length = math.sqrt(H.x * H.x + H.y * H.y + H.z * H.z)
                assert abs(length - 1.0) < 1e-6

    def test_cosine_sample(self):
        xi_y = 0.5
        H = self.lib.sample_hemisphere_cosine(0.0, xi_y)
        expected_ct = math.sqrt(1.0 - xi_y)
        assert abs(H.z - expected_ct) < 1e-6

    def test_uniform_sample(self):
        xi_y = 0.5
        H = self.lib.sample_hemisphere_uniform(0.0, xi_y)
        assert abs(H.z - xi_y) < 1e-6

    def test_charlie_sample(self):
        roughness = 0.5
        xi_y = 0.5
        expected_st = math.pow(xi_y, roughness / (2.0 * roughness + 1.0))
        expected_ct = math.sqrt(max(1.0 - expected_st * expected_st, 0.0))
        H = self.lib.sample_Charlie(0.0, xi_y, roughness)
        assert abs(H.z - expected_ct) < 1e-4

    def test_hammersley_ri(self):
        val = self.lib.hammersley_radical_inverse(ctypes.c_uint(0))
        assert abs(val) < 1e-10
        val1 = self.lib.hammersley_radical_inverse(ctypes.c_uint(1))
        assert abs(val1 - 0.5) < 1e-6


# ──────────────────────────────────────────────────────────────────────
# FFI bridge tests
# ──────────────────────────────────────────────────────────────────────

class TestFFIBridge:
    """Verify Python ctypes bridge works correctly."""

    def test_bridge_imports(self):
        from ffi_bridge import D_GGX, V_SmithGGX, F_Schlick, D_Charlie, V_Neubelt

    def test_bridge_D_GGX(self):
        from ffi_bridge import D_GGX
        alpha = 0.5
        a2 = alpha * alpha
        f = 1.0 * (a2 - 1.0) + 1.0
        expected = a2 / (math.pi * f * f)
        result = D_GGX(1.0, alpha)
        assert abs(result - expected) < 1e-6

    def test_bridge_V_SmithGGX(self):
        from ffi_bridge import V_SmithGGX
        NoV, NoL, alpha = 0.5, 0.5, 0.5
        a2 = alpha * alpha
        gv = NoL * math.sqrt(NoV * NoV * (1.0 - a2) + a2)
        gl = NoV * math.sqrt(NoL * NoL * (1.0 - a2) + a2)
        expected = 0.5 / (gv + gl + 1e-7)
        result = V_SmithGGX(NoV, NoL, alpha)
        assert abs(result - expected) < 1e-4

    def test_bridge_F_Schlick(self):
        from ffi_bridge import F_Schlick
        expected = 0.04 + 0.96 * 0.5 ** 5
        result = F_Schlick(0.5, 0.04)
        assert abs(result - expected) < 1e-6

    def test_bridge_sample_GGX(self):
        from ffi_bridge import sample_GGX
        alpha = 0.5
        a2 = alpha * alpha
        xi_y = 0.5
        expected_ct2 = (1.0 - xi_y) / (1.0 + (a2 - 1.0) * xi_y)
        expected_hz = math.sqrt(expected_ct2)
        H = sample_GGX(0.0, xi_y, alpha)
        assert isinstance(H, tuple), f"Expected tuple, got {type(H)}"
        assert len(H) == 3, f"Expected 3-tuple, got {len(H)}"
        assert abs(H[2] - expected_hz) < 1e-4

    def test_bridge_hammersley(self):
        from ffi_bridge import hammersley_ri
        assert abs(hammersley_ri(0)) < 1e-10
        assert abs(hammersley_ri(1) - 0.5) < 1e-6


# ──────────────────────────────────────────────────────────────────────
# Integrator tests
# ──────────────────────────────────────────────────────────────────────

class TestIntegrators:
    """Verify DFG integrators produce correct values."""

    @staticmethod
    def _reference_dfg(nov, roughness, n=4096):
        """Independent vectorized reference DFG using numpy."""
        import numpy as np
        a = roughness * roughness
        idx = np.arange(n, dtype=np.uint32)
        b = idx.copy()
        for s, m in [(1, 0x55555555), (2, 0x33333333),
                     (4, 0x0F0F0F0F), (8, 0x00FF00FF), (16, 0x0000FFFF)]:
            b = ((b & np.uint32(m)) << np.uint32(s)) | \
                ((b & ~np.uint32(m)) >> np.uint32(s))
        r = b.astype(np.float64) * 2.3283064365386963e-10
        u0 = idx.astype(np.float64) / n
        a2 = a * a
        ph = 2.0 * np.pi * u0
        ct2 = np.clip((1.0 - r) / (1.0 + (a2 - 1.0) * r), 0.0, 1.0)
        ct = np.sqrt(ct2)
        st = np.sqrt(np.clip(1.0 - ct2, 0.0, 1.0))
        hx = st * np.cos(ph)
        hz = ct
        vx = math.sqrt(max(1.0 - nov * nov, 0.0))
        vz = nov
        voh = np.clip(vx * hx + vz * hz, 0.0, None)
        lz = np.clip(2.0 * voh * hz - vz, 0.0, None)
        noh = np.clip(hz, 0.0, None)
        ok = (lz > 0) & (noh > 0)
        gv = lz * np.sqrt(np.clip(nov * nov * (1.0 - a2) + a2, 0.0, None))
        gl = nov * np.sqrt(np.clip(lz * lz * (1.0 - a2) + a2, 0.0, None))
        v = np.where(ok, 0.5 / (gv + gl + 1e-7), 0.0)
        w = np.where(ok, v * 4.0 * voh * lz / (noh + 1e-10), 0.0)
        fc = (1.0 - voh) ** 5
        return float(np.mean(w * (1.0 - fc))), float(np.mean(w * fc))

    def test_ggx_integrator_matches_reference(self):
        from integrators import integrate_dfg_ggx_is
        for NoV, rough in [(0.2, 0.3), (0.5, 0.5), (0.8, 0.7)]:
            x, y = integrate_dfg_ggx_is(NoV, rough, num_samples=4096)
            rx, ry = self._reference_dfg(NoV, rough, n=4096)
            assert abs(x - rx) < 0.02, (
                f"GGX IS DFG.x at ({NoV},{rough}): {x:.4f} vs ref {rx:.4f}"
            )
            assert abs(y - ry) < 0.02, (
                f"GGX IS DFG.y at ({NoV},{rough}): {y:.4f} vs ref {ry:.4f}"
            )

    def test_ggx_integrator_bounds(self):
        from integrators import integrate_dfg_ggx_is
        for nov in [0.1, 0.5, 0.9]:
            for rough in [0.1, 0.5, 0.9]:
                x, y = integrate_dfg_ggx_is(nov, rough, num_samples=1024)
                assert -0.01 <= x <= 1.05, f"DFG.x={x:.4f} out of bounds"
                assert -0.01 <= y <= 1.05, f"DFG.y={y:.4f} out of bounds"

    def test_cosine_integrator_reasonable(self):
        from integrators import integrate_dfg_cosine
        for NoV, rough in [(0.5, 0.5), (0.8, 0.3)]:
            x, y = integrate_dfg_cosine(NoV, rough, num_samples=4096)
            rx, ry = self._reference_dfg(NoV, rough, n=4096)
            assert abs(x - rx) < 0.06, (
                f"Cosine DFG.x at ({NoV},{rough}): {x:.4f} vs ref {rx:.4f}"
            )
            assert abs(y - ry) < 0.06, (
                f"Cosine DFG.y at ({NoV},{rough}): {y:.4f} vs ref {ry:.4f}"
            )

    def test_uniform_integrator_reasonable(self):
        from integrators import integrate_dfg_uniform
        for NoV, rough in [(0.5, 0.5), (0.8, 0.3)]:
            x, y = integrate_dfg_uniform(NoV, rough, num_samples=4096)
            rx, ry = self._reference_dfg(NoV, rough, n=4096)
            assert abs(x - rx) < 0.10, (
                f"Uniform DFG.x at ({NoV},{rough}): {x:.4f} vs ref {rx:.4f}"
            )
            assert abs(y - ry) < 0.10, (
                f"Uniform DFG.y at ({NoV},{rough}): {y:.4f} vs ref {ry:.4f}"
            )

    def test_cloth_integrator(self):
        from integrators import integrate_dfg_cloth
        import numpy as np

        def ref_cloth(nov, roughness, n=4096):
            idx = np.arange(n, dtype=np.uint32)
            b = idx.copy()
            for s, m in [(1, 0x55555555), (2, 0x33333333),
                         (4, 0x0F0F0F0F), (8, 0x00FF00FF), (16, 0x0000FFFF)]:
                b = ((b & np.uint32(m)) << np.uint32(s)) | \
                    ((b & ~np.uint32(m)) >> np.uint32(s))
            r = b.astype(np.float64) * 2.3283064365386963e-10
            u0 = idx.astype(np.float64) / n
            ph = 2.0 * np.pi * u0
            r_cl = np.clip(r, 1e-10, None)
            sin_theta = np.power(r_cl, roughness / (2.0 * roughness + 1.0))
            cos_theta = np.sqrt(np.clip(1.0 - sin_theta ** 2, 0.0, 1.0))
            hx = sin_theta * np.cos(ph)
            hz = cos_theta
            vx = math.sqrt(max(1.0 - nov * nov, 0.0))
            vz = nov
            voh = np.clip(vx * hx + vz * hz, 0.0, None)
            lz = np.clip(2.0 * voh * hz - vz, 0.0, None)
            noh = np.clip(hz, 0.0, None)
            ok = (lz > 0) & (noh > 0)
            v_nb = np.where(ok, 1.0 / (4.0 * (lz + nov - lz * nov) + 1e-7), 0.0)
            w = np.where(ok, v_nb * 4.0 * voh * lz / (noh + 1e-10), 0.0)
            return float(np.mean(w))

        for NoV, rough in [(0.3, 0.3), (0.5, 0.5), (0.7, 0.7)]:
            val = integrate_dfg_cloth(NoV, rough, num_samples=4096)
            ref = ref_cloth(NoV, rough, n=4096)
            assert abs(val - ref) < 0.04, (
                f"Cloth DFG at ({NoV},{rough}): {val:.4f} vs ref {ref:.4f}"
            )

    def test_cloth_integrator_positive(self):
        from integrators import integrate_dfg_cloth
        for nov in [0.2, 0.5, 0.8]:
            for rough in [0.3, 0.6, 0.9]:
                val = integrate_dfg_cloth(nov, rough, num_samples=1024)
                assert val > 0.0, f"Cloth DFG should be > 0 at ({nov}, {rough})"


# ──────────────────────────────────────────────────────────────────────
# Convergence report tests
# ──────────────────────────────────────────────────────────────────────

class TestConvergenceReport:
    """Verify convergence analysis is correct."""

    def test_report_exists(self):
        assert os.path.isfile('/app/convergence_report.json')

    def test_report_structure(self):
        with open('/app/convergence_report.json') as f:
            report = json.load(f)
        assert 'roughness_bands' in report
        for band in ['0.1', '0.3', '0.5', '0.7', '0.9']:
            assert band in report['roughness_bands'], f"Missing band {band}"
            entry = report['roughness_bands'][band]
            assert 'ranking' in entry
            assert 'rmse' in entry
            assert len(entry['ranking']) == 3
            for name in ['ggx_is', 'cosine', 'uniform']:
                assert name in entry['rmse'], f"Missing RMSE for {name}"

    def test_ggx_always_beats_uniform(self):
        """GGX IS should always converge faster than uniform hemisphere."""
        with open('/app/convergence_report.json') as f:
            report = json.load(f)
        for band in ['0.1', '0.3', '0.5', '0.7', '0.9']:
            rmse = report['roughness_bands'][band]['rmse']
            assert rmse['ggx_is'] < rmse['uniform'], (
                f"At roughness={band}, GGX IS RMSE ({rmse['ggx_is']:.6f}) "
                f"should be < uniform RMSE ({rmse['uniform']:.6f})"
            )

    def test_low_roughness_ggx_advantage(self):
        with open('/app/convergence_report.json') as f:
            report = json.load(f)
        entry = report['roughness_bands']['0.1']
        rmse = entry['rmse']
        ratio = rmse['uniform'] / max(rmse['ggx_is'], 1e-10)
        assert ratio > 5.0, (
            f"At roughness=0.1, uniform/ggx_is RMSE ratio = {ratio:.1f}, "
            f"expected > 5.0"
        )

    def test_rmse_values_plausible(self):
        with open('/app/convergence_report.json') as f:
            report = json.load(f)
        for band in ['0.1', '0.5', '0.9']:
            rmse = report['roughness_bands'][band]['rmse']
            assert 0 < rmse['ggx_is'] < 0.05, (
                f"GGX IS RMSE at roughness={band} = {rmse['ggx_is']:.6f}, "
                f"expected 0 < x < 0.05"
            )
            assert rmse['uniform'] > rmse['ggx_is'], (
                f"Uniform RMSE should be > GGX IS at roughness={band}"
            )


# ──────────────────────────────────────────────────────────────────────
# DFG LUT tests
# ──────────────────────────────────────────────────────────────────────

class TestDFGLUT:
    """Verify the final DFG LUT is correct."""

    @staticmethod
    def _reference_dfg(nov, roughness, n=4096):
        import numpy as np
        a = roughness * roughness
        idx = np.arange(n, dtype=np.uint32)
        b = idx.copy()
        for s, m in [(1, 0x55555555), (2, 0x33333333),
                     (4, 0x0F0F0F0F), (8, 0x00FF00FF), (16, 0x0000FFFF)]:
            b = ((b & np.uint32(m)) << np.uint32(s)) | \
                ((b & ~np.uint32(m)) >> np.uint32(s))
        r = b.astype(np.float64) * 2.3283064365386963e-10
        u0 = idx.astype(np.float64) / n
        a2 = a * a
        ph = 2.0 * np.pi * u0
        ct2 = np.clip((1.0 - r) / (1.0 + (a2 - 1.0) * r), 0.0, 1.0)
        ct = np.sqrt(ct2)
        st = np.sqrt(np.clip(1.0 - ct2, 0.0, 1.0))
        hx = st * np.cos(ph)
        hz = ct
        vx = math.sqrt(max(1.0 - nov * nov, 0.0))
        vz = nov
        voh = np.clip(vx * hx + vz * hz, 0.0, None)
        lz = np.clip(2.0 * voh * hz - vz, 0.0, None)
        noh = np.clip(hz, 0.0, None)
        ok = (lz > 0) & (noh > 0)
        gv = lz * np.sqrt(np.clip(nov * nov * (1.0 - a2) + a2, 0.0, None))
        gl = nov * np.sqrt(np.clip(lz * lz * (1.0 - a2) + a2, 0.0, None))
        v = np.where(ok, 0.5 / (gv + gl + 1e-7), 0.0)
        w = np.where(ok, v * 4.0 * voh * lz / (noh + 1e-10), 0.0)
        fc = (1.0 - voh) ** 5
        return float(np.mean(w * (1.0 - fc))), float(np.mean(w * fc))

    def test_lut_exists(self):
        assert os.path.isfile('/app/dfg_lut.json')

    def test_lut_structure(self):
        with open('/app/dfg_lut.json') as f:
            lut = json.load(f)
        assert 'size' in lut
        assert 'standard' in lut
        assert 'cloth' in lut
        assert len(lut['standard']) == lut['size']
        assert len(lut['cloth']) == lut['size']
        for row in lut['standard']:
            assert len(row) == lut['size']
        for row in lut['cloth']:
            assert len(row) == lut['size']

    def test_lut_standard_values(self):
        with open('/app/dfg_lut.json') as f:
            lut = json.load(f)
        size = lut['size']
        for i_nov in [2, size // 4, size // 2, 3 * size // 4]:
            for i_rough in [2, size // 4, size // 2, 3 * size // 4]:
                nov = max((i_nov + 0.5) / size, 0.01)
                rough = max((i_rough + 0.5) / size, 0.01)
                rx, ry = self._reference_dfg(nov, rough, n=4096)
                entry = lut['standard'][i_nov][i_rough]
                assert abs(entry[0] - rx) < 0.04, (
                    f"LUT[{i_nov}][{i_rough}] x: {entry[0]:.4f} vs ref {rx:.4f}"
                )
                assert abs(entry[1] - ry) < 0.04, (
                    f"LUT[{i_nov}][{i_rough}] y: {entry[1]:.4f} vs ref {ry:.4f}"
                )

    def test_lut_bounds(self):
        with open('/app/dfg_lut.json') as f:
            lut = json.load(f)
        for row in lut['standard']:
            for entry in row:
                assert -0.01 <= entry[0] <= 1.05, f"DFG.x={entry[0]} out of bounds"
                assert -0.01 <= entry[1] <= 1.05, f"DFG.y={entry[1]} out of bounds"

    def test_lut_low_roughness_high_reflectance(self):
        with open('/app/dfg_lut.json') as f:
            lut = json.load(f)
        size = lut['size']
        i_nov = size - 2
        i_rough = 1
        x, y = lut['standard'][i_nov][i_rough]
        assert x > 0.8, f"Expected high DFG.x at low rough/high NoV, got {x:.4f}"

    def test_lut_cloth_positive(self):
        with open('/app/dfg_lut.json') as f:
            lut = json.load(f)
        size = lut['size']
        for i in range(2, size - 1, max(size // 4, 1)):
            for j in range(2, size - 1, max(size // 4, 1)):
                val = lut['cloth'][i][j]
                assert val > 0.0, f"Cloth LUT[{i}][{j}] should be positive"
