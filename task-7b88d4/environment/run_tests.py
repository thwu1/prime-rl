#!/usr/bin/env python3
"""
Quick test runner: checks correctness and reports cycle count.
Usage: python3 /app/run_tests.py
"""
import random
import sys
from copy import copy

from problem import (
    Machine, Tree, Input, build_mem_image, reference_kernel2, N_CORES
)
from perf_takehome import KernelBuilder, BASELINE


def run_kernel(forest_height, rounds, batch_size, seed=None):
    if seed is not None:
        random.seed(seed)
    forest = Tree.generate(forest_height)
    inp = Input.generate(forest, batch_size, rounds)
    mem = build_mem_image(forest, inp)
    ref_mem = copy(mem)

    kb = KernelBuilder()
    kb.build_kernel(forest.height, len(forest.values), len(inp.indices), rounds)

    machine = Machine(mem, kb.instrs, kb.debug_info(), n_cores=N_CORES)
    machine.enable_pause = False
    machine.enable_debug = False
    machine.run()

    for rm in reference_kernel2(ref_mem):
        pass

    inp_values_p = ref_mem[6]
    actual = machine.mem[inp_values_p: inp_values_p + len(inp.values)]
    expected = ref_mem[inp_values_p: inp_values_p + len(inp.values)]

    return actual == expected, machine.cycle


def main():
    print("=== Correctness Tests ===")
    all_correct = True
    for i in range(8):
        correct, cycles = run_kernel(10, 16, 256, seed=None)
        status = "PASS" if correct else "FAIL"
        print(f"  Test {i+1}: {status} ({cycles} cycles)")
        if not correct:
            all_correct = False

    print(f"\n=== Performance Test ===")
    random.seed(123)
    correct, cycles = run_kernel(10, 16, 256, seed=123)
    print(f"  Cycles: {cycles}")
    print(f"  Baseline: {BASELINE}")
    print(f"  Speedup: {BASELINE / cycles:.1f}x")
    print(f"  Target: < 17000 cycles")
    print(f"  Status: {'PASS' if cycles < 17000 and correct else 'FAIL'}")

    if not all_correct:
        print("\nFAILED: Output does not match reference kernel")
        sys.exit(1)
    if cycles >= 17000:
        print(f"\nFAILED: {cycles} cycles >= 17000 target")
        sys.exit(1)
    print("\nAll tests passed!")


if __name__ == "__main__":
    main()
