
"""
Tests for memory-efficient attention implementation.

Verifies forward and backward passes (causal and non-causal) against naive
reference implementations, plus independent finite-difference gradient checks.
Also verifies that the implementation uses the C shared library.
"""

import os
import pytest
import sys
import importlib.util
import numpy as np

sys.path.insert(0, "/app")

# Load reference module directly from file path to avoid any module resolution issues
_ref_spec = importlib.util.spec_from_file_location("reference", "/app/reference.py")
_ref_mod = importlib.util.module_from_spec(_ref_spec)
_ref_spec.loader.exec_module(_ref_mod)

reference_forward = _ref_mod.reference_forward
reference_backward = _ref_mod.reference_backward
reference_causal_forward = _ref_mod.reference_causal_forward
reference_causal_backward = _ref_mod.reference_causal_backward

_fa = None


def _get_fa():
    global _fa
    if _fa is None:
        import flash_attention as m
        _fa = m
    return _fa


def make_qkv(N, d, seed=42):
    rng = np.random.RandomState(seed)
    Q = rng.randn(N, d).astype(np.float64)
    K = rng.randn(N, d).astype(np.float64)
    V = rng.randn(N, d).astype(np.float64)
    return Q, K, V


def make_do(N, d, seed=123):
    rng = np.random.RandomState(seed)
    return rng.randn(N, d).astype(np.float64)


# ==================================================================
# Source code and build integrity checks
# ==================================================================

class TestBuildIntegrity:
    """Verify the implementation uses the C shared library correctly."""

    def test_shared_library_exists(self):
        """The compiled shared library must be present."""
        assert os.path.exists("/app/libattention.so"), \
            "libattention.so must exist in /app/ -- build the C library first"

    def test_uses_c_library(self):
        """flash_attention.py must use the C library, not pure Python."""
        source = open("/app/flash_attention.py").read()
        uses_ctypes = "ctypes" in source
        uses_attention_module = "import attention" in source or \
                                "from attention" in source
        assert uses_ctypes or uses_attention_module, \
            "flash_attention.py must use ctypes or import from attention.py"

    def test_no_reference_import(self):
        source = open("/app/flash_attention.py").read()
        assert "import reference" not in source, "Must not import reference module"
        assert "from reference" not in source, "Must not import from reference module"

    def test_not_stub(self):
        """Functions must have actual implementations."""
        source = open("/app/flash_attention.py").read()
        assert source.count("raise NotImplementedError") == 0, \
            "All stubs must be replaced with implementations"

    def test_c_has_causal_functions(self):
        """C source must contain causal forward and backward implementations."""
        source = open("/app/src/blocked_attention.c").read()
        assert "blocked_causal_forward" in source, \
            "C source must implement blocked_causal_forward"
        assert "blocked_causal_backward" in source, \
            "C source must implement blocked_causal_backward"

    def test_has_block_iteration(self):
        """C implementation must use block iteration pattern."""
        source = open("/app/src/blocked_attention.c").read()
        assert "block_size" in source, "Must use block_size parameter"
        assert "for" in source, "Must contain loop structures for block iteration"

    def test_callable(self):
        fa = _get_fa()
        assert callable(getattr(fa, "flash_attention_forward", None))
        assert callable(getattr(fa, "flash_attention_causal_forward", None))
        assert callable(getattr(fa, "flash_attention_backward", None))
        assert callable(getattr(fa, "flash_attention_causal_backward", None))


# ==================================================================
# Forward pass tests (non-causal)
# ==================================================================

