"""Tests for the VLIW optimizer.

Verifies that the optimizer produces:
1. Functionally correct output (identical memory state to sequential execution)
2. Valid VLIW bundles (unit slot constraints, no WAW hazards)
3. Register allocation within budget
4. Schedule within cycle budget
"""


import sys
import os

sys.path.insert(0, '/app')

from machine import VLIWMachine, validate_bundle, max_register
from vasm_parser import parse_vasm


PROGRAM_DIR = '/app/programs'


def _load_program(filename):
    path = os.path.join(PROGRAM_DIR, filename)
    with open(path) as f:
        return parse_vasm(f.read())


def _load_optimize():
    from optimize import optimize
    return optimize


def _run_test(program):
    optimize = _load_optimize()
    instructions = program["instructions"]
    max_regs = program["max_regs"]
    max_cycles = program["max_cycles"]
    initial_mem = program["initial_memory"]

    # Run reference (sequential, one instruction per cycle)
    ref_machine = VLIWMachine(initial_mem)
    ref_output = ref_machine.run_sequential(instructions)

    # Run optimizer
    bundles = optimize(instructions, max_regs)

    # Verify bundles is a list of lists
    assert isinstance(bundles, list), "optimize must return a list of bundles"
    for i, bundle in enumerate(bundles):
        assert isinstance(bundle, list), f"Bundle {i} must be a list of instructions"
        for j, inst in enumerate(bundle):
            assert isinstance(inst, dict), f"Bundle {i}, inst {j} must be a dict"
            assert "op" in inst, f"Bundle {i}, inst {j} missing 'op'"
            assert "dst" in inst, f"Bundle {i}, inst {j} missing 'dst'"
            assert "srcs" in inst, f"Bundle {i}, inst {j} missing 'srcs'"

    # Validate each bundle respects VLIW constraints
    for i, bundle in enumerate(bundles):
        valid, msg = validate_bundle(bundle)
        assert valid, f"Bundle {i} violates VLIW constraints: {msg}"

    # Run optimized (VLIW)
    opt_machine = VLIWMachine(initial_mem)
    opt_output = opt_machine.run_vliw(bundles)

    # Check functional correctness
    assert ref_output == opt_output, (
        f"Output mismatch for '{program['name']}':\n"
        f"  Reference: {ref_output}\n"
        f"  Optimized: {opt_output}"
    )

    # Check register budget
    num_regs = max_register(bundles)
    assert num_regs <= max_regs, (
        f"Register budget exceeded for '{program['name']}': "
        f"used {num_regs}, max {max_regs}"
    )

    # Check cycle budget
    num_cycles = len(bundles)
    assert num_cycles <= max_cycles, (
        f"Cycle budget exceeded for '{program['name']}': "
        f"{num_cycles} cycles, max {max_cycles}"
    )


def test_single_hash():
    """Test optimizer on single myhash kernel (35 instructions)."""
    program = _load_program('single_hash.vasm')
    _run_test(program)


def test_triple_hash():
    """Test optimizer on triple myhash kernel with ILP (101 instructions)."""
    program = _load_program('triple_hash.vasm')
    _run_test(program)


def test_pipeline_dag():
    """Test optimizer on diamond-DAG pipeline (41 instructions)."""
    program = _load_program('pipeline_dag.vasm')
    _run_test(program)
