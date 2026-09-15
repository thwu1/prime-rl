"""
Tests for the register allocator and x86-64 code generator.

Phase 1 — register allocation:
  For each test program, verify that after allocation:
    1. No virtual registers remain.
    2. All physical register indices are < NUM_PHYS_REGS.
    3. The emulator output matches the original program.
    4. No trivial MOV rx rx instructions exist.
    5. Spill-designated programs actually use stack slots.

Phase 2 — native x86-64 execution:
  For each test program, verify that:
    1. The code generator produces valid assembly.
    2. gcc successfully compiles and links it with runtime.c.
    3. The resulting binary produces output identical to the emulator.
"""


import os
import subprocess
import sys
import tempfile

sys.path.insert(0, '/app')

import pytest
from ir import is_vreg, is_preg, is_stack, NUM_PHYS_REGS
from emulator import emulate
from test_programs import get_all_programs


def _load_allocator():
    from regalloc import allocate_registers
    return allocate_registers


def _load_codegen():
    from codegen import generate_x86
    return generate_x86


@pytest.fixture(scope='session')
def allocator():
    return _load_allocator()


@pytest.fixture(scope='session')
def codegen():
    return _load_codegen()


_PROGRAMS = get_all_programs()

# ---------------------------------------------------------------------------
# Phase 1: register allocation correctness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('name,program', _PROGRAMS, ids=[n for n, _ in _PROGRAMS])
def test_correctness(name, program, allocator):
    expected = emulate(program)
    allocated = allocator(program)

    # No virtual registers should remain
    remaining = allocated.all_vregs()
    assert len(remaining) == 0, (
        f"[{name}] virtual registers remain after allocation: {remaining}"
    )

    # Physical register indices must be valid
    for label, instrs in allocated.blocks.items():
        for instr in instrs:
            for reg in instr.defs() | instr.uses():
                if is_preg(reg):
                    idx = int(reg[1:])
                    assert idx < NUM_PHYS_REGS, (
                        f"[{name}] invalid register {reg} "
                        f"(only r0-r{NUM_PHYS_REGS - 1} allowed)"
                    )

    # Emulator output must match
    actual = emulate(allocated)
    assert actual == expected, (
        f"[{name}] output mismatch: expected {expected}, got {actual}"
    )


@pytest.mark.parametrize('name,program', _PROGRAMS, ids=[n for n, _ in _PROGRAMS])
def test_no_trivial_moves(name, program, allocator):
    """After allocation, MOV rx rx should have been eliminated."""
    allocated = allocator(program)
    for label, instrs in allocated.blocks.items():
        for instr in instrs:
            if instr.op == 'MOV':
                assert instr.dst != instr.src1, (
                    f"[{name}] trivial move {instr} in block '{label}'"
                )


@pytest.mark.parametrize('name,program',
                         [p for p in _PROGRAMS if p[0].startswith('spill')],
                         ids=[n for n, _ in _PROGRAMS if n.startswith('spill')])
def test_spill_programs_use_stack(name, program, allocator):
    """Programs designed to exceed register count must actually spill."""
    allocated = allocator(program)
    has_stack = False
    for instrs in allocated.blocks.values():
        for instr in instrs:
            for reg in instr.defs() | instr.uses():
                if is_stack(reg):
                    has_stack = True
    assert has_stack, (
        f"[{name}] expected stack spills but none found - "
        f"only {NUM_PHYS_REGS} physical registers are available"
    )


# ---------------------------------------------------------------------------
# Phase 2: x86-64 native compilation and execution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('name,program', _PROGRAMS, ids=[n for n, _ in _PROGRAMS])
def test_native_compilation(name, program, allocator, codegen):
    """Assembly must compile and link with gcc without errors."""
    allocated = allocator(program)
    asm_code = codegen(allocated)

    asm_path = os.path.join(tempfile.gettempdir(), f'test_{name}.s')
    bin_path = os.path.join(tempfile.gettempdir(), f'test_{name}')

    with open(asm_path, 'w') as f:
        f.write(asm_code)

    result = subprocess.run(
        ['gcc', '-o', bin_path, asm_path, '/app/runtime.c', '-no-pie'],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"[{name}] gcc compilation failed:\n{result.stderr}"
    )


@pytest.mark.parametrize('name,program', _PROGRAMS, ids=[n for n, _ in _PROGRAMS])
def test_native_output(name, program, allocator, codegen):
    """Compiled binary must produce output identical to the emulator."""
    expected = emulate(program)
    allocated = allocator(program)
    asm_code = codegen(allocated)

    asm_path = os.path.join(tempfile.gettempdir(), f'run_{name}.s')
    bin_path = os.path.join(tempfile.gettempdir(), f'run_{name}')

    with open(asm_path, 'w') as f:
        f.write(asm_code)

    compile_res = subprocess.run(
        ['gcc', '-o', bin_path, asm_path, '/app/runtime.c', '-no-pie'],
        capture_output=True, text=True, timeout=30,
    )
    assert compile_res.returncode == 0, (
        f"[{name}] gcc compilation failed:\n{compile_res.stderr}"
    )

    run_res = subprocess.run(
        [bin_path], capture_output=True, text=True, timeout=10,
    )
    assert run_res.returncode == 0, (
        f"[{name}] binary exited with code {run_res.returncode}:\n"
        f"{run_res.stderr}"
    )

    actual_lines = run_res.stdout.strip().split('\n') if run_res.stdout.strip() else []
    actual = [int(x) for x in actual_lines]
    assert actual == expected, (
        f"[{name}] native output {actual} != emulator output {expected}"
    )


@pytest.mark.parametrize('name,program',
                         [p for p in _PROGRAMS if p[0].startswith('spill')],
                         ids=[n for n, _ in _PROGRAMS if n.startswith('spill')])
def test_native_spill_output(name, program, allocator, codegen):
    """Spill programs must work correctly in native execution too."""
    expected = emulate(program)
    allocated = allocator(program)

    # Confirm spills are present
    has_stack = any(
        is_stack(r)
        for instrs in allocated.blocks.values()
        for instr in instrs
        for r in instr.defs() | instr.uses()
    )
    assert has_stack, f"[{name}] no spills detected"

    asm_code = codegen(allocated)
    asm_path = os.path.join(tempfile.gettempdir(), f'spill_{name}.s')
    bin_path = os.path.join(tempfile.gettempdir(), f'spill_{name}')

    with open(asm_path, 'w') as f:
        f.write(asm_code)

    compile_res = subprocess.run(
        ['gcc', '-o', bin_path, asm_path, '/app/runtime.c', '-no-pie'],
        capture_output=True, text=True, timeout=30,
    )
    assert compile_res.returncode == 0, (
        f"[{name}] gcc compilation failed:\n{compile_res.stderr}"
    )

    run_res = subprocess.run(
        [bin_path], capture_output=True, text=True, timeout=10,
    )
    assert run_res.returncode == 0, (
        f"[{name}] spill binary crashed:\n{run_res.stderr}"
    )

    actual_lines = run_res.stdout.strip().split('\n') if run_res.stdout.strip() else []
    actual = [int(x) for x in actual_lines]
    assert actual == expected, (
        f"[{name}] spill native output {actual} != expected {expected}"
    )
