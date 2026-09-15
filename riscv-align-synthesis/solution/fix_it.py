#!/usr/bin/env python3
"""
Diagnose and fix three regressions in the alignment synthesis pipeline.

Bug 1 (rob_parser.py): REL-format relocations (r_format=1) have no
explicit addend in ELF. The parser reads r_format but ignores it,
always setting r_addend to the raw binary value. For REL entries,
r_addend must be None.

Bug 2 (synth_engine.py): LoongArch synthesis threshold is >= 4,
unified with RISC-V during a refactoring. But LoongArch's minimum
NOP is 4 bytes, so align=4 never needs padding. Threshold must be > 4.

Bug 3 (synth_engine.py): _is_covered() uses existence-only check --
any ALIGN at offset 0 suppresses synthesis. Per spec (Approach B),
only suppress when RELA addend >= (addralign - min_nop). Weak ALIGNs
from older assemblers must not suppress synthesis.
"""


import sys

errors = []

# ========== Fix 1: rob_parser.py ==========
print("=" * 60)
print("  Fixing rob_parser.py: REL format handling")
print("=" * 60)

with open('/app/rob_parser.py') as f:
    parser_src = f.read()

target = 'r_addend=r_addend,'
fix = 'r_addend=r_addend if r_format == 0 else None,'

if target not in parser_src:
    errors.append("rob_parser.py: cannot find 'r_addend=r_addend,'")
else:
    parser_src = parser_src.replace(target, fix, 1)
    with open('/app/rob_parser.py', 'w') as f:
        f.write(parser_src)
    print("  [FIXED] REL-format relocations now yield r_addend=None")

# ========== Fix 2 & 3: synth_engine.py ==========
print()
print("=" * 60)
print("  Fixing synth_engine.py: threshold + suppression logic")
print("=" * 60)

with open('/app/synth_engine.py') as f:
    engine_src = f.read()

# Fix 2: LoongArch threshold >= -> >
old_thresh = 'return addralign >= 4  # Unified with RISC-V during refactoring'
new_thresh = 'return addralign > 4'
if old_thresh not in engine_src:
    errors.append("synth_engine.py: cannot find LoongArch threshold line")
else:
    engine_src = engine_src.replace(old_thresh, new_thresh, 1)
    print("  [FIXED] LoongArch threshold: >= 4 -> > 4")

# Fix 3: Replace existence-only _is_covered with strength-aware version
old_fn = (
    'def _is_covered(sec: InputSection, align_type: int) -> bool:\n'
    '    """Check if an existing ALIGN at offset 0 already covers this section."""\n'
    '    return any(\n'
    '        r.r_offset == 0 and r.r_type == align_type\n'
    '        for r in sec.relocations\n'
    '    )'
)
new_fn = (
    'def _is_covered(sec: InputSection, align_type: int, needed: int) -> bool:\n'
    '    """Check if an existing ALIGN at offset 0 has sufficient strength."""\n'
    '    for r in sec.relocations:\n'
    '        if r.r_offset != 0 or r.r_type != align_type:\n'
    '            continue\n'
    '        if r.r_addend is None:\n'
    '            continue\n'
    '        if r.r_addend >= needed:\n'
    '            return True\n'
    '    return False'
)

if old_fn not in engine_src:
    errors.append("synth_engine.py: cannot find _is_covered function body")
else:
    engine_src = engine_src.replace(old_fn, new_fn, 1)
    print("  [FIXED] _is_covered: existence-only -> strength-aware")

# Fix 3b: Update call site to pass needed parameter
old_call = (
    '    if not _is_covered(sec, align_type):\n'
    '        addend = sec.addralign - get_min_nop(arch)'
)
new_call = (
    '    addend = sec.addralign - get_min_nop(arch)\n'
    '    if not _is_covered(sec, align_type, addend):'
)

if old_call not in engine_src:
    errors.append("synth_engine.py: cannot find _is_covered call site")
else:
    engine_src = engine_src.replace(old_call, new_call, 1)
    print("  [FIXED] Call site: compute addend before coverage check")

with open('/app/synth_engine.py', 'w') as f:
    f.write(engine_src)

# ========== Summary ==========
print()
if errors:
    print("ERRORS:")
    for e in errors:
        print(f"  {e}", file=sys.stderr)
    sys.exit(1)

print("All three regressions fixed successfully.")
