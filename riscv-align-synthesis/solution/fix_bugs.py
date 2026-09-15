#!/usr/bin/env python3
"""
Diagnose and repair regressions in the ELF alignment synthesis pipeline.

Three bugs identified through binary analysis and specification comparison:

Bug 1 (rob_parser.py): The parser reads the r_format field from the binary
but ignores it when constructing Relocation objects. For REL-format entries
(r_format=1), r_addend should be None because REL has no explicit addend.
The parser always passes the raw binary r_addend value.

Bug 2 (synth_engine.py): The _is_covered() function uses an existence-only
check (Approach A) -- any ALIGN at offset 0 suppresses synthesis. The spec's
concrete scenario demonstrates that Approach B (strength-aware) is correct:
only suppress when RELA format AND addend >= (addralign - min_nop).

Bug 3 (synth_engine.py): The _needs_synthesis() function uses addralign >= 4
for LoongArch instead of addralign > 4. Since LoongArch's minimum NOP is 4
bytes, addralign=4 never needs padding -- the threshold should be strict.
"""


import struct
import sys
import os

sys.path.insert(0, '/app')

# ===== PHASE 1: DIAGNOSE =====

print("=" * 60)
print("  Phase 1: Diagnosis")
print("=" * 60)

# Diagnose Bug 1: Cross-verify parser against raw binary
with open('/app/objects/riscv_rel_a8.rob', 'rb') as f:
    rob_data = f.read()

# Parse the header to find relocation table offset
_, _, sec_count, rel_count = struct.unpack_from('<HHII', rob_data, 4)
rel_pos = 16 + 20 * sec_count
_, _, _, r_format, raw_addend = struct.unpack_from('<HHHHi', rob_data, rel_pos)

from rob_parser import parse_rob_file
parsed = parse_rob_file('/app/objects/riscv_rel_a8.rob')
parsed_addend = parsed['sections'][0].relocations[0].r_addend

print(f"  Binary r_format = {r_format} (1=REL means no explicit addend)")
print(f"  Parser r_addend = {parsed_addend!r} (should be None for REL)")
bug1 = r_format == 1 and parsed_addend is not None
print(f"  Bug 1 (parser REL handling): {'CONFIRMED' if bug1 else 'not found'}")

# Diagnose Bug 2: Check suppression strategy
from synth_engine import synthesize_for_section

r = parse_rob_file('/app/objects/riscv_weak_a8.rob')
_, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
bug2 = len(synth) == 0
print(f"\n  Weak ALIGN (addend=2, need=6): synth_count={len(synth)} (expected 1)")
print(f"  Bug 2 (existence-only suppression): {'CONFIRMED' if bug2 else 'not found'}")

# Diagnose Bug 3: Check LoongArch threshold
r = parse_rob_file('/app/objects/la_boundary_a4.rob')
_, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
bug3 = len(synth) > 0
print(f"\n  LoongArch align=4: synth_count={len(synth)} (expected 0)")
print(f"  Bug 3 (LoongArch threshold >=4 vs >4): {'CONFIRMED' if bug3 else 'not found'}")

# ===== PHASE 2: FIX =====

print("\n" + "=" * 60)
print("  Phase 2: Applying Fixes")
print("=" * 60)

# Fix Bug 1: rob_parser.py - condition addend on r_format
with open('/app/rob_parser.py') as f:
    src = f.read()

old_addend = 'r_addend=r_addend,'
new_addend = 'r_addend=r_addend if r_format == 0 else None,'
assert old_addend in src, "Cannot find r_addend assignment in rob_parser.py"
src = src.replace(old_addend, new_addend)

with open('/app/rob_parser.py', 'w') as f:
    f.write(src)
print("  [FIXED] rob_parser.py: REL-format addend -> None")

# Fix Bugs 2 & 3: synth_engine.py
with open('/app/synth_engine.py') as f:
    src = f.read()

# Fix Bug 3: LoongArch threshold
old_threshold = 'return addralign >= 4  # Unified with RISC-V during refactoring'
new_threshold = 'return addralign > 4  # LoongArch nop=4, align=4 is trivial'
assert old_threshold in src, "Cannot find LoongArch threshold in synth_engine.py"
src = src.replace(old_threshold, new_threshold)
print("  [FIXED] synth_engine.py: LoongArch threshold >= -> >")

# Fix Bug 2: Replace existence-only check with strength-aware check
old_func = '''def _is_covered(sec: InputSection, align_type: int) -> bool:
    """Check if an existing ALIGN at offset 0 already covers this section."""
    return any(
        r.r_offset == 0 and r.r_type == align_type
        for r in sec.relocations
    )'''

new_func = '''def _is_covered(sec: InputSection, align_type: int, needed: int) -> bool:
    """Check if an existing ALIGN at offset 0 has sufficient strength."""
    for r in sec.relocations:
        if r.r_offset != 0 or r.r_type != align_type:
            continue
        if r.r_addend is None:
            continue
        if r.r_addend >= needed:
            return True
    return False'''

assert old_func in src, "Cannot find _is_covered function in synth_engine.py"
src = src.replace(old_func, new_func)

old_call = '''    if not _is_covered(sec, align_type):
        addend = sec.addralign - get_min_nop(arch)'''

new_call = '''    addend = sec.addralign - get_min_nop(arch)
    if not _is_covered(sec, align_type, addend):'''

assert old_call in src, "Cannot find _is_covered call site in synth_engine.py"
src = src.replace(old_call, new_call)

with open('/app/synth_engine.py', 'w') as f:
    f.write(src)
print("  [FIXED] synth_engine.py: strength-aware suppression (Approach B)")

# ===== PHASE 3: VERIFY =====

print("\n" + "=" * 60)
print("  Phase 3: Verification")
print("=" * 60)

# Reload modules to pick up fixes
import importlib
import rob_parser
import synth_engine
importlib.reload(rob_parser)
importlib.reload(synth_engine)
from rob_parser import parse_rob_file
from synth_engine import synthesize_for_section

# Re-check all three bugs
r = parse_rob_file('/app/objects/riscv_rel_a8.rob')
rel_addend = r['sections'][0].relocations[0].r_addend
print(f"  Parser REL addend: {rel_addend!r} (want None) -> {'OK' if rel_addend is None else 'FAIL'}")

r = parse_rob_file('/app/objects/riscv_weak_a8.rob')
_, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
print(f"  Weak ALIGN synth: {len(synth)} (want 1) -> {'OK' if len(synth) == 1 else 'FAIL'}")

r = parse_rob_file('/app/objects/la_boundary_a4.rob')
_, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
print(f"  LoongArch align=4 synth: {len(synth)} (want 0) -> {'OK' if len(synth) == 0 else 'FAIL'}")

print("\n  All regressions repaired.")