class TestForwardNonCausal:

    @pytest.mark.parametrize("N,d,bs", [
        (32, 16, 8),
        (32, 16, 16),
        (32, 16, 32),
        (64, 32, 16),
        (128, 64, 32),
    ])
    def test_divisible(self, N, d, bs):
        Q, K, V = make_qkv(N, d)
        ref_O, ref_L = reference_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_forward(Q, K, V, bs)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10, rtol=1e-10)
        np.testing.assert_allclose(got_L, ref_L, atol=1e-10, rtol=1e-10)

    @pytest.mark.parametrize("N,d,bs", [
        (30, 16, 8),
        (33, 16, 8),
        (17, 32, 8),
        (100, 64, 32),
        (65, 32, 16),
        (7, 4, 3),
    ])
    def test_non_divisible(self, N, d, bs):
        Q, K, V = make_qkv(N, d)
        ref_O, ref_L = reference_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_forward(Q, K, V, bs)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10, rtol=1e-10)
        np.testing.assert_allclose(got_L, ref_L, atol=1e-10, rtol=1e-10)

    def test_block_size_one(self):
        Q, K, V = make_qkv(16, 8)
        ref_O, ref_L = reference_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_forward(Q, K, V, 1)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10, rtol=1e-10)

    def test_single_element(self):
        Q, K, V = make_qkv(1, 8)
        ref_O, ref_L = reference_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_forward(Q, K, V, 1)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10, rtol=1e-10)
        np.testing.assert_allclose(got_O, V, atol=1e-10)

    def test_block_size_larger_than_N(self):
        Q, K, V = make_qkv(8, 4)
        ref_O, ref_L = reference_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_forward(Q, K, V, 64)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10, rtol=1e-10)

    def test_different_block_sizes_same_result(self):
        Q, K, V = make_qkv(64, 16)
        ref_O, _ = reference_forward(Q, K, V)
        for bs in [1, 4, 8, 16, 32, 64]:
            got_O, _ = _get_fa().flash_attention_forward(Q, K, V, bs)
            np.testing.assert_allclose(
                got_O, ref_O, atol=1e-10, rtol=1e-10,
                err_msg=f"Mismatch for block_size={bs}"
            )

    @pytest.mark.parametrize("d", [1, 4, 16, 64, 128])
    def test_various_head_dims(self, d):
        Q, K, V = make_qkv(32, d)
        ref_O, ref_L = reference_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_forward(Q, K, V, 8)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10, rtol=1e-10)

    def test_output_shapes(self):
        N, d = 32, 16
        Q, K, V = make_qkv(N, d)
        O, L = _get_fa().flash_attention_forward(Q, K, V, 8)
        assert O.shape == (N, d)
        assert L.shape == (N,)


# ==================================================================
# Forward pass tests (causal)
# ==================================================================

class TestForwardCausal:

    @pytest.mark.parametrize("N,d,bs", [
        (32, 16, 8),
        (32, 16, 16),
        (32, 16, 32),
        (64, 32, 16),
    ])
    def test_divisible(self, N, d, bs):
        Q, K, V = make_qkv(N, d)
        ref_O, ref_L = reference_causal_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_causal_forward(Q, K, V, bs)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10, rtol=1e-10)
        np.testing.assert_allclose(got_L, ref_L, atol=1e-10, rtol=1e-10)

    @pytest.mark.parametrize("N,d,bs", [
        (30, 16, 8),
        (33, 16, 8),
        (17, 32, 8),
        (7, 4, 3),
    ])
    def test_non_divisible(self, N, d, bs):
        Q, K, V = make_qkv(N, d)
        ref_O, ref_L = reference_causal_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_causal_forward(Q, K, V, bs)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10, rtol=1e-10)
        np.testing.assert_allclose(got_L, ref_L, atol=1e-10, rtol=1e-10)

    def test_first_row_self_attention(self):
        """First row of causal attention only attends to itself -> output = V[0]."""
        Q, K, V = make_qkv(16, 8)
        O, L = _get_fa().flash_attention_causal_forward(Q, K, V, 4)
        np.testing.assert_allclose(O[0], V[0], atol=1e-10)

    def test_causal_differs_from_noncausal(self):
        """For N > 1, causal and non-causal outputs must differ."""
        Q, K, V = make_qkv(16, 8)
        O_nc, _ = _get_fa().flash_attention_forward(Q, K, V, 4)
        O_c, _ = _get_fa().flash_attention_causal_forward(Q, K, V, 4)
        assert not np.allclose(O_nc, O_c), "Causal should differ from non-causal"

    def test_single_element_causal(self):
        Q, K, V = make_qkv(1, 4)
        ref_O, ref_L = reference_causal_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_causal_forward(Q, K, V, 1)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10)

    def test_block_size_one_causal(self):
        Q, K, V = make_qkv(16, 8)
        ref_O, ref_L = reference_causal_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_causal_forward(Q, K, V, 1)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10, rtol=1e-10)

    def test_block_size_larger_than_N_causal(self):
        Q, K, V = make_qkv(8, 4)
        ref_O, ref_L = reference_causal_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_causal_forward(Q, K, V, 64)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10, rtol=1e-10)

    def test_different_block_sizes_same_result_causal(self):
        Q, K, V = make_qkv(48, 16)
        ref_O, _ = reference_causal_forward(Q, K, V)
        for bs in [1, 6, 8, 16, 24, 48]:
            got_O, _ = _get_fa().flash_attention_causal_forward(Q, K, V, bs)
            np.testing.assert_allclose(
                got_O, ref_O, atol=1e-10, rtol=1e-10,
                err_msg=f"Causal mismatch for block_size={bs}"
            )

    def test_output_shapes_causal(self):
        N, d = 32, 16
        Q, K, V = make_qkv(N, d)
        O, L = _get_fa().flash_attention_causal_forward(Q, K, V, 8)
        assert O.shape == (N, d)
        assert L.shape == (N,)


