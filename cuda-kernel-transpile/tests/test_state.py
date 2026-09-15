"""
Tests for CUDA kernel CPU reference implementation task.

Verifies that the agent's output binary files match reference computations
for FDTD 3D stencil and Black-Scholes option pricing kernels.

"""
import pytest
import numpy as np
import os


# ============================================================
# FDTD 3D Star Stencil Tests
# ============================================================
class TestFDTD3D:
    RADIUS = 4
    DIM = 16
    OUTER = DIM + 2 * RADIUS  # 24

    def _load_inputs(self):
        input_vol = np.fromfile(
            '/app/data/fdtd_input.bin', dtype=np.float32
        ).reshape(self.OUTER, self.OUTER, self.OUTER)
        stencil = np.fromfile(
            '/app/data/fdtd_stencil.bin', dtype=np.float32
        )
        return input_vol, stencil

    def _compute_reference(self, input_vol, stencil):
        """Compute 3D star stencil on inner volume, output zero elsewhere."""
        output = np.zeros(
            (self.OUTER, self.OUTER, self.OUTER), dtype=np.float64
        )
        R = self.RADIUS
        O = self.OUTER
        s, e = R, O - R  # inner region: [4:20, 4:20, 4:20]

        inp = input_vol.astype(np.float64)

        # Center coefficient
        output[s:e, s:e, s:e] = stencil[0] * inp[s:e, s:e, s:e]

        # Neighbor contributions along each axis
        for i in range(1, R + 1):
            output[s:e, s:e, s:e] += stencil[i] * (
                inp[s - i:e - i, s:e, s:e] + inp[s + i:e + i, s:e, s:e] +
                inp[s:e, s - i:e - i, s:e] + inp[s:e, s + i:e + i, s:e] +
                inp[s:e, s:e, s - i:e - i] + inp[s:e, s:e, s + i:e + i]
            )

        return output.astype(np.float32)

    def test_output_file_exists(self):
        assert os.path.exists('/app/output/fdtd_output.bin'), \
            "FDTD output file not found at /app/output/fdtd_output.bin"

    def test_output_size(self):
        output = np.fromfile('/app/output/fdtd_output.bin', dtype=np.float32)
        expected_size = self.OUTER ** 3
        assert output.size == expected_size, \
            f"Expected {expected_size} float32 elements, got {output.size}"

    def test_inner_region_correctness(self):
        """The inner DIM^3 region must match the star stencil computation."""
        input_vol, stencil = self._load_inputs()
        ref = self._compute_reference(input_vol, stencil)
        output = np.fromfile(
            '/app/output/fdtd_output.bin', dtype=np.float32
        ).reshape(self.OUTER, self.OUTER, self.OUTER)

        R = self.RADIUS
        O = self.OUTER
        inner_out = output[R:O - R, R:O - R, R:O - R]
        inner_ref = ref[R:O - R, R:O - R, R:O - R]

        max_diff = np.max(np.abs(inner_out - inner_ref))
        assert max_diff < 1e-4, \
            f"Inner region max difference: {max_diff} (tolerance: 1e-4)"

    def test_halo_is_zero(self):
        """The output's halo (padding) region must remain zero."""
        output = np.fromfile(
            '/app/output/fdtd_output.bin', dtype=np.float32
        ).reshape(self.OUTER, self.OUTER, self.OUTER)

        R = self.RADIUS
        O = self.OUTER

        # Check z-face halos
        assert np.allclose(output[:R, :, :], 0.0, atol=1e-7), \
            "Halo region (z-front) should be zero"
        assert np.allclose(output[O - R:, :, :], 0.0, atol=1e-7), \
            "Halo region (z-back) should be zero"

        # Check y-face halos (excluding already-checked z faces)
        assert np.allclose(output[R:O - R, :R, :], 0.0, atol=1e-7), \
            "Halo region (y-front) should be zero"
        assert np.allclose(output[R:O - R, O - R:, :], 0.0, atol=1e-7), \
            "Halo region (y-back) should be zero"

        # Check x-face halos (excluding already-checked z and y faces)
        assert np.allclose(output[R:O - R, R:O - R, :R], 0.0, atol=1e-7), \
            "Halo region (x-front) should be zero"
        assert np.allclose(output[R:O - R, R:O - R, O - R:], 0.0, atol=1e-7), \
            "Halo region (x-back) should be zero"

    def test_stencil_symmetry(self):
        """Spot-check that the stencil produces non-trivial, symmetric results."""
        output = np.fromfile(
            '/app/output/fdtd_output.bin', dtype=np.float32
        ).reshape(self.OUTER, self.OUTER, self.OUTER)
        R = self.RADIUS
        O = self.OUTER

        inner = output[R:O - R, R:O - R, R:O - R]
        # Should have both positive and negative values for random input
        assert inner.max() > 0, "Inner region should contain positive values"
        assert inner.min() < 0, "Inner region should contain negative values"
        # Should not be all the same value
        assert inner.std() > 0.01, "Inner region should have variance"


