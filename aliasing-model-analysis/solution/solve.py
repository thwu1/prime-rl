#!/usr/bin/env python3

"""
Solution for the Rust aliasing model forensics task.

Strategy:
1. Parse pre-captured Miri diagnostics, validating each file:
   - Check the test name in the output matches the expected function
   - Check the output is complete (contains a verdict, not truncated)
2. For unreliable diagnostics, analyze the Rust source code patterns
3. Write classification.json
4. Apply fixes to lib.rs
5. Verify fixes compile and pass cargo test
"""

import json
import os
import re
import subprocess
import sys

FUNCTIONS = [
    "interleaved_copy",
    "activated_overwrite",
    "reborrow_invalidation",
    "disjoint_raw_ptrs",
    "shared_read_after_mut",
    "protector_violation",
]

DIAGNOSTICS_DIR = "/app/diagnostics"


def validate_diagnostic(filepath, expected_func):
    """Read a diagnostic file and validate its integrity.

    Returns (is_valid, has_ub) where:
    - is_valid: True if the file is complete and matches the expected function
    - has_ub: True if UB was detected (only meaningful if is_valid)
    """
    if not os.path.exists(filepath):
        return False, False

    with open(filepath) as f:
        content = f.read()

    # Check test name matches expected function
    test_name_pattern = rf"test tests::test_{re.escape(expected_func)}\s+\.\.\."
    if not re.search(test_name_pattern, content):
        # Check if a DIFFERENT test name appears (mislabeled file)
        other_test = re.search(r"test tests::test_(\w+)\s+\.\.\.", content)
        if other_test and other_test.group(1) != expected_func:
            print(f"  WARNING: {filepath} contains output for "
                  f"test_{other_test.group(1)}, not test_{expected_func}")
            return False, False
        # No test name found at all (badly truncated)
        return False, False

    # Check output is complete (has a verdict: "ok", "error:", or "FAILED")
    has_verdict = ("... ok" in content or
                   "... error:" in content or
                   "... FAILED" in content or
                   "test result:" in content)

    if not has_verdict:
        print(f"  WARNING: {filepath} appears truncated (no verdict)")
        return False, False

    has_ub = "Undefined Behavior" in content
    return True, has_ub


def analyze_code_sb(source, func_name):
    """Analyze source code to determine if a function has UB under Stacked Borrows.

    Key SB patterns that cause UB:
    - as_ptr() creates SharedReadOnly; subsequent as_mut_ptr() Unique retag pops it
    - Parent write through raw ptr pops child tag from borrow stack
    - Protected &mut forbids writes through aliasing pointers
    """
    # Extract function body
    pattern = rf'(?:pub\s+)?unsafe\s+fn\s+{re.escape(func_name)}\s*\('
    match = re.search(pattern, source)
    if not match:
        return False

    brace_start = source.find('{', match.start())
    depth = 1
    i = brace_start + 1
    while i < len(source) and depth > 0:
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
        i += 1
    body = source[brace_start + 1:i - 1]

    # Pattern: as_ptr() before as_mut_ptr() — SharedReadOnly invalidated by Unique retag
    has_as_ptr = ".as_ptr()" in body
    has_as_mut_ptr = ".as_mut_ptr()" in body

    if has_as_ptr and has_as_mut_ptr:
        ptr_pos = body.find(".as_ptr()")
        mut_pos = body.find(".as_mut_ptr()")
        if ptr_pos < mut_pos:
            # as_ptr() derived pointer used after as_mut_ptr() Unique retag
            return True

    # Pattern: SharedReadOnly pointers read after as_mut_ptr Unique retag
    # (reads via as_ptr()-derived pointers after as_mut_ptr() call)
    if has_as_ptr and has_as_mut_ptr:
        # Find all as_ptr and as_mut_ptr positions
        as_ptr_uses = [m.start() for m in re.finditer(r'\.as_ptr\(\)', body)]
        as_mut_ptr_uses = [m.start() for m in re.finditer(r'\.as_mut_ptr\(\)', body)]
        # If any as_ptr is before any as_mut_ptr, and the as_ptr result
        # is used after the as_mut_ptr call
        for pp in as_ptr_uses:
            for mp in as_mut_ptr_uses:
                if pp < mp:
                    return True

    # Pattern: parent-child reborrow with parent write before child read
    parent_writes = [m.start() for m in re.finditer(r'\*parent\s*=', body)]
    child_reads = [m.start() for m in re.finditer(r'\*child(?!\s*=)', body)]
    if parent_writes and child_reads:
        last_parent_write = max(parent_writes)
        late_child_reads = [r for r in child_reads if r > last_parent_write]
        if late_child_reads:
            return True

    return False


