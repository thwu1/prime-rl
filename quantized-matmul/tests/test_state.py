
import pytest
import numpy as np
import ctypes
import os


@pytest.fixture(scope="session")
def lib():
    """Build the shared library and load it via ctypes."""
    so_path = "/app/libqmatmul.so"
    assert os.path.exists(so_path), (
        f"{so_path} not found. Run 'make' in /app/ first."
    )

    lib = ctypes.CDLL(so_path)

    # quantize_symmetric
    lib.quantize_symmetric.restype = ctypes.c_int
    lib.quantize_symmetric.argtypes = [
        ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.POINTER(ctypes.c_int8),
        ctypes.POINTER(ctypes.c_float),
    ]

    # dequantize_symmetric
    lib.dequantize_symmetric.restype = ctypes.c_int
    lib.dequantize_symmetric.argtypes = [
        ctypes.POINTER(ctypes.c_int8), ctypes.c_int, ctypes.c_int,
        ctypes.c_float, ctypes.POINTER(ctypes.c_float), ctypes.c_int,
    ]

    # quantize_asymmetric
    lib.quantize_asymmetric.restype = ctypes.c_int
    lib.quantize_asymmetric.argtypes = [
        ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.POINTER(ctypes.c_int8),
        ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float),
    ]

    # dequantize_asymmetric
    lib.dequantize_asymmetric.restype = ctypes.c_int
    lib.dequantize_asymmetric.argtypes = [
        ctypes.POINTER(ctypes.c_int8), ctypes.c_int, ctypes.c_int,
        ctypes.c_float, ctypes.c_float,
        ctypes.POINTER(ctypes.c_float), ctypes.c_int,
    ]

    # quantized_matmul
    lib.quantized_matmul.restype = ctypes.c_int
    lib.quantized_matmul.argtypes = [
        ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_float), ctypes.c_int,
        ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int,
    ]

    # adaptive_quantized_matmul
    lib.adaptive_quantized_matmul.restype = ctypes.c_int
    lib.adaptive_quantized_matmul.argtypes = [
        ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_float), ctypes.c_int,
        ctypes.POINTER(ctypes.c_float), ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
    ]

    # reference_matmul
    lib.reference_matmul.restype = None
    lib.reference_matmul.argtypes = [
        ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_float), ctypes.c_int,
        ctypes.POINTER(ctypes.c_float),
    ]

    return lib


def fptr(arr):
    return arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float))


def i8ptr(arr):
    return arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))


def iptr(arr):
    return arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int))


def run_adaptive(lib, M, K, N, block_size, A, B):
    """Run adaptive_quantized_matmul and return (C_adapt, C_ref, stats, rel_err)."""
    C_ref = np.zeros((M, N), dtype=np.float32)
    C_adapt = np.zeros((M, N), dtype=np.float32)
    stats = np.zeros(2, dtype=np.int32)

    lib.reference_matmul(fptr(A), M, K, fptr(B), N, fptr(C_ref))
    ret = lib.adaptive_quantized_matmul(
        fptr(A), M, K, fptr(B), N, fptr(C_adapt), block_size, iptr(stats))
    assert ret == 0, f"adaptive_quantized_matmul returned {ret}"

    ref_max = np.max(np.abs(C_ref)) + 1e-10
    rel_err = np.max(np.abs(C_ref - C_adapt)) / ref_max
    return C_adapt, C_ref, stats, rel_err


# ---------------------------------------------------------------------------
# Tests for basic correctness of adaptive_quantized_matmul
# ---------------------------------------------------------------------------

