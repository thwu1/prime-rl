
"""
Tests for the x86-64 compilation backend.
Three-tier verification:
  1. Emulator correctness: run allocated programs through Python emulator
  2. Structural constraints: x86 validity of allocated IR
  3. Binary execution: compile to real x86-64, link with C runtime, run
"""

import sys
import os
import subprocess
import tempfile

for p in ['/opt/task_lib', '/app']:
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
from programs import PROGRAMS
from emulator import Emulator


# ---- Helpers ----

def _run_emulator(prog_name):
    """Allocate and emulate a program, returning ((rax, output), allocated)."""
    from allocator import allocate_registers
    prog = PROGRAMS[prog_name]
    allocated = allocate_registers(prog)
    emu = Emulator()
    return emu.run(allocated), allocated


def _compile_and_run(prog_name):
    """Allocate, emit assembly, compile with gcc, run binary.
    Returns (return_value, printed_output_list)."""
    from allocator import allocate_registers
    from emit import emit_x86
    prog = PROGRAMS[prog_name]
    allocated = allocate_registers(prog)
    asm_text = emit_x86(allocated)

    with tempfile.TemporaryDirectory() as tmpdir:
        asm_path = os.path.join(tmpdir, f"{prog_name}.s")
        bin_path = os.path.join(tmpdir, prog_name)

        with open(asm_path, 'w') as f:
            f.write(asm_text)

        # Compile
        runtime_path = '/app/runtime.c'
        if not os.path.exists(runtime_path):
            runtime_path = '/opt/task_lib/runtime.c'
        comp = subprocess.run(
            ['gcc', '-no-pie', '-o', bin_path, asm_path, runtime_path],
            capture_output=True, text=True, timeout=30
        )
        assert comp.returncode == 0, (
            f"GCC compilation failed for '{prog_name}':\n{comp.stderr}"
        )

        # Run
        run = subprocess.run(
            [bin_path], capture_output=True, text=True, timeout=10
        )
        assert run.returncode == 0, (
            f"Binary crashed for '{prog_name}' (exit {run.returncode}):\n"
            f"stdout: {run.stdout}\nstderr: {run.stderr}"
        )

        # Parse output
        raw_lines = run.stdout.strip().split('\n') if run.stdout.strip() else []
        retval_lines = [l for l in raw_lines if l.startswith('RETVAL:')]
        output_lines = [l for l in raw_lines if not l.startswith('RETVAL:') and l.strip()]

        assert len(retval_lines) == 1, (
            f"Expected exactly one RETVAL line for '{prog_name}', "
            f"got {len(retval_lines)}. Full stdout:\n{run.stdout}"
        )
        rax = int(retval_lines[0].split(':')[1])
        printed = [int(l) for l in output_lines]
        return rax, printed


# ---- Tier 1: Emulator correctness ----

class TestEmulatorCorrectness:

    def test_simple_arith(self):
        (rax, out), _ = _run_emulator("simple_arith")
        assert rax == 42, f"Expected rax=42, got {rax}"
        assert out == []

    def test_branches(self):
        (rax, out), _ = _run_emulator("branches")
        assert rax == 10, f"Expected rax=10, got {rax}"
        assert out == []

    def test_loop(self):
        (rax, out), _ = _run_emulator("loop")
        assert rax == 55, f"Expected rax=55, got {rax}"
        assert out == []

    def test_fibonacci(self):
        (rax, out), _ = _run_emulator("fibonacci")
        assert rax == 144, f"Expected rax=144, got {rax}"
        assert out == []

    def test_many_vars(self):
        (rax, out), _ = _run_emulator("many_vars")
        assert rax == 120, f"Expected rax=120, got {rax}"
        assert out == []

    def test_nested_loops(self):
        (rax, out), _ = _run_emulator("nested_loops")
        assert rax == 80, f"Expected rax=80, got {rax}"
        assert out == []

    def test_with_calls(self):
        (rax, out), _ = _run_emulator("with_calls")
        assert rax == 14, f"Expected rax=14, got {rax}"
        assert out == [3, 13], f"Expected output [3, 13], got {out}"


