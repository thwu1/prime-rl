
import json
import subprocess
import os
import re
import pytest


EXPECTED_CLASSIFICATION = {
    "interleaved_copy": "sb_only",
    "activated_overwrite": "tb_only",
    "reborrow_invalidation": "both",
    "disjoint_raw_ptrs": "neither",
    "shared_read_after_mut": "sb_only",
    "protector_violation": "both",
}


def test_classification_file_exists():
    """classification.json must exist at /app/classification.json."""
    assert os.path.exists("/app/classification.json"), (
        "classification.json not found at /app/classification.json"
    )


def test_classification_correct():
    """Each function must be correctly classified."""
    with open("/app/classification.json") as f:
        actual = json.load(f)

    for func_name, expected_class in EXPECTED_CLASSIFICATION.items():
        assert func_name in actual, f"Missing classification for '{func_name}'"
        assert actual[func_name] == expected_class, (
            f"Wrong classification for '{func_name}': "
            f"expected '{expected_class}', got '{actual[func_name]}'"
        )


def test_code_compiles():
    """The fixed code must compile successfully."""
    result = subprocess.run(
        ["cargo", "build"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout + "\n" + result.stderr
    assert result.returncode == 0, (
        f"cargo build failed:\n{combined}"
    )


def test_all_rust_tests_pass():
    """All 6 Rust tests must pass after fixing."""
    result = subprocess.run(
        ["cargo", "test"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout + "\n" + result.stderr
    assert result.returncode == 0, (
        f"cargo test failed:\n{combined}"
    )
    assert "6 passed" in combined, (
        f"Expected 6 tests to pass, output:\n{combined}"
    )


def _extract_function_body(source, func_name):
    """Extract the body of a Rust function (content between outermost braces)."""
    pattern = rf'(?:pub\s+)?unsafe\s+fn\s+{re.escape(func_name)}\s*\('
    match = re.search(pattern, source)
    if not match:
        return None

    # Find the opening brace after the signature
    brace_start = source.find('{', match.start())
    if brace_start == -1:
        return None

    # Brace-match to find closing brace
    depth = 1
    i = brace_start + 1
    while i < len(source) and depth > 0:
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
        i += 1

    return source[brace_start + 1:i - 1]


def test_structural_fixes():
    """Verify that known UB-causing patterns have been removed from the fixed code."""
    with open("/app/src/lib.rs") as f:
        source = f.read()

    # --- interleaved_copy (sb_only): must not use .as_ptr() ---
    body = _extract_function_body(source, "interleaved_copy")
    assert body is not None, "interleaved_copy function not found"
    assert ".as_ptr()" not in body, (
        "interleaved_copy still uses .as_ptr() which causes UB under Stacked Borrows"
    )

    # --- activated_overwrite (tb_only): must not use .as_ptr() ---
    body = _extract_function_body(source, "activated_overwrite")
    assert body is not None, "activated_overwrite function not found"
    assert ".as_ptr()" not in body, (
        "activated_overwrite still uses .as_ptr() which causes UB under Tree Borrows"
    )

    # --- shared_read_after_mut (sb_only): must not use .as_ptr() ---
    body = _extract_function_body(source, "shared_read_after_mut")
    assert body is not None, "shared_read_after_mut function not found"
    assert ".as_ptr()" not in body, (
        "shared_read_after_mut still uses .as_ptr() which causes UB under Stacked Borrows"
    )

    # --- reborrow_invalidation (both): must not read through child after parent write ---
    body = _extract_function_body(source, "reborrow_invalidation")
    assert body is not None, "reborrow_invalidation function not found"
    parent_writes = [m.start() for m in re.finditer(r'\*parent\s*=', body)]
    child_reads = [m.start() for m in re.finditer(r'\*child(?!\s*=)', body)]
    if parent_writes:
        last_parent_write = max(parent_writes)
        late_child_reads = [r for r in child_reads if r > last_parent_write]
        assert not late_child_reads, (
            "reborrow_invalidation reads *child after *parent write"
        )

    # --- protector_violation (both): protector_inner must not take &mut ---
    sig_match = re.search(r'fn\s+protector_inner\s*\(([^)]*)\)', source)
    assert sig_match, "protector_inner function not found"
    params = sig_match.group(1)
    assert "&mut" not in params, (
        "protector_inner still takes &mut parameter"
    )