class TestAdaptiveCorrectness:
    """Verify adaptive_quantized_matmul produces correct results on various shapes."""

    def test_small_aligned_centered(self, lib):
        np.random.seed(42)
        A = np.ascontiguousarray(np.random.randn(8, 8).astype(np.float32))
        B = np.ascontiguousarray(np.random.randn(8, 8).astype(np.float32))
        _, _, _, rel_err = run_adaptive(lib, 8, 8, 8, 4, A, B)
        assert rel_err < 0.15, f"Error {rel_err:.6f}"

    def test_small_unaligned_centered(self, lib):
        np.random.seed(43)
        A = np.ascontiguousarray(np.random.randn(7, 5).astype(np.float32))
        B = np.ascontiguousarray(np.random.randn(5, 9).astype(np.float32))
        _, _, _, rel_err = run_adaptive(lib, 7, 5, 9, 4, A, B)
        assert rel_err < 0.15, f"Error {rel_err:.6f}"

    def test_medium_aligned_centered(self, lib):
        np.random.seed(44)
        A = np.ascontiguousarray(np.random.randn(32, 64).astype(np.float32))
        B = np.ascontiguousarray(np.random.randn(64, 32).astype(np.float32))
        _, _, _, rel_err = run_adaptive(lib, 32, 64, 32, 16, A, B)
        assert rel_err < 0.15, f"Error {rel_err:.6f}"

    def test_medium_unaligned_centered(self, lib):
        np.random.seed(45)
        A = np.ascontiguousarray(np.random.randn(33, 65).astype(np.float32))
        B = np.ascontiguousarray(np.random.randn(65, 17).astype(np.float32))
        _, _, _, rel_err = run_adaptive(lib, 33, 65, 17, 16, A, B)
        assert rel_err < 0.15, f"Error {rel_err:.6f}"

    def test_small_aligned_biased(self, lib):
        np.random.seed(46)
        A = np.ascontiguousarray(
            np.random.uniform(10.0, 20.0, (16, 16)).astype(np.float32))
        B = np.ascontiguousarray(
            np.random.uniform(10.0, 20.0, (16, 16)).astype(np.float32))
        _, _, _, rel_err = run_adaptive(lib, 16, 16, 16, 8, A, B)
        assert rel_err < 0.15, f"Error {rel_err:.6f}"

    def test_small_unaligned_biased(self, lib):
        np.random.seed(47)
        A = np.ascontiguousarray(
            np.random.uniform(5.0, 15.0, (11, 7)).astype(np.float32))
        B = np.ascontiguousarray(
            np.random.uniform(5.0, 15.0, (7, 13)).astype(np.float32))
        _, _, _, rel_err = run_adaptive(lib, 11, 7, 13, 4, A, B)
        assert rel_err < 0.15, f"Error {rel_err:.6f}"

    def test_1x1(self, lib):
        A = np.array([[3.5]], dtype=np.float32)
        B = np.array([[2.0]], dtype=np.float32)
        _, _, _, rel_err = run_adaptive(lib, 1, 1, 1, 1, A, B)
        assert rel_err < 0.01, f"Error {rel_err:.6f}"

    def test_vector_matrix(self, lib):
        np.random.seed(48)
        A = np.ascontiguousarray(np.random.randn(1, 32).astype(np.float32))
        B = np.ascontiguousarray(np.random.randn(32, 16).astype(np.float32))
        _, _, _, rel_err = run_adaptive(lib, 1, 32, 16, 8, A, B)
        assert rel_err < 0.15, f"Error {rel_err:.6f}"

    def test_block_larger_than_matrix(self, lib):
        np.random.seed(49)
        A = np.ascontiguousarray(np.random.randn(4, 4).astype(np.float32))
        B = np.ascontiguousarray(np.random.randn(4, 4).astype(np.float32))
        _, _, _, rel_err = run_adaptive(lib, 4, 4, 4, 64, A, B)
        assert rel_err < 0.15, f"Error {rel_err:.6f}"

    def test_block_size_1(self, lib):
        """Per-element quantization: near-exact results."""
        np.random.seed(50)
        A = np.ascontiguousarray(np.random.randn(16, 16).astype(np.float32))
        B = np.ascontiguousarray(np.random.randn(16, 16).astype(np.float32))
        _, _, _, rel_err = run_adaptive(lib, 16, 16, 16, 1, A, B)
        assert rel_err < 0.005, f"Error {rel_err:.6f}"


# ---------------------------------------------------------------------------
# Tests for mode selection behavior
# ---------------------------------------------------------------------------

