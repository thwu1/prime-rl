"""Verification tests for the x86 compiler backend.


Tests verify:
  1. Allocated programs contain no Variable nodes.
  2. No instruction has two Deref (memory) operands.
  3. Emulator output matches before/after allocation.
  4. Emitted assembly compiles via gcc and runs correctly as a native binary.
"""

import copy
import os
import subprocess
import sys

import pytest

sys.path.insert(0, '/app')

from x86_ast import Variable, Instr, Callq, Jump, JumpIf, Deref
from emulator import X86Emulator
import programs


# ── helpers ───────────────────────────────────────────────────────────

def _has_variables(program):
    """Return True if any instruction operand is a Variable."""
    for label, instrs in program.body.items():
        for node in instrs:
            if isinstance(node, Instr):
                for a in node.args:
                    if isinstance(a, Variable):
                        return True
    return False


def _get_program(name):
    return dict(programs.ALL_PROGRAMS)[name]


# ── parameterised tests ──────────────────────────────────────────────

PROGRAM_NAMES = [name for name, _ in programs.ALL_PROGRAMS]


@pytest.mark.parametrize('name', PROGRAM_NAMES)
def test_allocation_correctness(name):
    """Allocated program must produce identical emulator output."""
    from allocator import allocate_registers

    prog = copy.deepcopy(_get_program(name))

    # Expected output from the original (un-allocated) program
    emu_orig = X86Emulator()
    expected_rax, expected_output = emu_orig.run(prog)

    # Run the allocator
    allocated = allocate_registers(copy.deepcopy(_get_program(name)))

    # Structural check: no Variables should remain
    assert not _has_variables(allocated), (
        f'Program "{name}" still contains Variable nodes after allocation'
    )

    # Functional check: emulator output must match
    emu_alloc = X86Emulator()
    actual_rax, actual_output = emu_alloc.run(allocated)

    assert actual_rax == expected_rax, (
        f'[{name}] rax mismatch: expected {expected_rax}, got {actual_rax}'
    )
    assert actual_output == expected_output, (
        f'[{name}] output mismatch: expected {expected_output}, '
        f'got {actual_output}'
    )


@pytest.mark.parametrize('name', PROGRAM_NAMES)
def test_no_mem_to_mem(name):
    """After allocation no instruction should have two Deref operands."""
    from allocator import allocate_registers

    allocated = allocate_registers(copy.deepcopy(_get_program(name)))

    for label, instrs in allocated.body.items():
        for node in instrs:
            if isinstance(node, Instr) and len(node.args) == 2:
                a, b = node.args
                assert not (isinstance(a, Deref) and isinstance(b, Deref)), (
                    f'[{name}] mem-to-mem in block {label}: {node}'
                )


@pytest.mark.parametrize('name', PROGRAM_NAMES)
def test_native_execution(name):
    """Emitted assembly must compile and run correctly as a native binary."""
    from allocator import allocate_registers
    from codegen import emit_x86

    prog = copy.deepcopy(_get_program(name))

    # Expected output from emulator
    emu = X86Emulator()
    expected_rax, expected_output = emu.run(prog)

    # Allocate and emit assembly
    allocated = allocate_registers(copy.deepcopy(_get_program(name)))
    asm_text = emit_x86(allocated)

    asm_path = f'/tmp/tbtest_{name}.s'
    exe_path = f'/tmp/tbtest_{name}'

    try:
        with open(asm_path, 'w') as f:
            f.write(asm_text)

        # Compile with gcc
        comp = subprocess.run(
            ['gcc', '-no-pie', '-o', exe_path, asm_path, '/app/runtime.c'],
            capture_output=True, text=True, timeout=30,
        )
        assert comp.returncode == 0, (
            f'[{name}] gcc compilation failed:\n{comp.stderr}'
        )

        # Execute the native binary
        run = subprocess.run(
            [exe_path], capture_output=True, text=True, timeout=10,
        )
        assert run.returncode == 0, (
            f'[{name}] binary exited with code {run.returncode}\n'
            f'stdout: {run.stdout}\nstderr: {run.stderr}'
        )

        # Parse output: lines are either print_int output or RETVAL:<n>
        raw_lines = [l for l in run.stdout.strip().split('\n') if l.strip()]
        retval_lines = [l for l in raw_lines if l.startswith('RETVAL:')]
        output_lines = [l for l in raw_lines if not l.startswith('RETVAL:')]

        assert len(retval_lines) == 1, (
            f'[{name}] expected exactly one RETVAL line, got: {retval_lines}'
        )

        actual_rax = int(retval_lines[0].split(':')[1])
        actual_output = [int(l) for l in output_lines]

        assert actual_rax == expected_rax, (
            f'[{name}] native rax mismatch: expected {expected_rax}, '
            f'got {actual_rax}'
        )
        assert actual_output == expected_output, (
            f'[{name}] native output mismatch: expected {expected_output}, '
            f'got {actual_output}'
        )
    finally:
        for p in [asm_path, exe_path]:
            if os.path.exists(p):
                os.unlink(p)
