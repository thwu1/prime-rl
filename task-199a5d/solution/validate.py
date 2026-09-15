
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, '/app')

from regalloc import allocate_registers
from codegen import generate_x86
from test_programs import get_all_programs
from emulator import emulate
from ir import is_vreg, is_preg, is_stack, NUM_PHYS_REGS

print("=== Phase 1: register allocation (emulator) ===")
for name, prog in get_all_programs():
    expected = emulate(prog)
    allocated = allocate_registers(prog)

    remaining = allocated.all_vregs()
    assert len(remaining) == 0, f"{name}: vregs remain: {remaining}"

    for label, instrs in allocated.blocks.items():
        for instr in instrs:
            for reg in instr.defs() | instr.uses():
                if is_preg(reg):
                    assert int(reg[1:]) < NUM_PHYS_REGS, f"bad reg {reg}"

    actual = emulate(allocated)
    assert actual == expected, f"{name}: expected {expected}, got {actual}"

    spills = any(
        is_stack(r)
        for instrs in allocated.blocks.values()
        for instr in instrs
        for r in instr.defs() | instr.uses()
    )
    if name.startswith('spill'):
        assert spills, f"{name}: should spill but didn't"

    print(f"  {name}: PASS (spills={'yes' if spills else 'no'})")

print("\n=== Phase 2: native x86-64 compilation and execution ===")
for name, prog in get_all_programs():
    expected = emulate(prog)
    allocated = allocate_registers(prog)
    asm_code = generate_x86(allocated)

    asm_path = os.path.join(tempfile.gettempdir(), f'val_{name}.s')
    bin_path = os.path.join(tempfile.gettempdir(), f'val_{name}')

    with open(asm_path, 'w') as f:
        f.write(asm_code)

    compile_res = subprocess.run(
        ['gcc', '-o', bin_path, asm_path, '/app/runtime.c', '-no-pie'],
        capture_output=True, text=True, timeout=30,
    )
    assert compile_res.returncode == 0, (
        f"{name}: gcc failed:\n{compile_res.stderr}"
    )

    run_res = subprocess.run(
        [bin_path], capture_output=True, text=True, timeout=10,
    )
    assert run_res.returncode == 0, (
        f"{name}: binary exited {run_res.returncode}:\n{run_res.stderr}"
    )

    actual_lines = run_res.stdout.strip().split('\n') if run_res.stdout.strip() else []
    actual = [int(x) for x in actual_lines]
    assert actual == expected, (
        f"{name}: native output {actual} != expected {expected}"
    )
    print(f"  {name}: PASS (native)")

print("\nAll programs verified (emulator + native).")