# ==================================================================
# Backward pass tests (non-causal)
# ==================================================================

class TestBackwardNonCausal:

    @pytest.mark.parametrize("N,d,bs", [
        (32, 16, 8),
        (32, 16, 16),
        (32, 16, 32),
        (64, 32, 16),
    ])
    def test_divisible(self, N, d, bs):
        Q, K, V = make_qkv(N, d)
        dO = make_do(N, d)
        ref_O, ref_L = reference_forward(Q, K, V)
        ref_dQ, ref_dK, ref_dV = reference_backward(Q, K, V, ref_O, dO, ref_L)
        got_O, got_L = _get_fa().flash_attention_forward(Q, K, V, bs)
        got_dQ, got_dK, got_dV = _get_fa().flash_attention_backward(
            Q, K, V, got_O, dO, got_L, bs
        )
        np.testing.assert_allclose(got_dQ, ref_dQ, atol=1e-8, rtol=1e-8)
        np.testing.assert_allclose(got_dK, ref_dK, atol=1e-8, rtol=1e-8)
        np.testing.assert_allclose(got_dV, ref_dV, atol=1e-8, rtol=1e-8)

    @pytest.mark.parametrize("N,d,bs", [
        (30, 16, 8),
        (33, 16, 8),
        (17, 32, 8),
        (65, 32, 16),
    ])
    def test_non_divisible(self, N, d, bs):
        Q, K, V = make_qkv(N, d)
        dO = make_do(N, d)
        ref_O, ref_L = reference_forward(Q, K, V)
        ref_dQ, ref_dK, ref_dV = reference_backward(Q, K, V, ref_O, dO, ref_L)
        got_O, got_L = _get_fa().flash_attention_forward(Q, K, V, bs)
        got_dQ, got_dK, got_dV = _get_fa().flash_attention_backward(
            Q, K, V, got_O, dO, got_L, bs
        )
        np.testing.assert_allclose(got_dQ, ref_dQ, atol=1e-8, rtol=1e-8)
        np.testing.assert_allclose(got_dK, ref_dK, atol=1e-8, rtol=1e-8)
        np.testing.assert_allclose(got_dV, ref_dV, atol=1e-8, rtol=1e-8)

    def test_gradient_shapes(self):
        N, d = 32, 16
        Q, K, V = make_qkv(N, d)
        dO = make_do(N, d)
        O, L = _get_fa().flash_attention_forward(Q, K, V, 8)
        dQ, dK, dV = _get_fa().flash_attention_backward(Q, K, V, O, dO, L, 8)
        assert dQ.shape == Q.shape
        assert dK.shape == K.shape
        assert dV.shape == V.shape

    def test_numerical_gradient_dQ(self):
        """Verify dQ via finite differences."""
        N, d = 8, 4
        Q, K, V = make_qkv(N, d, seed=7)
        dO = make_do(N, d, seed=8)
        O, L = _get_fa().flash_attention_forward(Q, K, V, 4)
        dQ, _, _ = _get_fa().flash_attention_backward(Q, K, V, O, dO, L, 4)

        eps = 1e-5
        dQ_num = np.zeros_like(Q)
        for i in range(N):
            for j in range(d):
                Qp = Q.copy(); Qp[i, j] += eps
                Qm = Q.copy(); Qm[i, j] -= eps
                Op, _ = _get_fa().flash_attention_forward(Qp, K, V, 4)
                Om, _ = _get_fa().flash_attention_forward(Qm, K, V, 4)
                dQ_num[i, j] = np.sum((Op - Om) * dO) / (2 * eps)
        np.testing.assert_allclose(dQ, dQ_num, atol=1e-5, rtol=1e-5)

    def test_numerical_gradient_dK(self):
        """Verify dK via finite differences."""
        N, d = 8, 4
        Q, K, V = make_qkv(N, d, seed=7)
        dO = make_do(N, d, seed=8)
        O, L = _get_fa().flash_attention_forward(Q, K, V, 4)
        _, dK, _ = _get_fa().flash_attention_backward(Q, K, V, O, dO, L, 4)

        eps = 1e-5
        dK_num = np.zeros_like(K)
        for i in range(N):
            for j in range(d):
                Kp = K.copy(); Kp[i, j] += eps
                Km = K.copy(); Km[i, j] -= eps
                Op, _ = _get_fa().flash_attention_forward(Q, Kp, V, 4)
                Om, _ = _get_fa().flash_attention_forward(Q, Km, V, 4)
                dK_num[i, j] = np.sum((Op - Om) * dO) / (2 * eps)
        np.testing.assert_allclose(dK, dK_num, atol=1e-5, rtol=1e-5)

    def test_numerical_gradient_dV(self):
        """Verify dV via finite differences."""
        N, d = 8, 4
        Q, K, V = make_qkv(N, d, seed=7)
        dO = make_do(N, d, seed=8)
        O, L = _get_fa().flash_attention_forward(Q, K, V, 4)
        _, _, dV = _get_fa().flash_attention_backward(Q, K, V, O, dO, L, 4)

        eps = 1e-5
        dV_num = np.zeros_like(V)
        for i in range(N):
            for j in range(d):
                Vp = V.copy(); Vp[i, j] += eps
                Vm = V.copy(); Vm[i, j] -= eps
                Op, _ = _get_fa().flash_attention_forward(Q, K, Vp, 4)
                Om, _ = _get_fa().flash_attention_forward(Q, K, Vm, 4)
                dV_num[i, j] = np.sum((Op - Om) * dO) / (2 * eps)
        np.testing.assert_allclose(dV, dV_num, atol=1e-5, rtol=1e-5)


