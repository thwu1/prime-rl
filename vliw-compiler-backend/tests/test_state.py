
"""
Tests for the VLIW optimizer.

Part 1 — Function-based tests:
  For each program, call optimize() directly, validate bundles,
  simulate on the VLIW machine, compare memory, check cycle count.

Part 2 — CLI pipeline tests:
  Compile the C bundle validator, run the optimizer CLI to produce
  .vliw files, validate with the compiled binary, and compare
  simulation output via machine.py compare.
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, "/app")

from machine import VLIWMachine, reference_run, validate_bundles, MASK32
from programs import PROGRAMS
from optimizer import optimize


# ================================================================
# Part 1: Function-based correctness tests
# ================================================================

def _run_program_test(prog):
    name = prog["name"]
    instructions = prog["instructions"]
    num_regs = prog["num_regs"]
    initial_mem = prog.get("initial_mem", {})
    check_addrs = prog["check_addrs"]
    target_cycles = prog["target_cycles"]
    mem_size = 4096

    # 1. Reference execution
    ref_mem = reference_run(instructions, initial_mem=initial_mem,
                            mem_size=mem_size)

    # 2. Optimize
    bundles = optimize(instructions, num_regs, mem_size)

    # 3. Basic validation
    assert isinstance(bundles, list), f"[{name}] optimize() must return a list"
    assert len(bundles) > 0, f"[{name}] optimize() returned empty bundle list"
    for i, b in enumerate(bundles):
        assert isinstance(b, dict), f"[{name}] bundle {i} must be a dict"
        for key in ("SLOT_A", "SLOT_B", "SLOT_M"):
            assert key in b, f"[{name}] bundle {i} missing key {key}"

    # Structural validation (slot assignments, register ranges, WAW)
    validate_bundles(bundles, num_regs)

    # 4. Execute on VLIW machine
    machine = VLIWMachine(num_regs=num_regs, mem_size=mem_size)
    for addr, val in initial_mem.items():
        machine.mem[int(addr)] = val & MASK32

    cycle_count = machine.run(bundles)

    # 5. Check correctness
    for addr in check_addrs:
        actual = machine.mem[addr]
        expected = ref_mem[addr]
        assert actual == expected, (
            f"[{name}] Memory mismatch at addr {addr}: "
            f"got {actual:#010x}, expected {expected:#010x}"
        )

    # 6. Check cycle count
    assert cycle_count <= target_cycles, (
        f"[{name}] Too many cycles: {cycle_count} > target {target_cycles}"
    )


def test_basic_arith():
    _run_program_test(PROGRAMS[0])


def test_hash_compute():
    _run_program_test(PROGRAMS[1])


def test_poly_batch():
    _run_program_test(PROGRAMS[2])


def test_tree_walk():
    _run_program_test(PROGRAMS[3])


def test_matmul_2x2():
    _run_program_test(PROGRAMS[4])


# ================================================================
# Part 2: CLI pipeline tests (tool interoperability)
# ================================================================

def _ensure_toolchain_built():
    """Compile the C bundle validator if not already built."""
    if not os.path.isfile("/app/bundle_check"):
        result = subprocess.run(
            ["make", "-C", "/app", "build"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"Toolchain build failed (gcc/make):\n{result.stderr}"
        )


def _run_cli_pipeline(prog):
    """Full CLI pipeline: optimizer CLI -> bundle_check -> machine.py compare."""
    _ensure_toolchain_built()

    name = prog["name"]
    vliw_path = f"/tmp/test_{name}.vliw"

    # Step 1: Run optimizer CLI to produce .vliw output
    result = subprocess.run(
        ["python3", "/app/optimizer.py", name],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"[{name}] Optimizer CLI failed (exit {result.returncode}):\n"
        f"{result.stderr}"
    )
    assert len(result.stdout.strip()) > 0, (
        f"[{name}] Optimizer CLI produced empty output"
    )
    with open(vliw_path, "w") as f:
        f.write(result.stdout)

    # Step 2: Run compiled C bundle validator
    result = subprocess.run(
        ["/app/bundle_check", vliw_path],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, (
        f"[{name}] C bundle validator failed:\n{result.stderr}\n{result.stdout}"
    )

    # Step 3: Run machine.py compare (simulation + reference comparison)
    result = subprocess.run(
        ["python3", "/app/machine.py", "compare", vliw_path, name],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"[{name}] Simulation comparison failed:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "PASS" in result.stdout, (
        f"[{name}] Comparison did not report PASS:\n{result.stdout}"
    )


def test_cli_basic_arith():
    _run_cli_pipeline(PROGRAMS[0])


def test_cli_hash_compute():
    _run_cli_pipeline(PROGRAMS[1])


def test_cli_poly_batch():
    _run_cli_pipeline(PROGRAMS[2])


def test_cli_tree_walk():
    _run_cli_pipeline(PROGRAMS[3])


def test_cli_matmul_2x2():
    _run_cli_pipeline(PROGRAMS[4])
