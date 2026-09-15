#!/usr/bin/env python3
"""Test harness for VecTor-16 attention kernel.

Usage:
    pip3 install numpy
    python3 test_harness.py [kernel_path]

Default kernel path: /app/kernels/attention.asm
"""

import os
import sys

try:
    import numpy as np
except ImportError:
    print("ERROR: numpy required. Install with: pip3 install numpy")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from simulator.sim import Simulator, SimulatorError
from reference import scaled_dot_product_attention

D_K = 32
SEQ_LEN = 8
Q_ADDR = 0
K_ADDR = 32
V_ADDR = 288
N_VALID_ADDR = 544
OUTPUT_ADDR = 560


def generate_inputs(seed):
    """Generate random test inputs with a given seed."""
    np.random.seed(seed)
    Q = np.random.randn(D_K)
    K = np.random.randn(SEQ_LEN, D_K)
    V = np.random.randn(SEQ_LEN, D_K)
    return Q, K, V


def test_kernel(kernel_path, seed, n_valid, tol=1e-5):
    """Test a kernel against the reference. Returns True if passed."""
    Q, K, V = generate_inputs(seed)
    expected = scaled_dot_product_attention(Q, K, V, n_valid)

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
    max_abs_diff = np.max(np.abs(actual - expected))
    max_rel_diff = np.max(np.abs(actual - expected) / (np.abs(expected) + 1e-10))

    print(f"  Seed={seed}, n_valid={n_valid}")
    print(f"  Cycles: {cycles}, Instructions: {instr_count}")
    print(f"  Max absolute diff: {max_abs_diff:.2e}")
    print(f"  Max relative diff: {max_rel_diff:.2e}")

    passed = np.allclose(actual, expected, rtol=tol, atol=tol)
    if passed:
        print("  Result: PASSED")
    else:
        print("  Result: FAILED")
        print(f"  Expected (first 5): {expected[:5]}")
        print(f"  Actual   (first 5): {actual[:5]}")
    return passed


def main():
    kernel_path = sys.argv[1] if len(sys.argv) > 1 else '/app/kernels/attention.asm'

    if not os.path.exists(kernel_path):
        print(f"ERROR: Kernel not found: {kernel_path}")
        print("Write your kernel assembly to this file and run again.")
        sys.exit(1)

    print(f"Testing kernel: {kernel_path}")
    print(f"d_k={D_K}, seq_len={SEQ_LEN}, VLEN=16, tiles={D_K // 16}")

    test_cases = [(42, 5), (123, 8), (7, 3)]
    results = []

    for seed, n_valid in test_cases:
        print(f"\n--- Test (seed={seed}, n_valid={n_valid}) ---")
        try:
            passed = test_kernel(kernel_path, seed, n_valid)
            results.append(passed)
        except SimulatorError as e:
            print(f"  Simulator error: {e}")
            results.append(False)
        except Exception as e:
            print(f"  Error: {e}")
            results.append(False)

    print(f"\n{'=' * 40}")
    passed_count = sum(results)
    print(f"Results: {passed_count}/{len(results)} tests passed")
    if all(results):
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)


if __name__ == '__main__':
    main()