def analyze_code_tb(source, func_name):
    """Analyze source code to determine if a function has UB under Tree Borrows.

    Key TB patterns that cause UB:
    - Write activates Reserved->Active; foreign read freezes Active->Frozen;
      subsequent write through Frozen is UB
    - Parent write disables child (Active->Disabled)
    - Protected &mut violated by sibling writes
    """
    pattern = rf'(?:pub\s+)?unsafe\s+fn\s+{re.escape(func_name)}\s*\('
    match = re.search(pattern, source)
    if not match:
        return False

    brace_start = source.find('{', match.start())
    depth = 1
    i = brace_start + 1
    while i < len(source) and depth > 0:
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
        i += 1
    body = source[brace_start + 1:i - 1]

    # Pattern: write through as_mut_ptr, then as_ptr() reborrow (foreign read
    # freezes Active), then write again — Active->Frozen->write = UB
    has_as_mut_ptr = ".as_mut_ptr()" in body
    if has_as_mut_ptr:
        mut_pos = body.find(".as_mut_ptr()")
        # Look for write, then as_ptr read, then another write
        # through the original mut pointer
        writes_through_dst = list(re.finditer(r'\*dst\s*=', body))
        as_ptr_calls = list(re.finditer(r'\.as_ptr\(\)', body))
        if len(writes_through_dst) >= 2 and as_ptr_calls:
            first_write = writes_through_dst[0].start()
            second_write = writes_through_dst[1].start()
            for ap in as_ptr_calls:
                if first_write < ap.start() < second_write:
                    return True

    # Pattern: parent-child with parent write disabling child
    parent_writes = [m.start() for m in re.finditer(r'\*parent\s*=', body)]
    child_reads = [m.start() for m in re.finditer(r'\*child(?!\s*=)', body)]
    if parent_writes and child_reads:
        last_parent_write = max(parent_writes)
        late_child_reads = [r for r in child_reads if r > last_parent_write]
        if late_child_reads:
            return True

    return False


def check_protector_violation(source):
    """Check if protector_violation triggers UB under either model.
    Protected &mut + aliasing raw write = UB under both SB and TB."""
    sig_match = re.search(r'fn\s+protector_inner\s*\(([^)]*)\)', source)
    if sig_match and "&mut" in sig_match.group(1):
        return True
    return False


# ============================================================
# Step 1: Load source code for fallback analysis
# ============================================================
with open("/app/src/lib.rs") as f:
    source = f.read()

# ============================================================
# Step 2: Classify each function
# ============================================================
print("=" * 60)
print("Classifying functions from diagnostics + code analysis")
print("=" * 60)

classification = {}
for func in FUNCTIONS:
    sb_file = os.path.join(DIAGNOSTICS_DIR, "stacked_borrows", f"test_{func}.txt")
    tb_file = os.path.join(DIAGNOSTICS_DIR, "tree_borrows", f"test_{func}.txt")

    sb_valid, sb_ub = validate_diagnostic(sb_file, func)
    tb_valid, tb_ub = validate_diagnostic(tb_file, func)

    # Fallback to code analysis for unreliable diagnostics
    if not sb_valid:
        print(f"  {func} SB: diagnostic unreliable, analyzing code...")
        if func == "protector_violation":
            sb_ub = check_protector_violation(source)
        else:
            sb_ub = analyze_code_sb(source, func)
    if not tb_valid:
        print(f"  {func} TB: diagnostic unreliable, analyzing code...")
        if func == "protector_violation":
            tb_ub = check_protector_violation(source)
        else:
            tb_ub = analyze_code_tb(source, func)

    if sb_ub and tb_ub:
        cat = "both"
    elif sb_ub:
        cat = "sb_only"
    elif tb_ub:
        cat = "tb_only"
    else:
        cat = "neither"

    print(f"  {func}: {cat} (SB={'UB' if sb_ub else 'ok'}, TB={'UB' if tb_ub else 'ok'})")
    classification[func] = cat

# ============================================================
# Step 3: Write classification.json
# ============================================================
print("\n" + "=" * 60)
print("Writing classification.json")
print("=" * 60)

with open("/app/classification.json", "w") as f:
    json.dump(classification, f, indent=2)

print(json.dumps(classification, indent=2))

# ============================================================
# Step 4: Apply fixes to lib.rs
# ============================================================
print("\n" + "=" * 60)
print("Applying fixes to /app/src/lib.rs")
print("=" * 60)

with open("/solution/fixed_lib.rs", "r") as f:
    fixed_code = f.read()

with open("/app/src/lib.rs", "w") as f:
    f.write(fixed_code)

print("Fixed lib.rs written.")

# ============================================================
# Step 5: Verify fixes compile and pass tests
# ============================================================
print("\n" + "=" * 60)
print("Verifying fixes")
print("=" * 60)

build_result = subprocess.run(
    ["cargo", "build"],
    cwd="/app",
    capture_output=True,
    text=True,
    timeout=120,
)
if build_result.returncode != 0:
    print(f"cargo build FAILED:\n{build_result.stderr}")
    sys.exit(1)
print("cargo build: OK")

test_result = subprocess.run(
    ["cargo", "test"],
    cwd="/app",
    capture_output=True,
    text=True,
    timeout=120,
)
combined = test_result.stdout + "\n" + test_result.stderr
if test_result.returncode != 0:
    print(f"cargo test FAILED:\n{combined}")
    sys.exit(1)
if "6 passed" not in combined:
    print(f"Not all 6 tests passed:\n{combined}")
    sys.exit(1)
print("cargo test: OK (6 passed)")

print("\nAll checks passed!")