# ==================================================================
# Backward pass tests (causal)
# ==================================================================

class TestBackwardCausal:

    @pytest.mark.parametrize("N,d,bs", [
        (32, 16, 8),
        (32, 16, 16),
        (64, 32, 16),
    ])
    def test_divisible(self, N, d, bs):
        Q, K, V = make_qkv(N, d)
        dO = make_do(N, d)
        ref_O, ref_L = reference_causal_forward(Q, K, V)
        ref_dQ, ref_dK, ref_dV = reference_causal_backward(
            Q, K, V, ref_O, dO, ref_L
        )
        got_O, got_L = _get_fa().flash_attention_causal_forward(Q, K, V, bs)
        got_dQ, got_dK, got_dV = _get_fa().flash_attention_causal_backward(
            Q, K, V, got_O, dO, got_L, bs
        )
        np.testing.assert_allclose(got_dQ, ref_dQ, atol=1e-8, rtol=1e-8)
        np.testing.assert_allclose(got_dK, ref_dK, atol=1e-8, rtol=1e-8)
        np.testing.assert_allclose(got_dV, ref_dV, atol=1e-8, rtol=1e-8)

    @pytest.mark.parametrize("N,d,bs", [
        (30, 16, 8),
        (33, 16, 8),
        (17, 32, 8),
    ])
    def test_non_divisible(self, N, d, bs):
        Q, K, V = make_qkv(N, d)
        dO = make_do(N, d)
        ref_O, ref_L = reference_causal_forward(Q, K, V)
        ref_dQ, ref_dK, ref_dV = reference_causal_backward(
            Q, K, V, ref_O, dO, ref_L
        )
        got_O, got_L = _get_fa().flash_attention_causal_forward(Q, K, V, bs)
        got_dQ, got_dK, got_dV = _get_fa().flash_attention_causal_backward(
            Q, K, V, got_O, dO, got_L, bs
        )
        np.testing.assert_allclose(got_dQ, ref_dQ, atol=1e-8, rtol=1e-8)
        np.testing.assert_allclose(got_dK, ref_dK, atol=1e-8, rtol=1e-8)
        np.testing.assert_allclose(got_dV, ref_dV, atol=1e-8, rtol=1e-8)

    def test_numerical_gradient_causal_dQ(self):
        """Verify causal dQ via finite differences."""
        N, d = 8, 4
        Q, K, V = make_qkv(N, d, seed=7)
        dO = make_do(N, d, seed=8)
        O, L = _get_fa().flash_attention_causal_forward(Q, K, V, 4)
        dQ, _, _ = _get_fa().flash_attention_causal_backward(Q, K, V, O, dO, L, 4)

        eps = 1e-5
        dQ_num = np.zeros_like(Q)
        for i in range(N):
            for j in range(d):
                Qp = Q.copy(); Qp[i, j] += eps
                Qm = Q.copy(); Qm[i, j] -= eps
                Op, _ = _get_fa().flash_attention_causal_forward(Qp, K, V, 4)
                Om, _ = _get_fa().flash_attention_causal_forward(Qm, K, V, 4)
                dQ_num[i, j] = np.sum((Op - Om) * dO) / (2 * eps)
        np.testing.assert_allclose(dQ, dQ_num, atol=1e-5, rtol=1e-5)

    def test_numerical_gradient_causal_dK(self):
        """Verify causal dK via finite differences."""
        N, d = 8, 4
        Q, K, V = make_qkv(N, d, seed=7)
        dO = make_do(N, d, seed=8)
        O, L = _get_fa().flash_attention_causal_forward(Q, K, V, 4)
        _, dK, _ = _get_fa().flash_attention_causal_backward(Q, K, V, O, dO, L, 4)

        eps = 1e-5
        dK_num = np.zeros_like(K)
        for i in range(N):
            for j in range(d):
                Kp = K.copy(); Kp[i, j] += eps
                Km = K.copy(); Km[i, j] -= eps
                Op, _ = _get_fa().flash_attention_causal_forward(Q, Kp, V, 4)
                Om, _ = _get_fa().flash_attention_causal_forward(Q, Km, V, 4)
                dK_num[i, j] = np.sum((Op - Om) * dO) / (2 * eps)
        np.testing.assert_allclose(dK, dK_num, atol=1e-5, rtol=1e-5)

    def test_numerical_gradient_causal_dV(self):
        """Verify causal dV via finite differences."""
        N, d = 8, 4
        Q, K, V = make_qkv(N, d, seed=7)
        dO = make_do(N, d, seed=8)
        O, L = _get_fa().flash_attention_causal_forward(Q, K, V, 4)
        _, _, dV = _get_fa().flash_attention_causal_backward(Q, K, V, O, dO, L, 4)

        eps = 1e-5
        dV_num = np.zeros_like(V)
        for i in range(N):
            for j in range(d):
                Vp = V.copy(); Vp[i, j] += eps
                Vm = V.copy(); Vm[i, j] -= eps
                Op, _ = _get_fa().flash_attention_causal_forward(Q, K, Vp, 4)
                Om, _ = _get_fa().flash_attention_causal_forward(Q, K, Vm, 4)
                dV_num[i, j] = np.sum((Op - Om) * dO) / (2 * eps)
        np.testing.assert_allclose(dV, dV_num, atol=1e-5, rtol=1e-5)

    def test_causal_backward_differs_from_noncausal(self):
        """Causal and non-causal backward should produce different gradients."""
        N, d = 16, 8
        Q, K, V = make_qkv(N, d)
        dO = make_do(N, d)
        O_nc, L_nc = _get_fa().flash_attention_forward(Q, K, V, 4)
        O_c, L_c = _get_fa().flash_attention_causal_forward(Q, K, V, 4)
        dQ_nc, _, _ = _get_fa().flash_attention_backward(Q, K, V, O_nc, dO, L_nc, 4)
        dQ_c, _, _ = _get_fa().flash_attention_causal_backward(Q, K, V, O_c, dO, L_c, 4)
        assert not np.allclose(dQ_nc, dQ_c), \
            "Causal and non-causal backward should produce different gradients"


