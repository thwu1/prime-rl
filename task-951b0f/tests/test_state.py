"""Tests for the register allocator and assembly emitter.

Each test builds a CFG with virtual registers, runs allocate_registers,
and verifies that (a) no VRegs remain and (b) the executor produces the
same output as the original virtual-register version.  Native execution
tests additionally compile the emitted assembly with gcc, run the binary,
and check its output.

"""
import os
import sys
import subprocess
import tempfile

sys.path.insert(0, '/app')

import pytest
from ir import VReg, PReg, Deref, CFG
from executor import Executor
from programs import (
    program_simple,
    program_arithmetic,
    program_conditional,
    program_loop,
    program_nested_conditional,
    program_pressure,
    program_loop_multi,
    program_three_calls,
)
from allocator import allocate_registers
from emitter import emit_x86


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _has_vregs(cfg: CFG) -> bool:
    """True if any VReg operand remains in *cfg*."""
    for block in cfg.blocks.values():
        for instr in block.instrs:
            for arg in instr.args:
                if isinstance(arg, VReg):
                    return True
    return False


def _verify_interp(name: str, cfg, inputs, expected):
    """Run *cfg* through allocator, check no VRegs and correct output."""
    orig_out = Executor(cfg, inputs).run()
    assert orig_out == expected, (
        f"{name}: original program wrong: {orig_out} != {expected}"
    )

    allocated = allocate_registers(cfg)

    assert not _has_vregs(allocated), (
        f"{name}: VRegs remain after allocation"
    )

    alloc_out = Executor(allocated, inputs).run()
    assert alloc_out == expected, (
        f"{name}: allocated program output {alloc_out} != {expected}"
    )
    return allocated


def _verify_native(name: str, cfg, inputs, expected):
    """Run allocator + emitter + gcc, execute the binary, check output."""
    allocated = allocate_registers(cfg)
    assert not _has_vregs(allocated), f"{name}: VRegs remain after allocation"

    asm_src = emit_x86(allocated)
    assert isinstance(asm_src, str) and len(asm_src) > 0, (
        f"{name}: emit_x86 returned empty or non-string"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        asm_path = os.path.join(tmpdir, 'prog.s')
        exe_path = os.path.join(tmpdir, 'prog')

        with open(asm_path, 'w') as f:
            f.write(asm_src)

        comp = subprocess.run(
            ['gcc', '-o', exe_path, asm_path, '/app/runtime.c', '-no-pie'],
            capture_output=True, text=True,
        )
        assert comp.returncode == 0, (
            f"{name}: gcc compilation failed:\n{comp.stderr}"
        )

        input_str = '\n'.join(str(x) for x in inputs) + '\n' if inputs else ''
        run = subprocess.run(
            [exe_path],
            input=input_str, capture_output=True, text=True, timeout=10,
        )
        assert run.returncode == 0, (
            f"{name}: binary exited with code {run.returncode}:\n{run.stderr}"
        )

        output = [int(x) for x in run.stdout.strip().split('\n') if x.strip()]
        assert output == expected, (
            f"{name}: native output {output} != {expected}"
        )


# ---------------------------------------------------------------------------
# Interpreter tests  (allocator correctness)
# ---------------------------------------------------------------------------

class TestAllocatorInterpreter:
    def test_simple(self):
        cfg, inp, exp = program_simple()
        _verify_interp("simple", cfg, inp, exp)

    def test_arithmetic(self):
        cfg, inp, exp = program_arithmetic()
        _verify_interp("arithmetic", cfg, inp, exp)

    def test_conditional(self):
        cfg, inp, exp = program_conditional()
        _verify_interp("conditional", cfg, inp, exp)

    def test_loop(self):
        cfg, inp, exp = program_loop()
        _verify_interp("loop", cfg, inp, exp)

    def test_nested_conditional(self):
        cfg, inp, exp = program_nested_conditional()
        _verify_interp("nested_conditional", cfg, inp, exp)

    def test_register_pressure(self):
        cfg, inp, exp = program_pressure()
        _verify_interp("pressure", cfg, inp, exp)

    def test_loop_multi(self):
        cfg, inp, exp = program_loop_multi()
        _verify_interp("loop_multi", cfg, inp, exp)

    def test_three_calls(self):
        cfg, inp, exp = program_three_calls()
        _verify_interp("three_calls", cfg, inp, exp)

    # Edge-case inputs on existing programs
    def test_conditional_negative(self):
        cfg, _, _ = program_conditional()
        allocated = allocate_registers(cfg)
        out = Executor(allocated, [-3]).run()
        assert out == [3], f"conditional(-3): {out}"

    def test_conditional_zero(self):
        cfg, _, _ = program_conditional()
        allocated = allocate_registers(cfg)
        out = Executor(allocated, [0]).run()
        assert out == [0], f"conditional(0): {out}"

    def test_loop_zero(self):
        cfg, _, _ = program_loop()
        allocated = allocate_registers(cfg)
        out = Executor(allocated, [0]).run()
        assert out == [0], f"loop(0): {out}"

    def test_loop_large(self):
        cfg, _, _ = program_loop()
        allocated = allocate_registers(cfg)
        out = Executor(allocated, [100]).run()
        assert out == [4950], f"loop(100): {out}"


# ---------------------------------------------------------------------------
# Native execution tests  (allocator + emitter end-to-end)
# ---------------------------------------------------------------------------

class TestNativeExecution:
    def test_native_simple(self):
        cfg, inp, exp = program_simple()
        _verify_native("native_simple", cfg, inp, exp)

    def test_native_arithmetic(self):
        cfg, inp, exp = program_arithmetic()
        _verify_native("native_arithmetic", cfg, inp, exp)

    def test_native_conditional(self):
        cfg, inp, exp = program_conditional()
        _verify_native("native_conditional", cfg, inp, exp)

    def test_native_loop(self):
        cfg, inp, exp = program_loop()
        _verify_native("native_loop", cfg, inp, exp)

    def test_native_nested(self):
        cfg, inp, exp = program_nested_conditional()
        _verify_native("native_nested", cfg, inp, exp)

    def test_native_pressure(self):
        cfg, inp, exp = program_pressure()
        _verify_native("native_pressure", cfg, inp, exp)

    def test_native_loop_multi(self):
        cfg, inp, exp = program_loop_multi()
        _verify_native("native_loop_multi", cfg, inp, exp)

    def test_native_three_calls(self):
        cfg, inp, exp = program_three_calls()
        _verify_native("native_three_calls", cfg, inp, exp)

    # Edge cases via native execution
    def test_native_conditional_negative(self):
        cfg, _, _ = program_conditional()
        _verify_native("native_cond_neg", cfg, [-3], [3])

    def test_native_loop_zero(self):
        cfg, _, _ = program_loop()
        _verify_native("native_loop_zero", cfg, [0], [0])

    def test_native_loop_large(self):
        cfg, _, _ = program_loop()
        _verify_native("native_loop_100", cfg, [100], [4950])
