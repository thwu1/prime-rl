"""Tests for MiniNPU simulator correctness and assembly kernel validation.

"""

import os
import sys

sys.path.insert(0, '/opt/npu')

import numpy as np
import pytest

from simulator import MiniNPU

SEED = 42
VLEN = 16


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_npu():
    return MiniNPU()


# ---------------------------------------------------------------------------
# Simulator unit tests — exercise specific instruction semantics
# ---------------------------------------------------------------------------

class TestSimulatorInstructions:
    """Verify that individual instructions match the ISA spec."""

    def test_vadd_basic(self):
        """VADD: vd[i] = vs1[i] + vs2[i]."""
        npu = make_npu()
        np.random.seed(SEED)
        a = np.random.randn(VLEN).astype(np.float32)
        b = np.random.randn(VLEN).astype(np.float32)
        npu.load_memory(0, a)
        npu.load_memory(16, b)
        npu.load_program("""
VLD v0, 0
VLD v1, 16
VADD v2, v0, v1
VST v2, 32
HALT
""")
        npu.run()
        result = npu.read_memory(32, VLEN)
        expected = a + b
        np.testing.assert_allclose(result, expected, rtol=1e-5, atol=1e-6)

    def test_vsub_correctness(self):
        """VSUB: vd[i] = vs1[i] - vs2[i] (order matters)."""
        npu = make_npu()
        np.random.seed(SEED + 1)
        a = np.random.randn(VLEN).astype(np.float32)
        b = np.random.randn(VLEN).astype(np.float32)
        npu.load_memory(0, a)
        npu.load_memory(16, b)
        npu.load_program("""
VLD v0, 0
VLD v1, 16
VSUB v2, v0, v1
VST v2, 32
HALT
""")
        npu.run()
        result = npu.read_memory(32, VLEN)
        expected = a - b
        np.testing.assert_allclose(result, expected, rtol=1e-5, atol=1e-6)

    def test_vmac_accumulation(self):
        """VMAC: vd[i] += vs1[i] * vs2[i] (must accumulate, not overwrite)."""
        npu = make_npu()
        np.random.seed(SEED + 2)
        a = np.random.randn(VLEN).astype(np.float32)
        b = np.random.randn(VLEN).astype(np.float32)
        c = np.random.randn(VLEN).astype(np.float32)
        d = np.random.randn(VLEN).astype(np.float32)
        npu.load_memory(0, a)
        npu.load_memory(16, b)
        npu.load_memory(32, c)
        npu.load_memory(48, d)
        npu.load_program("""
# v10 = a * b, then v10 += c * d
VBCAST v10, s0
VLD v0, 0
VLD v1, 16
VMAC v10, v0, v1
VLD v2, 32
VLD v3, 48
VMAC v10, v2, v3
VST v10, 64
HALT
""")
        npu.run()
        result = npu.read_memory(64, VLEN)
        expected = (a * b + c * d).astype(np.float32)
        np.testing.assert_allclose(result, expected, rtol=1e-5, atol=1e-6)

    def test_vredsum_all_elements(self):
        """VREDSUM: sd = sum of ALL VLEN elements in vs."""
        npu = make_npu()
        np.random.seed(SEED + 3)
        a = np.random.randn(VLEN).astype(np.float32)
        npu.load_memory(0, a)
        npu.load_program("""
VLD v0, 0
VREDSUM s1, v0
SST s1, 16
HALT
""")
        npu.run()
        result = float(npu.read_memory(16, 1)[0])
        expected = float(np.sum(a))
        np.testing.assert_allclose(result, expected, rtol=1e-5, atol=1e-6)


# ---------------------------------------------------------------------------
# Kernel integration tests — verify agent-written kernels
# ---------------------------------------------------------------------------

class TestKernels:
    """Test assembly kernels against NumPy reference implementations."""

    def test_dotproduct_kernel(self):
        """Dot product of two 64-element vectors."""
        kernel_path = '/opt/npu/programs/dotproduct.asm'
        assert os.path.exists(kernel_path), (
            f"Kernel file {kernel_path} not found — write it first"
        )

        npu = make_npu()
        np.random.seed(SEED + 10)
        a = np.random.randn(64).astype(np.float32)
        b = np.random.randn(64).astype(np.float32)
        npu.load_memory(0, a)
        npu.load_memory(64, b)

        with open(kernel_path) as f:
            npu.load_program(f.read())
        npu.run()

        result = float(npu.read_memory(128, 1)[0])
        expected = float(np.dot(a.astype(np.float64), b.astype(np.float64)))
        np.testing.assert_allclose(result, expected, rtol=1e-3, atol=1e-4)

    def test_softmax_kernel(self):
        """Numerically-stable softmax over 64 elements."""
        kernel_path = '/opt/npu/programs/softmax.asm'
        assert os.path.exists(kernel_path), (
            f"Kernel file {kernel_path} not found — write it first"
        )

        npu = make_npu()
        np.random.seed(SEED + 20)
        x = np.random.randn(64).astype(np.float32)
        npu.load_memory(0, x)

        with open(kernel_path) as f:
            npu.load_program(f.read())
        npu.run()

        result = npu.read_memory(64, 64)

        # Reference: numerically-stable softmax in float64 then compare
        xd = x.astype(np.float64)
        max_x = np.max(xd)
        exp_x = np.exp(xd - max_x)
        expected = (exp_x / np.sum(exp_x)).astype(np.float32)

        np.testing.assert_allclose(result, expected, rtol=1e-3, atol=1e-4)
        # softmax should sum to ~1.0
        np.testing.assert_allclose(np.sum(result), 1.0, rtol=1e-3, atol=1e-4)

    def test_rmsnorm_kernel(self):
        """RMSNorm with weights over 64 elements, epsilon=1e-6."""
        kernel_path = '/opt/npu/programs/rmsnorm.asm'
        assert os.path.exists(kernel_path), (
            f"Kernel file {kernel_path} not found — write it first"
        )

        npu = make_npu()
        np.random.seed(SEED + 30)
        x = np.random.randn(64).astype(np.float32)
        w = np.random.randn(64).astype(np.float32)
        npu.load_memory(0, x)
        npu.load_memory(64, w)

        with open(kernel_path) as f:
            npu.load_program(f.read())
        npu.run()

        result = npu.read_memory(128, 64)

        # Reference: RMSNorm in float64 then compare
        xd = x.astype(np.float64)
        wd = w.astype(np.float64)
        rms = np.sqrt(np.mean(xd ** 2) + 1e-6)
        expected = ((xd / rms) * wd).astype(np.float32)

        np.testing.assert_allclose(result, expected, rtol=1e-3, atol=1e-4)