class TestAdaptiveModeSelection:
    """Verify that mode selection is active and reasonable."""

    def test_centered_data_prefers_symmetric(self, lib):
        """On zero-centered data, most tiles should use symmetric mode."""
        np.random.seed(60)
        M, K, N, bs = 32, 32, 32, 8
        A = np.ascontiguousarray(np.random.randn(M, K).astype(np.float32))
        B = np.ascontiguousarray(np.random.randn(K, N).astype(np.float32))
        _, _, stats, rel_err = run_adaptive(lib, M, K, N, bs, A, B)
        assert rel_err < 0.15
        assert stats[0] > 0, "No tiles used symmetric mode on centered data"
        assert stats[0] > stats[1], (
            f"Expected more symmetric ({stats[0]}) than asymmetric ({stats[1]}) "
            f"on centered data"
        )

    def test_biased_data_prefers_asymmetric(self, lib):
        """On strongly biased data, most tiles should use asymmetric mode."""
        np.random.seed(61)
        M, K, N, bs = 32, 32, 32, 8
        A = np.ascontiguousarray(
            np.random.uniform(10.0, 20.0, (M, K)).astype(np.float32))
        B = np.ascontiguousarray(
            np.random.uniform(10.0, 20.0, (K, N)).astype(np.float32))
        _, _, stats, rel_err = run_adaptive(lib, M, K, N, bs, A, B)
        assert rel_err < 0.15
        assert stats[1] > 0, "No tiles used asymmetric mode on biased data"
        assert stats[1] > stats[0], (
            f"Expected more asymmetric ({stats[1]}) than symmetric ({stats[0]}) "
            f"on biased data"
        )

    def test_mixed_data_uses_both_modes(self, lib):
        """On mixed-distribution data, both modes should be used."""
        np.random.seed(62)
        M, K, N, bs = 32, 32, 32, 16
        A = np.zeros((M, K), dtype=np.float32)
        # Top half: biased [10, 20]
        A[:16, :] = np.random.uniform(10.0, 20.0, size=(16, K))
        # Bottom half: centered N(0, 1)
        A[16:, :] = np.random.randn(16, K)
        A = np.ascontiguousarray(A.astype(np.float32))

        B = np.zeros((K, N), dtype=np.float32)
        # Left half: biased [10, 20]
        B[:, :16] = np.random.uniform(10.0, 20.0, size=(K, 16))
        # Right half: centered N(0, 1)
        B[:, 16:] = np.random.randn(K, 16)
        B = np.ascontiguousarray(B.astype(np.float32))

        _, _, stats, rel_err = run_adaptive(lib, M, K, N, bs, A, B)
        assert rel_err < 0.15
        assert stats[0] > 0, "No symmetric tiles on mixed data"
        assert stats[1] > 0, "No asymmetric tiles on mixed data"

    def test_stats_is_null_safe(self, lib):
        """Passing NULL for stats should not crash."""
        np.random.seed(63)
        A = np.ascontiguousarray(np.random.randn(8, 8).astype(np.float32))
        B = np.ascontiguousarray(np.random.randn(8, 8).astype(np.float32))
        C = np.zeros((8, 8), dtype=np.float32)
        ret = lib.adaptive_quantized_matmul(
            fptr(A), 8, 8, fptr(B), 8, fptr(C), 4, None)
        assert ret == 0, f"returned {ret} with NULL stats"


# ---------------------------------------------------------------------------
# Tests for adaptive superiority over uniform modes
# ---------------------------------------------------------------------------