# ============================================================
# Black-Scholes Option Pricing Tests
# ============================================================
class TestBlackScholes:
    N = 2048
    R = 0.02
    V = 0.30

    @staticmethod
    def _cnd_poly(d):
        """Polynomial approximation of CND (Abramowitz & Stegun 26.2.17)."""
        A1 = np.float64(0.31938153)
        A2 = np.float64(-0.356563782)
        A3 = np.float64(1.781477937)
        A4 = np.float64(-1.821255978)
        A5 = np.float64(1.330274429)
        RSQRT2PI = np.float64(0.39894228040143267793994605993438)

        d = np.asarray(d, dtype=np.float64)
        K = 1.0 / (1.0 + 0.2316419 * np.abs(d))
        cnd = RSQRT2PI * np.exp(-0.5 * d * d) * (
            K * (A1 + K * (A2 + K * (A3 + K * (A4 + K * A5))))
        )
        return np.where(d > 0, 1.0 - cnd, cnd)

    def _load_inputs(self):
        S = np.fromfile('/app/data/stock_price.bin', dtype=np.float32)
        X = np.fromfile('/app/data/option_strike.bin', dtype=np.float32)
        T = np.fromfile('/app/data/option_years.bin', dtype=np.float32)
        return S, X, T

    def _compute_reference(self, S, X, T):
        """Compute Black-Scholes prices using polynomial CND."""
        S64 = S.astype(np.float64)
        X64 = X.astype(np.float64)
        T64 = T.astype(np.float64)

        sqrtT = np.sqrt(T64)
        d1 = (np.log(S64 / X64) + (self.R + 0.5 * self.V * self.V) * T64) \
            / (self.V * sqrtT)
        d2 = d1 - self.V * sqrtT

        CNDD1 = self._cnd_poly(d1)
        CNDD2 = self._cnd_poly(d2)

        expRT = np.exp(-self.R * T64)
        call_result = (S64 * CNDD1 - X64 * expRT * CNDD2).astype(np.float32)
        put_result = (
            X64 * expRT * (1.0 - CNDD2) - S64 * (1.0 - CNDD1)
        ).astype(np.float32)

        return call_result, put_result

    def test_call_output_exists(self):
        assert os.path.exists('/app/output/call_out.bin'), \
            "Call output file not found at /app/output/call_out.bin"

    def test_put_output_exists(self):
        assert os.path.exists('/app/output/put_out.bin'), \
            "Put output file not found at /app/output/put_out.bin"

    def test_call_output_size(self):
        call = np.fromfile('/app/output/call_out.bin', dtype=np.float32)
        assert call.size == self.N, \
            f"Call output: expected {self.N} elements, got {call.size}"

    def test_put_output_size(self):
        put = np.fromfile('/app/output/put_out.bin', dtype=np.float32)
        assert put.size == self.N, \
            f"Put output: expected {self.N} elements, got {put.size}"

    def test_call_correctness(self):
        """Call prices must match reference within tolerance."""
        S, X, T = self._load_inputs()
        ref_call, _ = self._compute_reference(S, X, T)
        call = np.fromfile('/app/output/call_out.bin', dtype=np.float32)

        max_diff = np.max(np.abs(call - ref_call))
        assert max_diff < 1e-3, \
            f"Call prices max difference: {max_diff} (tolerance: 1e-3)"

    def test_put_correctness(self):
        """Put prices must match reference within tolerance."""
        S, X, T = self._load_inputs()
        _, ref_put = self._compute_reference(S, X, T)
        put = np.fromfile('/app/output/put_out.bin', dtype=np.float32)

        max_diff = np.max(np.abs(put - ref_put))
        assert max_diff < 1e-3, \
            f"Put prices max difference: {max_diff} (tolerance: 1e-3)"

    def test_put_call_parity(self):
        """Verify put-call parity: C - P = S - X * e^(-rT)."""
        S, X, T = self._load_inputs()
        call = np.fromfile('/app/output/call_out.bin', dtype=np.float32)
        put = np.fromfile('/app/output/put_out.bin', dtype=np.float32)

        S64 = S.astype(np.float64)
        X64 = X.astype(np.float64)
        T64 = T.astype(np.float64)

        expected_diff = S64 - X64 * np.exp(-self.R * T64)
        actual_diff = call.astype(np.float64) - put.astype(np.float64)

        max_parity_error = np.max(np.abs(actual_diff - expected_diff))
        assert max_parity_error < 1e-1, \
            f"Put-call parity violation: {max_parity_error} (tolerance: 1e-1)"

    def test_call_prices_non_negative(self):
        """Call option prices must be non-negative."""
        call = np.fromfile('/app/output/call_out.bin', dtype=np.float32)
        assert np.all(call >= -1e-6), \
            f"Found negative call prices: min = {call.min()}"

    def test_put_prices_non_negative(self):
        """Put option prices must be non-negative."""
        put = np.fromfile('/app/output/put_out.bin', dtype=np.float32)
        assert np.all(put >= -1e-6), \
            f"Found negative put prices: min = {put.min()}"
