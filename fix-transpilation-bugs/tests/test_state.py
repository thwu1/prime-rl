"""Tests for C-to-Rust transpilation semantic equivalence and audit.

"""

import subprocess
import os
import json
import pytest
import tempfile


def run_c(input_file):
    result = subprocess.run(
        ["/app/c_src/record_processor", input_file],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"C program failed: {result.stderr}"
    return result.stdout


def run_rust(input_file):
    result = subprocess.run(
        ["/app/rust_src/target/release/record_processor", input_file],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"Rust program failed: {result.stderr}"
    return result.stdout


def test_full_output_match():
    """Full output must be byte-identical between C and Rust."""
    c_out = run_c("/app/data/input.txt")
    rust_out = run_rust("/app/data/input.txt")
    assert c_out == rust_out, (
        f"Outputs differ.\n\n--- C output ---\n{c_out}\n"
        f"--- Rust output ---\n{rust_out}"
    )


def test_category_stats():
    """Per-category statistics lines must match."""
    c_out = run_c("/app/data/input.txt")
    rust_out = run_rust("/app/data/input.txt")
    c_cats = [l for l in c_out.splitlines() if l.startswith("CAT[")]
    rust_cats = [l for l in rust_out.splitlines() if l.startswith("CAT[")]
    assert len(c_cats) == len(rust_cats), (
        f"Different number of categories: C={len(c_cats)}, Rust={len(rust_cats)}"
    )
    for i, (cl, rl) in enumerate(zip(c_cats, rust_cats)):
        assert cl == rl, f"Category line {i} differs:\n  C:    {cl}\n  Rust: {rl}"


def test_global_hash():
    """Global hash line must match."""
    c_out = run_c("/app/data/input.txt")
    rust_out = run_rust("/app/data/input.txt")
    c_hash = [l for l in c_out.splitlines() if l.startswith("GLOBAL_HASH:")]
    rust_hash = [l for l in rust_out.splitlines() if l.startswith("GLOBAL_HASH:")]
    assert c_hash == rust_hash, (
        f"Global hash differs: C={c_hash}, Rust={rust_hash}"
    )


def test_compact_serial():
    """Compact serialization section must match (delta + zigzag + varint)."""
    c_out = run_c("/app/data/input.txt")
    rust_out = run_rust("/app/data/input.txt")
    c_serial = [l for l in c_out.splitlines() if l.strip().startswith("S[")]
    rust_serial = [l for l in rust_out.splitlines() if l.strip().startswith("S[")]
    assert len(c_serial) == len(rust_serial), (
        f"Different number of serial lines: C={len(c_serial)}, Rust={len(rust_serial)}"
    )
    for i, (cl, rl) in enumerate(zip(c_serial, rust_serial)):
        assert cl == rl, f"Serial line {i} differs:\n  C:    {cl}\n  Rust: {rl}"


def test_varint_check():
    """Varint encode/decode roundtrip results must match."""
    c_out = run_c("/app/data/input.txt")
    rust_out = run_rust("/app/data/input.txt")
    c_varint = [l for l in c_out.splitlines() if l.strip().startswith("V(")]
    rust_varint = [l for l in rust_out.splitlines() if l.strip().startswith("V(")]
    assert len(c_varint) == len(rust_varint), (
        f"Different number of varint checks: C={len(c_varint)}, Rust={len(rust_varint)}"
    )
    for i, (cl, rl) in enumerate(zip(c_varint, rust_varint)):
        assert cl == rl, f"Varint check {i} differs:\n  C:    {cl}\n  Rust: {rl}"


def test_be16_check():
    """Big-endian 16-bit read results must match."""
    c_out = run_c("/app/data/input.txt")
    rust_out = run_rust("/app/data/input.txt")
    c_be = [l for l in c_out.splitlines() if l.strip().startswith("[")]
    rust_be = [l for l in rust_out.splitlines() if l.strip().startswith("[")]
    assert c_be == rust_be, (
        f"BE16 checks differ:\n  C:    {c_be}\n  Rust: {rust_be}"
    )


def test_zigzag_check():
    """Zigzag encoding/decoding results must match."""
    c_out = run_c("/app/data/input.txt")
    rust_out = run_rust("/app/data/input.txt")
    c_zz = [l for l in c_out.splitlines() if l.strip().startswith("ZZ(")]
    rust_zz = [l for l in rust_out.splitlines() if l.strip().startswith("ZZ(")]
    assert len(c_zz) == len(rust_zz), (
        f"Different number of zigzag checks: C={len(c_zz)}, Rust={len(rust_zz)}"
    )
    for i, (cl, rl) in enumerate(zip(c_zz, rust_zz)):
        assert cl == rl, f"Zigzag check {i} differs:\n  C:    {cl}\n  Rust: {rl}"


def test_fingerprint_values():
    """Fingerprint (FP) values in category lines must match."""
    c_out = run_c("/app/data/input.txt")
    rust_out = run_rust("/app/data/input.txt")
    c_cats = [l for l in c_out.splitlines() if l.startswith("CAT[")]
    rust_cats = [l for l in rust_out.splitlines() if l.startswith("CAT[")]
    for i, (cl, rl) in enumerate(zip(c_cats, rust_cats)):
        c_fp = cl.split("FP=")[1] if "FP=" in cl else ""
        r_fp = rl.split("FP=")[1] if "FP=" in rl else ""
        assert c_fp == r_fp, (
            f"Fingerprint mismatch for category {i}:\n  C:    {c_fp}\n  Rust: {r_fp}"
        )


def test_no_roundtrip_failures():
    """Roundtrip failure lines must match between C and Rust."""
    c_out = run_c("/app/data/input.txt")
    rust_out = run_rust("/app/data/input.txt")
    c_fails = [l for l in c_out.splitlines() if "ROUNDTRIP_FAIL" in l]
    rust_fails = [l for l in rust_out.splitlines() if "ROUNDTRIP_FAIL" in l]
    assert c_fails == rust_fails, (
        f"Roundtrip failures differ:\n  C:    {c_fails}\n  Rust: {rust_fails}"
    )


def test_edge_case_input():
    """Output must match on edge-case inputs with extreme values."""
    edge_input = (
        "# Edge case records\n"
        "EDGE001|1|0|00000000|0\n"
        "EDGE002|1|2147483647|FFFFFFFF|1\n"
        "EDGE003|1|-2147483648|80000000|-1\n"
        "EDGE004|2|1|00000001|32767\n"
        "EDGE005|2|-1|00000001|-32768\n"
        "EDGE006|3|-5000|ABCDEF01|10\n"
        "EDGE007|3|1000|00001234|5\n"
        "EDGE008|4|65534|00000002|1\n"
        "EDGE009|4|1|00000002|1\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(edge_input)
        edge_path = f.name
    try:
        c_out = run_c(edge_path)
        rust_out = run_rust(edge_path)
        assert c_out == rust_out, (
            f"Edge case outputs differ.\n\n--- C output ---\n{c_out}\n"
            f"--- Rust output ---\n{rust_out}"
        )
    finally:
        os.unlink(edge_path)


def test_single_record():
    """Output must match for a single-record input."""
    single = "REC1|99|-42|DEADBEEF|-7\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(single)
        path = f.name
    try:
        c_out = run_c(path)
        rust_out = run_rust(path)
        assert c_out == rust_out, (
            f"Single record outputs differ.\n\n--- C ---\n{c_out}\n"
            f"--- Rust ---\n{rust_out}"
        )
    finally:
        os.unlink(path)


def test_audit_file_exists():
    """Transpilation audit JSON must exist at /app/transpilation_audit.json."""
    assert os.path.isfile("/app/transpilation_audit.json"), (
        "Missing /app/transpilation_audit.json — audit report is a required deliverable"
    )


def test_audit_file_valid_json():
    """Audit file must be valid JSON containing an array."""
    with open("/app/transpilation_audit.json", "r") as f:
        data = json.load(f)
    assert isinstance(data, list), "Audit file must be a JSON array"


def test_audit_sufficient_entries():
    """Audit must document at least 6 distinct bugs."""
    with open("/app/transpilation_audit.json", "r") as f:
        data = json.load(f)
    assert len(data) >= 6, (
        f"Audit contains only {len(data)} entries; expected at least 6 distinct bugs"
    )


def test_audit_entry_schema():
    """Each audit entry must have required fields with valid values."""
    with open("/app/transpilation_audit.json", "r") as f:
        data = json.load(f)
    required_fields = {"location", "root_cause", "severity", "fix_description"}
    valid_severities = {"critical", "major", "minor"}
    for i, entry in enumerate(data):
        assert isinstance(entry, dict), f"Entry {i} is not a dict"
        missing = required_fields - set(entry.keys())
        assert not missing, f"Entry {i} missing fields: {missing}"
        assert entry["severity"] in valid_severities, (
            f"Entry {i} severity '{entry['severity']}' not in {valid_severities}"
        )
        for field in required_fields:
            assert isinstance(entry[field], str) and len(entry[field].strip()) > 0, (
                f"Entry {i} field '{field}' must be a non-empty string"
            )


def test_audit_unique_locations():
    """Audit entries must reference at least 4 distinct code locations."""
    with open("/app/transpilation_audit.json", "r") as f:
        data = json.load(f)
    locations = set()
    for entry in data:
        locations.add(entry["location"].strip().lower())
    assert len(locations) >= 4, (
        f"Only {len(locations)} distinct locations found; "
        f"expected at least 4 distinct code regions"
    )


def test_audit_severity_distribution():
    """Audit must assign at least two different severity levels."""
    with open("/app/transpilation_audit.json", "r") as f:
        data = json.load(f)
    severities = set(entry["severity"] for entry in data)
    assert len(severities) >= 2, (
        f"All entries have same severity '{severities.pop()}'; "
        f"expected meaningful severity differentiation"
    )