class TestAdaptiveSuperiority:
    """Verify adaptive outperforms uniform symmetric on biased data."""

    def test_beats_symmetric_on_biased(self, lib):
        """On strongly biased data, adaptive error must be lower than symmetric."""
        np.random.seed(70)
        M, K, N, bs = 32, 32, 32, 8
        A = np.ascontiguousarray(
            np.random.uniform(10.0, 20.0, (M, K)).astype(np.float32))
        B = np.ascontiguousarray(
            np.random.uniform(10.0, 20.0, (K, N)).astype(np.float32))

        C_ref = np.zeros((M, N), dtype=np.float32)
        C_sym = np.zeros((M, N), dtype=np.float32)
        C_adapt = np.zeros((M, N), dtype=np.float32)
        stats = np.zeros(2, dtype=np.int32)

        lib.reference_matmul(fptr(A), M, K, fptr(B), N, fptr(C_ref))
        lib.quantized_matmul(fptr(A), M, K, fptr(B), N, fptr(C_sym), bs, 0)
        lib.adaptive_quantized_matmul(
            fptr(A), M, K, fptr(B), N, fptr(C_adapt), bs, iptr(stats))

        ref_max = np.max(np.abs(C_ref)) + 1e-10
        err_sym = np.max(np.abs(C_ref - C_sym)) / ref_max
        err_adapt = np.max(np.abs(C_ref - C_adapt)) / ref_max

        assert err_adapt < err_sym, (
            f"Adaptive error {err_adapt:.6f} >= symmetric error {err_sym:.6f} "
            f"on biased data"
        )

    def test_beats_symmetric_negative_bias(self, lib):
        """On all-negative biased data, adaptive should still beat symmetric."""
        np.random.seed(71)
        M, K, N, bs = 32, 32, 32, 8
        A = np.ascontiguousarray(
            np.random.uniform(-20.0, -5.0, (M, K)).astype(np.float32))
        B = np.ascontiguousarray(
            np.random.uniform(-15.0, -3.0, (K, N)).astype(np.float32))

        C_ref = np.zeros((M, N), dtype=np.float32)
        C_sym = np.zeros((M, N), dtype=np.float32)
        C_adapt = np.zeros((M, N), dtype=np.float32)

        lib.reference_matmul(fptr(A), M, K, fptr(B), N, fptr(C_ref))
        lib.quantized_matmul(fptr(A), M, K, fptr(B), N, fptr(C_sym), bs, 0)
        lib.adaptive_quantized_matmul(
            fptr(A), M, K, fptr(B), N, fptr(C_adapt), bs, None)

        ref_max = np.max(np.abs(C_ref)) + 1e-10
        err_sym = np.max(np.abs(C_ref - C_sym)) / ref_max
        err_adapt = np.max(np.abs(C_ref - C_adapt)) / ref_max

        assert err_adapt < err_sym, (
            f"Adaptive error {err_adapt:.6f} >= symmetric error {err_sym:.6f} "
            f"on negative biased data"
        )


# ---------------------------------------------------------------------------
# Mixed-mode correctness: exercises all four mode combinations
# ---------------------------------------------------------------------------

