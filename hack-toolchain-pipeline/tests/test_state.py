"""Tests for the Hack assembly peephole optimizer."""

import sys
import os
import glob
import tempfile

sys.path.insert(0, '/app')

import pytest
from hack_pipeline import translate_vm, assemble, emulate
from optimizer import optimize_asm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def generate_asm(vm_input, bootstrap=False):
    """Generate Hack assembly lines from VM input."""
    if os.path.isdir(vm_input):
        vm_files = sorted(glob.glob(os.path.join(vm_input, '*.vm')))
        bootstrap = True
    else:
        vm_files = [vm_input]
    with tempfile.TemporaryDirectory() as d:
        asm = os.path.join(d, 'out.asm')
        translate_vm(vm_files, asm, bootstrap=bootstrap)
        with open(asm) as f:
            return [l.rstrip('\n') for l in f]


def run_asm(lines, cycles, init_ram=None):
    """Assemble and emulate assembly lines, return RAM dict."""
    with tempfile.TemporaryDirectory() as d:
        asm = os.path.join(d, 'out.asm')
        hack = os.path.join(d, 'out.hack')
        with open(asm, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        assemble(asm, hack)
        return emulate(hack, cycles, init_ram=init_ram)


def count_instructions(lines):
    """Count non-label, non-empty, non-comment instructions."""
    count = 0
    for line in lines:
        s = line.split('//')[0].strip()
        if s and not (s.startswith('(') and s.endswith(')')):
            count += 1
    return count


def get_reduction(vm_input, bootstrap=False):
    """Return (original_count, optimized_count, reduction_fraction)."""
    lines = generate_asm(vm_input, bootstrap=bootstrap)
    opt = optimize_asm(lines)
    orig = count_instructions(lines)
    optimized = count_instructions(opt)
    reduction = 1.0 - optimized / orig if orig > 0 else 0.0
    return orig, optimized, reduction


# ---------------------------------------------------------------------------
# Correctness Tests — optimized code must produce identical RAM states
# ---------------------------------------------------------------------------

class TestCorrectness:
    """Verify optimized assembly produces correct execution results."""

    def test_simple_add(self):
        """push 7, push 8, add -> SP=257, RAM[256]=15."""
        lines = generate_asm('/app/vm_programs/SimpleAdd.vm')
        opt = optimize_asm(lines)
        ram = run_asm(opt, 500, {0: 256})
        assert ram.get(0, 0) == 257
        assert ram.get(256, 0) == 15

    def test_stack_test(self):
        """Full arithmetic/logic: eq, lt, gt, add, sub, neg, and, or."""
        lines = generate_asm('/app/vm_programs/StackTest.vm')
        opt = optimize_asm(lines)
        ram = run_asm(opt, 2000, {0: 256})
        assert ram.get(0, 0) == 260
        assert ram.get(256, 0) == -1   # 17 == 17
        assert ram.get(257, 0) == 0    # 892 < 891 -> false
        assert ram.get(258, 0) == -1   # 32767 > 32766
        assert ram.get(259, 0) == 90   # (56 AND neg(31+53-112)) OR 82

    def test_basic_test(self):
        """Push/pop across local, argument, this, that, temp."""
        lines = generate_asm('/app/vm_programs/BasicTest.vm')
        opt = optimize_asm(lines)
        ram = run_asm(opt, 2000,
                      {0: 256, 1: 300, 2: 400, 3: 3000, 4: 3010})
        assert ram.get(256, 0) == 472
        assert ram.get(300, 0) == 10
        assert ram.get(401, 0) == 21
        assert ram.get(402, 0) == 22
        assert ram.get(3006, 0) == 36
        assert ram.get(3012, 0) == 42
        assert ram.get(3015, 0) == 45
        assert ram.get(11, 0) == 510

    def test_pointer_test(self):
        """Push/pop with pointer, this, that segments."""
        lines = generate_asm('/app/vm_programs/PointerTest.vm')
        opt = optimize_asm(lines)
        ram = run_asm(opt, 1500, {0: 256})
        assert ram.get(0, 0) == 257
        assert ram.get(256, 0) == 6084
        assert ram.get(3, 0) == 3030
        assert ram.get(4, 0) == 3040

    def test_static_test(self):
        """Push/pop with static segment variables."""
        lines = generate_asm('/app/vm_programs/StaticTest.vm')
        opt = optimize_asm(lines)
        ram = run_asm(opt, 1500, {0: 256})
        assert ram.get(0, 0) == 257
        assert ram.get(256, 0) == 1110

    def test_basic_loop(self):
        """Sum 1+2+3 = 6 using label/if-goto loop."""
        lines = generate_asm('/app/vm_programs/BasicLoop.vm')
        opt = optimize_asm(lines)
        ram = run_asm(opt, 5000,
                      {0: 256, 1: 300, 2: 400, 400: 3})
        assert ram.get(0, 0) == 257
        assert ram.get(256, 0) == 6

    def test_fibonacci_series(self):
        """Compute first 6 Fibonacci numbers in RAM[3000..3005]."""
        lines = generate_asm('/app/vm_programs/FibonacciSeries.vm')
        opt = optimize_asm(lines)
        ram = run_asm(opt, 10000,
                      {0: 256, 1: 300, 2: 400, 400: 6, 401: 3000})
        assert ram.get(3000, 0) == 0
        assert ram.get(3001, 0) == 1
        assert ram.get(3002, 0) == 1
        assert ram.get(3003, 0) == 2
        assert ram.get(3004, 0) == 3
        assert ram.get(3005, 0) == 5

    def test_simple_function(self):
        """Function with locals, arithmetic, and return."""
        lines = generate_asm('/app/vm_programs/SimpleFunction.vm')
        opt = optimize_asm(lines)
        ram = run_asm(opt, 1000, {
            0: 317, 1: 317, 2: 310, 3: 3000, 4: 4000,
            310: 1234, 311: 37, 312: 1000, 313: 305,
            314: 300, 315: 3010, 316: 4010
        })
        assert ram.get(0, 0) == 311
        assert ram.get(1, 0) == 305
        assert ram.get(2, 0) == 300
        assert ram.get(3, 0) == 3010
        assert ram.get(4, 0) == 4010
        assert ram.get(310, 0) == 1196

    def test_fibonacci_element(self):
        """Recursive fib(4)=3 with bootstrap and multi-file input."""
        lines = generate_asm('/app/vm_programs/FibonacciElement')
        opt = optimize_asm(lines)
        ram = run_asm(opt, 50000)
        assert ram.get(0, 0) == 262
        assert ram.get(261, 0) == 3


# ---------------------------------------------------------------------------
# Reduction Tests — optimized code must meet size targets
# ---------------------------------------------------------------------------

class TestReduction:
    """Verify optimizer achieves required instruction count reductions."""

    def test_simple_add_reduction(self):
        orig, optimized, reduction = get_reduction(
            '/app/vm_programs/SimpleAdd.vm')
        assert reduction >= 0.30, (
            f"SimpleAdd: {reduction:.1%} reduction ({orig}->{optimized}), "
            f"need >= 30%")

    def test_stack_test_reduction(self):
        orig, optimized, reduction = get_reduction(
            '/app/vm_programs/StackTest.vm')
        assert reduction >= 0.25, (
            f"StackTest: {reduction:.1%} reduction ({orig}->{optimized}), "
            f"need >= 25%")

    def test_basic_test_reduction(self):
        orig, optimized, reduction = get_reduction(
            '/app/vm_programs/BasicTest.vm')
        assert reduction >= 0.15, (
            f"BasicTest: {reduction:.1%} reduction ({orig}->{optimized}), "
            f"need >= 15%")

    def test_pointer_test_reduction(self):
        orig, optimized, reduction = get_reduction(
            '/app/vm_programs/PointerTest.vm')
        assert reduction >= 0.25, (
            f"PointerTest: {reduction:.1%} reduction ({orig}->{optimized}), "
            f"need >= 25%")

    def test_static_test_reduction(self):
        orig, optimized, reduction = get_reduction(
            '/app/vm_programs/StaticTest.vm')
        assert reduction >= 0.25, (
            f"StaticTest: {reduction:.1%} reduction ({orig}->{optimized}), "
            f"need >= 25%")

    def test_basic_loop_reduction(self):
        orig, optimized, reduction = get_reduction(
            '/app/vm_programs/BasicLoop.vm')
        assert reduction >= 0.15, (
            f"BasicLoop: {reduction:.1%} reduction ({orig}->{optimized}), "
            f"need >= 15%")

    def test_fibonacci_series_reduction(self):
        orig, optimized, reduction = get_reduction(
            '/app/vm_programs/FibonacciSeries.vm')
        assert reduction >= 0.15, (
            f"FibonacciSeries: {reduction:.1%} reduction "
            f"({orig}->{optimized}), need >= 15%")


# ---------------------------------------------------------------------------
# Safety Tests — optimizer must preserve structural properties
# ---------------------------------------------------------------------------

class TestSafety:
    """Verify optimizer maintains correctness invariants."""

    def test_idempotent(self):
        """Applying optimizer twice yields same result as once."""
        lines = generate_asm('/app/vm_programs/StackTest.vm')
        opt1 = optimize_asm(lines)
        opt2 = optimize_asm(opt1)
        assert opt1 == opt2, "Optimizer is not idempotent"

    def test_labels_preserved(self):
        """All labels from input must appear in output unchanged."""
        lines = generate_asm('/app/vm_programs/FibonacciSeries.vm')
        orig_labels = sorted(
            l.strip() for l in lines
            if l.strip().startswith('(') and l.strip().endswith(')'))
        opt = optimize_asm(lines)
        opt_labels = sorted(
            l.strip() for l in opt
            if l.strip().startswith('(') and l.strip().endswith(')'))
        assert orig_labels == opt_labels, (
            f"Labels changed: {set(orig_labels) ^ set(opt_labels)}")

    def test_reference_asm_correctness(self):
        """Optimizer must not break hand-written reference assembly."""
        with open('/app/asm_programs/Max.asm') as f:
            lines = [l.rstrip('\n') for l in f]
        opt = optimize_asm(lines)
        ram = run_asm(opt, 50, init_ram={0: 23, 1: 15})
        assert ram.get(2, 0) == 23, "Max.asm broken after optimization"