# ---- Tier 2: Structural x86 constraints ----

class TestStructural:

    def _get_all_allocated(self):
        from allocator import allocate_registers
        results = {}
        for name, prog in PROGRAMS.items():
            results[name] = allocate_registers(prog)
        return results

    def test_no_remaining_variables(self):
        """All ('var', name) arguments must be replaced."""
        for name, allocated in self._get_all_allocated().items():
            for label, instrs in allocated['blocks'].items():
                for instr in instrs:
                    for arg in instr[1:]:
                        if isinstance(arg, tuple) and len(arg) >= 2 and arg[0] == 'var':
                            pytest.fail(
                                f"Unallocated variable '{arg[1]}' in "
                                f"program '{name}', block '{label}': {instr}"
                            )

    def test_no_two_memory_operands(self):
        """No binary instruction may have two memory (deref) operands."""
        binary_ops = {'movq', 'addq', 'subq', 'xorq', 'cmpq', 'movzbq'}
        for name, allocated in self._get_all_allocated().items():
            for label, instrs in allocated['blocks'].items():
                for instr in instrs:
                    op = instr[0]
                    if op in binary_ops and len(instr) == 3:
                        src_mem = isinstance(instr[1], tuple) and instr[1][0] == 'deref'
                        dst_mem = isinstance(instr[2], tuple) and instr[2][0] == 'deref'
                        if src_mem and dst_mem:
                            pytest.fail(
                                f"Two memory operands in program '{name}', "
                                f"block '{label}': {instr}"
                            )

    def test_valid_registers_only(self):
        """All register arguments must be valid x86-64 register names."""
        valid_regs = {
            'rax', 'rbx', 'rcx', 'rdx', 'rsi', 'rdi', 'rsp', 'rbp',
            'r8', 'r9', 'r10', 'r11', 'r12', 'r13', 'r14', 'r15',
            'al', 'bl', 'cl', 'dl',
        }
        for name, allocated in self._get_all_allocated().items():
            for label, instrs in allocated['blocks'].items():
                for instr in instrs:
                    for arg in instr[1:]:
                        if isinstance(arg, tuple) and arg[0] == 'reg':
                            assert arg[1] in valid_regs, (
                                f"Invalid register '{arg[1]}' in program "
                                f"'{name}', block '{label}': {instr}"
                            )
                        elif isinstance(arg, tuple) and arg[0] == 'deref':
                            assert arg[1] in valid_regs, (
                                f"Invalid base register '{arg[1]}' in deref "
                                f"in program '{name}', block '{label}': {instr}"
                            )


# ---- Tier 3: Binary execution via GCC ----

class TestBinaryExecution:

    def test_simple_arith_binary(self):
        rax, out = _compile_and_run("simple_arith")
        assert rax == 42, f"Expected rax=42, got {rax}"
        assert out == []

    def test_branches_binary(self):
        rax, out = _compile_and_run("branches")
        assert rax == 10, f"Expected rax=10, got {rax}"
        assert out == []

    def test_loop_binary(self):
        rax, out = _compile_and_run("loop")
        assert rax == 55, f"Expected rax=55, got {rax}"
        assert out == []

    def test_fibonacci_binary(self):
        rax, out = _compile_and_run("fibonacci")
        assert rax == 144, f"Expected rax=144, got {rax}"
        assert out == []

    def test_many_vars_binary(self):
        rax, out = _compile_and_run("many_vars")
        assert rax == 120, f"Expected rax=120, got {rax}"
        assert out == []

    def test_nested_loops_binary(self):
        rax, out = _compile_and_run("nested_loops")
        assert rax == 80, f"Expected rax=80, got {rax}"
        assert out == []

    def test_with_calls_binary(self):
        rax, out = _compile_and_run("with_calls")
        assert rax == 14, f"Expected rax=14, got {rax}"
        assert out == [3, 13]