class TestMixedModeCorrectness:
    """Verify correct math when tiles use different quantization modes."""

    def test_mixed_distribution_all_combos(self, lib):
        """Matrix with biased and centered regions exercises all four
        mode combinations (sym*sym, sym*asym, asym*sym, asym*asym)."""
        np.random.seed(80)
        M, K, N, bs = 32, 32, 32, 16

        A = np.zeros((M, K), dtype=np.float32)
        A[:16, :] = np.random.uniform(10.0, 20.0, size=(16, K))
        A[16:, :] = np.random.randn(16, K)
        A = np.ascontiguousarray(A.astype(np.float32))

        B = np.zeros((K, N), dtype=np.float32)
        B[:, :16] = np.random.uniform(10.0, 20.0, size=(K, 16))
        B[:, 16:] = np.random.randn(K, 16)
        B = np.ascontiguousarray(B.astype(np.float32))

        _, _, stats, rel_err = run_adaptive(lib, M, K, N, bs, A, B)
        assert rel_err < 0.15, f"Error {rel_err:.6f} on mixed-mode test"
        assert stats[0] > 0, "No symmetric tiles in mixed test"
        assert stats[1] > 0, "No asymmetric tiles in mixed test"

    def test_mixed_unaligned(self, lib):
        """Mixed distributions with unaligned dimensions."""
        np.random.seed(81)
        M, K, N, bs = 37, 29, 43, 16

        A = np.zeros((M, K), dtype=np.float32)
        A[:16, :] = np.random.uniform(8.0, 16.0, size=(16, K))
        A[16:, :] = np.random.randn(M - 16, K)
        A = np.ascontiguousarray(A.astype(np.float32))

        B = np.zeros((K, N), dtype=np.float32)
        B[:, :16] = np.random.uniform(8.0, 16.0, size=(K, 16))
        B[:, 16:] = np.random.randn(K, N - 16)
        B = np.ascontiguousarray(B.astype(np.float32))

        _, _, stats, rel_err = run_adaptive(lib, M, K, N, bs, A, B)
        assert rel_err < 0.15, f"Error {rel_err:.6f} on mixed unaligned test"
        assert stats[0] > 0, "No symmetric tiles"
        assert stats[1] > 0, "No asymmetric tiles"

    def test_large_k_mixed_accumulation(self, lib):
        """Large K forces accumulation across many tiles with mixed modes."""
        np.random.seed(82)
        M, K, N, bs = 16, 128, 16, 16

        A = np.zeros((M, K), dtype=np.float32)
        # Alternate biased and centered columns in K dimension
        for kt in range(0, K, bs):
            kend = min(kt + bs, K)
            if (kt // bs) % 2 == 0:
                A[:, kt:kend] = np.random.uniform(5.0, 15.0, size=(M, kend - kt))
            else:
                A[:, kt:kend] = np.random.randn(M, kend - kt)
        A = np.ascontiguousarray(A.astype(np.float32))

        B = np.zeros((K, N), dtype=np.float32)
        for kt in range(0, K, bs):
            kend = min(kt + bs, K)
            if (kt // bs) % 2 == 0:
                B[kt:kend, :] = np.random.randn(kend - kt, N)
            else:
                B[kt:kend, :] = np.random.uniform(5.0, 15.0, size=(kend - kt, N))
        B = np.ascontiguousarray(B.astype(np.float32))

        _, _, stats, rel_err = run_adaptive(lib, M, K, N, bs, A, B)
        assert rel_err < 0.20, f"Error {rel_err:.6f} on large-K mixed test"
        assert stats[0] > 0, "No symmetric tiles in large-K mixed test"
        assert stats[1] > 0, "No asymmetric tiles in large-K mixed test"


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestAdaptiveEdgeCases:
    def test_all_zeros(self, lib):
        A = np.zeros((8, 8), dtype=np.float32)
        B = np.zeros((8, 8), dtype=np.float32)
        C = np.zeros((8, 8), dtype=np.float32)
        stats = np.zeros(2, dtype=np.int32)
        ret = lib.adaptive_quantized_matmul(
            fptr(A), 8, 8, fptr(B), 8, fptr(C), 4, iptr(stats))
        assert ret == 0
        assert np.all(C == 0.0)

    def test_constant_values(self, lib):
        A = np.full((8, 8), 5.0, dtype=np.float32)
        B = np.full((8, 8), 3.0, dtype=np.float32)
        C_ref = np.zeros((8, 8), dtype=np.float32)
        C = np.zeros((8, 8), dtype=np.float32)
        lib.reference_matmul(fptr(A), 8, 8, fptr(B), 8, fptr(C_ref))
        ret = lib.adaptive_quantized_matmul(
            fptr(A), 8, 8, fptr(B), 8, fptr(C), 4, None)
        assert ret == 0
        ref_max = np.max(np.abs(C_ref)) + 1e-10
        rel_err = np.max(np.abs(C_ref - C)) / ref_max
        assert rel_err < 0.15, f"Error {rel_err:.6f}"

    def test_invalid_args(self, lib):
        """Should return -1 for invalid arguments."""
        A = np.zeros((4, 4), dtype=np.float32)
        B = np.zeros((4, 4), dtype=np.float32)
        C = np.zeros((4, 4), dtype=np.float32)
        assert lib.adaptive_quantized_matmul(
            fptr(A), 0, 4, fptr(B), 4, fptr(C), 4, None) == -1
        assert lib.adaptive_quantized_matmul(
            fptr(A), 4, 4, fptr(B), 4, fptr(C), 0, None) == -1

    def test_tall_skinny(self, lib):
        np.random.seed(90)
        A = np.ascontiguousarray(np.random.randn(128, 8).astype(np.float32))
        B = np.ascontiguousarray(np.random.randn(8, 4).astype(np.float32))
        _, _, _, rel_err = run_adaptive(lib, 128, 8, 4, 8, A, B)
        assert rel_err < 0.15, f"Error {rel_err:.6f}"

    def test_wide(self, lib):
        np.random.seed(91)
        A = np.ascontiguousarray(np.random.randn(4, 8).astype(np.float32))
        B = np.ascontiguousarray(np.random.randn(8, 128).astype(np.float32))
        _, _, _, rel_err = run_adaptive(lib, 4, 8, 128, 8, A, B)
        assert rel_err < 0.15, f"Error {rel_err:.6f}"

    def test_large_accumulation(self, lib):
        """Large K tests accumulation across many tiles."""
        np.random.seed(92)
        A = np.ascontiguousarray(np.random.randn(16, 256).astype(np.float32))
        B = np.ascontiguousarray(np.random.randn(256, 16).astype(np.float32))
        _, _, _, rel_err = run_adaptive(lib, 16, 256, 16, 16, A, B)
        assert rel_err < 0.20, f"Error {rel_err:.6f}"
