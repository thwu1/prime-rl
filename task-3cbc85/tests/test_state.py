"""Tests for scaled dot-product attention kernel on VecTor-16 simulator.

"""

import os
import sys
import pytest
import numpy as np

sys.path.insert(0, '/app')
from simulator.sim import Simulator, SimulatorError

D_K = 32
SEQ_LEN = 8

Q_ADDR = 0
K_ADDR = 32
V_ADDR = 288
N_VALID_ADDR = 544
OUTPUT_ADDR = 560


def reference_attention(Q, K, V, n_valid):
    """Reference scaled dot-product attention with causal masking."""
    d_k = len(Q)
    scores = K @ Q / np.sqrt(d_k)
    scores[n_valid:] = float('-inf')
    m = np.max(scores)
    exp_scores = np.exp(scores - m)
    attn = exp_scores / np.sum(exp_scores)
    return attn @ V


def generate_inputs(seed):
    np.random.seed(seed)
    Q = np.random.randn(D_K)
    K = np.random.randn(SEQ_LEN, D_K)
    V = np.random.randn(SEQ_LEN, D_K)
    return Q, K, V


def setup_and_run(seed, n_valid, kernel_path='/app/kernels/attention.asm'):
    Q, K, V = generate_inputs(seed)
    expected = reference_attention(Q, K, V, n_valid)

    with open(kernel_path, 'r') as f:
        source = f.read()

    sim = Simulator(memory_size=65536)
    sim.load_memory(Q_ADDR, Q.tolist())
    sim.load_memory(K_ADDR, K.flatten().tolist())
    sim.load_memory(V_ADDR, V.flatten().tolist())
    sim.load_memory(N_VALID_ADDR, [float(n_valid)])

    sim.parse_program(source)
    cycles, instr_count = sim.execute(max_cycles=500000)

    actual = np.array(sim.read_memory(OUTPUT_ADDR, D_K))
    return actual, expected, cycles, sim


def test_kernel_exists():
    """Kernel assembly file must exist."""
    assert os.path.exists('/app/kernels/attention.asm'), \
        "Kernel file /app/kernels/attention.asm not found"


def test_kernel_parses():
    """Kernel must parse without errors."""
    with open('/app/kernels/attention.asm', 'r') as f:
        source = f.read()
    sim = Simulator()
    sim.parse_program(source)
    assert len(sim.instructions) > 0, "Kernel contains no instructions"


def test_kernel_halts():
    """Kernel must terminate via HALT within cycle budget."""
    Q, K, V = generate_inputs(42)

    with open('/app/kernels/attention.asm', 'r') as f:
        source = f.read()

    sim = Simulator(memory_size=65536)
    sim.load_memory(Q_ADDR, Q.tolist())
    sim.load_memory(K_ADDR, K.flatten().tolist())
    sim.load_memory(V_ADDR, V.flatten().tolist())
    sim.load_memory(N_VALID_ADDR, [5.0])

    sim.parse_program(source)
    cycles, _ = sim.execute(max_cycles=500000)
    assert sim.halted, "Kernel did not execute HALT instruction"
    assert cycles < 500000, f"Kernel used {cycles} cycles, exceeding budget"


def test_correctness_partial_mask():
    """Output must match reference: seed=42, n_valid=5 (3 masked positions)."""
    actual, expected, cycles, _ = setup_and_run(seed=42, n_valid=5)
    np.testing.assert_allclose(
        actual, expected, rtol=1e-5, atol=1e-5,
        err_msg=f"Output mismatch (seed=42, n_valid=5, cycles={cycles})"
    )


def test_correctness_no_mask():
    """Output must match reference: seed=123, n_valid=8 (no masking)."""
    actual, expected, cycles, _ = setup_and_run(seed=123, n_valid=8)
    np.testing.assert_allclose(
        actual, expected, rtol=1e-5, atol=1e-5,
        err_msg=f"Output mismatch (seed=123, n_valid=8, cycles={cycles})"
    )


def test_correctness_heavy_mask():
    """Output must match reference: seed=7, n_valid=3 (5 masked positions)."""
    actual, expected, cycles, _ = setup_and_run(seed=7, n_valid=3)
    np.testing.assert_allclose(
        actual, expected, rtol=1e-5, atol=1e-5,
        err_msg=f"Output mismatch (seed=7, n_valid=3, cycles={cycles})"
    )