# ==================================================================
# Cross-consistency tests
# ==================================================================

class TestCrossConsistency:

    def test_forward_backward_bridge(self):
        """The L from forward must enable correct backward recomputation."""
        N, d = 32, 16
        Q, K, V = make_qkv(N, d)
        O, L = _get_fa().flash_attention_forward(Q, K, V, 8)
        ref_O, ref_L = reference_forward(Q, K, V)
        np.testing.assert_allclose(L, ref_L, atol=1e-10, rtol=1e-10,
                                   err_msg="Auxiliary values must match reference")

    def test_causal_forward_backward_bridge(self):
        """The causal L from forward must match reference."""
        N, d = 32, 16
        Q, K, V = make_qkv(N, d)
        O, L = _get_fa().flash_attention_causal_forward(Q, K, V, 8)
        ref_O, ref_L = reference_causal_forward(Q, K, V)
        np.testing.assert_allclose(L, ref_L, atol=1e-10, rtol=1e-10,
                                   err_msg="Causal auxiliary values must match reference")

    def test_large_sequence(self):
        """Test with larger sequence to verify scalability."""
        N, d = 256, 32
        Q, K, V = make_qkv(N, d, seed=55)
        ref_O, ref_L = reference_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_forward(Q, K, V, 32)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10, rtol=1e-10)

    def test_large_sequence_causal(self):
        """Test causal with larger sequence."""
        N, d = 256, 32
        Q, K, V = make_qkv(N, d, seed=55)
        ref_O, ref_L = reference_causal_forward(Q, K, V)
        got_O, got_L = _get_fa().flash_attention_causal_forward(Q, K, V, 32)
        np.testing.assert_allclose(got_O, ref_O, atol=1e-10, rtol=1e-10)
