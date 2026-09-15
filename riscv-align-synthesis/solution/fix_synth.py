#!/usr/bin/env python3
"""
Fix the alignment synthesis bugs in align_synth.py.

Bug 1: _has_offset_zero_align only checks for the EXISTENCE of an
ALIGN relocation at offset 0. It should check whether the existing
ALIGN's addend is strong enough (>= addralign - min_nop) to cover
the section's alignment requirement.

Bug 2: REL-format relocations (r_addend=None) have no explicit addend.
The linker cannot determine alignment strength from REL format, so
it must always synthesize regardless of ALIGN existence.

Fix: Replace _has_offset_zero_align with _is_covered_by_align that
performs addend strength comparison and handles REL format correctly.
"""


import re

SYNTH_PATH = '/app/align_synth.py'

with open(SYNTH_PATH, 'r') as f:
    content = f.read()

# Identify the buggy function and its call site
# The bug is in _has_offset_zero_align: it returns True for ANY
# ALIGN at offset 0 regardless of addend strength or format.

old_func = '''def _has_offset_zero_align(sec: InputSection, align_type: int) -> bool:
    """
    Check whether the section already has an ALIGN relocation at
    offset 0.

    If any ALIGN relocation exists at the section start, this function
    returns True, indicating the assembler already handled alignment
    at the section entry point.
    """
    return any(
        r.r_offset == 0 and r.r_type == align_type
        for r in sec.relocations
    )'''

new_func = '''def _is_covered_by_align(sec: InputSection, align_type: int, arch: Arch) -> bool:
    """
    Check whether an existing ALIGN relocation at offset 0 already
    covers the section's alignment requirement.

    Coverage requires RELA format with addend >= (addralign - min_nop).
    A weak ALIGN (small addend) or REL-format ALIGN (no addend) does
    NOT cover a stronger alignment need.
    """
    needed = sec.addralign - get_min_nop(arch)
    for r in sec.relocations:
        if r.r_offset != 0 or r.r_type != align_type:
            continue
        # REL format has no explicit addend -- cannot determine strength
        if not r.has_addend:
            continue
        if r.r_addend >= needed:
            return True
    return False'''

if old_func not in content:
    # Try to find and fix even if formatting differs slightly
    print("WARNING: Could not find exact buggy function text.")
    print("Attempting regex-based replacement...")

    # Use regex to match the function
    pattern = r'def _has_offset_zero_align\(sec: InputSection, align_type: int\) -> bool:.*?(?=\ndef |\nclass |\Z)'
    match = re.search(pattern, content, re.DOTALL)
    if match:
        content = content[:match.start()] + new_func + content[match.end():]
    else:
        raise RuntimeError("Could not locate _has_offset_zero_align function")
else:
    content = content.replace(old_func, new_func)

# Update the call site to use the new function with the arch parameter
old_call = 'if not _has_offset_zero_align(sec, align_type):'
new_call = 'if not _is_covered_by_align(sec, align_type, arch):'

if old_call in content:
    content = content.replace(old_call, new_call)
else:
    raise RuntimeError("Could not locate _has_offset_zero_align call site")

# Also fix analyze_section to use the new function
old_analyze_ref = "    has_zero = _has_offset_zero_align(sec, align_type)"
new_analyze_ref = "    has_zero = _is_covered_by_align(sec, align_type, arch)"
if old_analyze_ref in content:
    content = content.replace(old_analyze_ref, new_analyze_ref)

old_analyze_needs = "    'needs_synthesis': exceeds and not has_zero,"
# This line stays the same -- the semantics changed because has_zero
# now means "covered" rather than just "exists"

with open(SYNTH_PATH, 'w') as f:
    f.write(content)

# Verify the fix was applied
with open(SYNTH_PATH, 'r') as f:
    fixed = f.read()

assert '_is_covered_by_align' in fixed, "Fix not applied: new function missing"
assert '_has_offset_zero_align' not in fixed, "Fix incomplete: old function still present"

print("Successfully fixed alignment synthesis bugs:")
print("  1. Replaced existence check with addend strength comparison")
print("  2. REL-format relocations no longer suppress synthesis")
