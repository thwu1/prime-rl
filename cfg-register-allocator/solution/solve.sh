#!/bin/bash

# Deploy the register allocator and assembly emitter
cp /solution/solver.py /app/allocator.py
cp /solution/emitter_solution.py /app/emitter.py

# Quick sanity check: allocate, emit, compile, and run a simple program
cd /app
python3 -c "
import sys
sys.path.insert(0, '/app')
from allocator import allocate_registers
from emitter import emit_program
from programs import test_cases, prog_spill
from interp import interp
from ir import Var, Deref

# Verify all test cases via interpreter
for name, prog, inputs, expected in test_cases:
    allocated = allocate_registers(prog)
    for label, instrs in allocated.blocks.items():
        for instr in instrs:
            for arg in instr.args:
                assert not isinstance(arg, Var), f'{name}: Var {arg} remains'
    result = interp(allocated, inputs)
    assert result == expected, f'{name}: expected {expected}, got {result}'
    assert allocated.stack_space % 16 == 0, f'{name}: misaligned stack'

# Verify spilling
alloc = allocate_registers(prog_spill)
has_spill = any(
    isinstance(arg, Deref) and arg.reg == 'rbp'
    for instrs in alloc.blocks.values()
    for instr in instrs
    for arg in instr.args
)
assert has_spill, 'No spilling detected for 15-variable program'

# Verify end-to-end binary compilation
import subprocess, tempfile, os
allocated = allocate_registers(test_cases[0][1])  # prog_simple
with tempfile.TemporaryDirectory() as tmpdir:
    asm = os.path.join(tmpdir, 'test.s')
    binary = os.path.join(tmpdir, 'test')
    emit_program(allocated, asm)
    r = subprocess.run(['gcc', '-o', binary, asm, '/app/runtime.c', '-no-pie'],
                       capture_output=True, text=True)
    assert r.returncode == 0, f'gcc failed: {r.stderr}'
    r = subprocess.run([binary], capture_output=True, text=True, timeout=5)
    assert r.returncode == 0 and int(r.stdout.strip()) == 42, f'Binary output wrong: {r.stdout}'

print('All solution verifications passed')
"
