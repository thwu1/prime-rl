"""Tests for the register allocation pipeline.

Verifies allocator correctness at the Python/interpreter level AND
end-to-end by emitting GAS assembly, compiling with gcc, and running
the resulting binary.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, '/app')

import pytest
from ir import Var, Reg, Deref, Imm, Instr, X86Program, ALLOCATABLE
from interp import interp
from programs import test_cases, prog_spill, all_programs


# -----------------------------------------------------------------------
# Helper: compile and run an allocated program as a native binary
# -----------------------------------------------------------------------

def _compile_and_run(allocated, inputs=None):
    """Emit assembly, compile with gcc, run binary, return (returncode, stdout, stderr)."""
    from emitter import emit_program

    with tempfile.TemporaryDirectory() as tmpdir:
        asm_path = os.path.join(tmpdir, 'prog.s')
        bin_path = os.path.join(tmpdir, 'prog')

        emit_program(allocated, asm_path)

        gcc = subprocess.run(
            ['gcc', '-o', bin_path, asm_path, '/app/runtime.c', '-no-pie'],
            capture_output=True, text=True, timeout=30,
        )
        if gcc.returncode != 0:
            return gcc.returncode, '', gcc.stderr

        stdin_data = None
        if inputs:
            stdin_data = '\n'.join(str(x) for x in inputs) + '\n'

        run = subprocess.run(
            [bin_path],
            input=stdin_data,
            capture_output=True, text=True, timeout=10,
        )
        return run.returncode, run.stdout, run.stderr


# =======================================================================
# PYTHON-LEVEL TESTS (allocator correctness via interpreter)
# =======================================================================

@pytest.mark.parametrize("name,program,inputs,expected", test_cases,
                         ids=[t[0] for t in test_cases])
def test_correctness(name, program, inputs, expected):
    from allocator import allocate_registers
    allocated = allocate_registers(program)

    # 1. No Var should remain
    for label, instrs in allocated.blocks.items():
        for instr in instrs:
            for arg in instr.args:
                assert not isinstance(arg, Var), (
                    f"[{name}] Var({arg.name!r}) still present in "
                    f"block '{label}': {instr}"
                )

    # 2. Result must match
    result = interp(allocated, inputs)
    assert result == expected, (
        f"[{name}] Expected rax={expected}, got {result}"
    )


# -----------------------------------------------------------------------
# Spilling: 15 simultaneous variables MUST produce stack slots
# -----------------------------------------------------------------------

def test_spilling():
    from allocator import allocate_registers
    allocated = allocate_registers(prog_spill)

    has_stack_slot = False
    for instrs in allocated.blocks.values():
        for instr in instrs:
            for arg in instr.args:
                if isinstance(arg, Deref) and arg.reg == 'rbp':
                    has_stack_slot = True

    assert has_stack_slot, (
        "15 simultaneously-live variables require spilling, "
        "but no Deref('rbp', ...) found in output"
    )

    result = interp(allocated)
    assert result == 120, f"Spill program: expected 120, got {result}"


# -----------------------------------------------------------------------
# Stack alignment: stack_space must be a non-negative multiple of 16
# -----------------------------------------------------------------------

@pytest.mark.parametrize("name,program", all_programs,
                         ids=[p[0] for p in all_programs])
def test_stack_alignment(name, program):
    from allocator import allocate_registers
    allocated = allocate_registers(program)
    ss = allocated.stack_space
    assert ss >= 0, f"[{name}] Negative stack_space: {ss}"
    assert ss % 16 == 0, (
        f"[{name}] stack_space={ss} is not 16-byte aligned"
    )


# -----------------------------------------------------------------------
# No self-move: trivial movq %r, %r should be eliminated
# -----------------------------------------------------------------------

@pytest.mark.parametrize("name,program", all_programs,
                         ids=[p[0] for p in all_programs])
def test_no_trivial_moves(name, program):
    from allocator import allocate_registers
    allocated = allocate_registers(program)
    for label, instrs in allocated.blocks.items():
        for instr in instrs:
            if instr.op == 'movq' and len(instr.args) >= 2:
                src, dst = instr.args[0], instr.args[1]
                if isinstance(src, (Reg, Deref)) and src == dst:
                    pytest.fail(
                        f"[{name}] Trivial movq in block '{label}': "
                        f"{instr}"
                    )


# -----------------------------------------------------------------------
# Caller-saved survival: variable live across callq
# -----------------------------------------------------------------------

def test_caller_saved_correctness():
    from allocator import allocate_registers
    allocated = allocate_registers(
        X86Program({
            'start': [
                Instr('movq', [Imm(100), Var('saved')]),
                Instr('callq', ['read_int', 0]),
                Instr('movq', [Reg('rax'), Var('input_val')]),
                Instr('addq', [Var('saved'), Var('input_val')]),
                Instr('movq', [Var('input_val'), Reg('rax')]),
                Instr('jmp', ['conclusion']),
            ],
        })
    )
    assert interp(allocated, [7]) == 107
    assert interp(allocated, [0]) == 100
    assert interp(allocated, [-50]) == 50


# -----------------------------------------------------------------------
# Loop + call interaction
# -----------------------------------------------------------------------

_LOOP_CALL_PROG = X86Program({
    'start': [
        Instr('movq', [Imm(0), Var('total')]),
        Instr('movq', [Imm(0), Var('cnt')]),
        Instr('jmp', ['lt']),
    ],
    'lt': [
        Instr('cmpq', [Imm(3), Var('cnt')]),
        Instr('jl', ['lb']),
        Instr('jmp', ['ld']),
    ],
    'lb': [
        Instr('callq', ['read_int', 0]),
        Instr('addq', [Reg('rax'), Var('total')]),
        Instr('addq', [Imm(1), Var('cnt')]),
        Instr('jmp', ['lt']),
    ],
    'ld': [
        Instr('movq', [Var('total'), Reg('rax')]),
        Instr('jmp', ['conclusion']),
    ],
})


def test_call_in_loop():
    from allocator import allocate_registers
    allocated = allocate_registers(_LOOP_CALL_PROG)
    assert interp(allocated, [10, 20, 30]) == 60
    assert interp(allocated, [1, 2, 3]) == 6


# =======================================================================
# BINARY-LEVEL TESTS (emitter + gcc + execution)
# =======================================================================

@pytest.mark.parametrize("name,program,inputs,expected", test_cases,
                         ids=[t[0] for t in test_cases])
def test_binary_execution(name, program, inputs, expected):
    """Emit GAS assembly, compile with gcc, run the binary, check output."""
    from allocator import allocate_registers
    allocated = allocate_registers(program)

    rc, stdout, stderr = _compile_and_run(allocated, inputs)
    assert rc == 0, (
        f"[{name}] Binary failed (rc={rc}):\n{stderr}"
    )
    actual = int(stdout.strip())
    assert actual == expected, (
        f"[{name}] Binary output {actual}, expected {expected}"
    )


def test_binary_call_in_loop():
    """End-to-end binary test for loop-with-callq program."""
    from allocator import allocate_registers
    allocated = allocate_registers(_LOOP_CALL_PROG)

    rc, stdout, stderr = _compile_and_run(allocated, [10, 20, 30])
    assert rc == 0, f"Binary failed (rc={rc}):\n{stderr}"
    assert int(stdout.strip()) == 60

    rc, stdout, stderr = _compile_and_run(allocated, [1, 2, 3])
    assert rc == 0, f"Binary failed (rc={rc}):\n{stderr}"
    assert int(stdout.strip()) == 6


def test_binary_spill():
    """Verify the 15-variable spill program works as a compiled binary."""
    from allocator import allocate_registers
    allocated = allocate_registers(prog_spill)

    rc, stdout, stderr = _compile_and_run(allocated)
    assert rc == 0, f"Spill binary failed (rc={rc}):\n{stderr}"
    assert int(stdout.strip()) == 120


def test_emitter_produces_valid_assembly():
    """Verify emitter output is syntactically valid (assembles without error)."""
    from allocator import allocate_registers
    from emitter import emit_program

    allocated = allocate_registers(prog_spill)

    with tempfile.TemporaryDirectory() as tmpdir:
        asm_path = os.path.join(tmpdir, 'check.s')
        obj_path = os.path.join(tmpdir, 'check.o')
        emit_program(allocated, asm_path)

        # Assemble only (no link) to verify syntax
        result = subprocess.run(
            ['gcc', '-c', '-o', obj_path, asm_path],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, (
            f"Assembly syntax error:\n{result.stderr}"
        )
