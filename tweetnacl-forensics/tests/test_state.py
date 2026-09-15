
"""
Tests for the NaCl conformance auditor.

Verifies that /app/nacl_auditor.py correctly:
- Passes the reference (correct) TweetNaCl build
- Detects all 4 bugs in the suspect TweetNaCl build
- Produces JSON reports conforming to the required schema
- Discovers symbols via nm -D
- Handles error cases
"""

import json
import os
import subprocess

import pytest


REF_LIB = "/app/libtweetnacl_reference.so"
SUS_LIB = "/app/libtweetnacl_suspect.so"
AUDITOR = "/app/nacl_auditor.py"

REQUIRED_PRIMITIVES = [
    "crypto_hash_sha512",
    "crypto_core_salsa20",
    "crypto_onetimeauth_poly1305",
    "crypto_sign_ed25519",
    "crypto_scalarmult_curve25519",
]


@pytest.fixture(scope="session", autouse=True)
def ensure_libraries():
    """Build both shared libraries if not already present."""
    subprocess.run(["make", "-C", "/app", "all"], capture_output=True, check=True)
    assert os.path.exists(REF_LIB), "Reference library not built"
    assert os.path.exists(SUS_LIB), "Suspect library not built"


def run_auditor(lib_path):
    """Run the auditor and return (returncode, parsed_report_or_None, stderr)."""
    r = subprocess.run(
        ["python3", AUDITOR, lib_path],
        capture_output=True, text=True, cwd="/app",
        timeout=120,
    )
    report = None
    if r.stdout.strip():
        try:
            report = json.loads(r.stdout)
        except json.JSONDecodeError:
            pass
    return r.returncode, report, r.stderr


# -----------------------------------------------------------------------
# Basic existence and executability
# -----------------------------------------------------------------------

def test_auditor_exists():
    """nacl_auditor.py must exist at /app/."""
    assert os.path.exists(AUDITOR), f"{AUDITOR} not found"


# -----------------------------------------------------------------------
# Reference build: everything should pass
# -----------------------------------------------------------------------

def test_reference_exit_code():
    """Auditor should exit 0 on the reference build."""
    rc, report, stderr = run_auditor(REF_LIB)
    assert rc == 0, f"Non-zero exit on reference: {stderr}"


def test_reference_overall_pass():
    """Reference build should have overall_status == 'pass'."""
    _, report, _ = run_auditor(REF_LIB)
    assert report is not None, "No JSON output"
    assert report["overall_status"] == "pass"


def test_reference_zero_bugs():
    """Reference build should have bugs_found == 0."""
    _, report, _ = run_auditor(REF_LIB)
    assert report["bugs_found"] == 0


def test_reference_all_primitives_pass():
    """Every primitive should pass on the reference build."""
    _, report, _ = run_auditor(REF_LIB)
    for name in REQUIRED_PRIMITIVES:
        assert name in report["primitives"], f"Missing primitive: {name}"
        assert report["primitives"][name]["status"] == "pass", \
            f"{name} should pass on reference build"


# -----------------------------------------------------------------------
# Suspect build: should detect exactly 4 bugs
# -----------------------------------------------------------------------

def test_suspect_exit_code():
    """Auditor should exit 0 on suspect build (audit completed successfully)."""
    rc, _, stderr = run_auditor(SUS_LIB)
    assert rc == 0, f"Non-zero exit on suspect: {stderr}"


def test_suspect_overall_fail():
    """Suspect build should have overall_status == 'fail'."""
    _, report, _ = run_auditor(SUS_LIB)
    assert report is not None, "No JSON output"
    assert report["overall_status"] == "fail"


def test_suspect_four_bugs():
    """Suspect build should have bugs_found == 4."""
    _, report, _ = run_auditor(SUS_LIB)
    assert report["bugs_found"] == 4, \
        f"Expected 4 bugs, found {report['bugs_found']}"


def test_suspect_sha512_fails():
    """SHA-512 primitive should fail on suspect build."""
    _, report, _ = run_auditor(SUS_LIB)
    assert report["primitives"]["crypto_hash_sha512"]["status"] == "fail"


def test_suspect_salsa20_fails():
    """Salsa20 core primitive should fail on suspect build."""
    _, report, _ = run_auditor(SUS_LIB)
    assert report["primitives"]["crypto_core_salsa20"]["status"] == "fail"


def test_suspect_poly1305_fails():
    """Poly1305 primitive should fail on suspect build."""
    _, report, _ = run_auditor(SUS_LIB)
    assert report["primitives"]["crypto_onetimeauth_poly1305"]["status"] == "fail"


def test_suspect_ed25519_fails():
    """Ed25519 primitive should fail on suspect build."""
    _, report, _ = run_auditor(SUS_LIB)
    assert report["primitives"]["crypto_sign_ed25519"]["status"] == "fail"


def test_suspect_scalarmult_passes():
    """Curve25519 scalarmult should pass on suspect build (no bug there)."""
    _, report, _ = run_auditor(SUS_LIB)
    assert report["primitives"]["crypto_scalarmult_curve25519"]["status"] == "pass"


# -----------------------------------------------------------------------
# JSON schema compliance
# -----------------------------------------------------------------------

def test_report_has_required_fields():
    """Report must contain all required top-level fields."""
    _, report, _ = run_auditor(SUS_LIB)
    for field in ["library_path", "symbol_count", "primitives",
                  "overall_status", "bugs_found"]:
        assert field in report, f"Missing top-level field: {field}"


def test_report_field_types():
    """Report fields must have correct types."""
    _, report, _ = run_auditor(SUS_LIB)
    assert isinstance(report["library_path"], str)
    assert isinstance(report["symbol_count"], int)
    assert isinstance(report["primitives"], dict)
    assert isinstance(report["overall_status"], str)
    assert isinstance(report["bugs_found"], int)


def test_report_all_primitives_present():
    """All 5 required primitives must be present in the report."""
    _, report, _ = run_auditor(SUS_LIB)
    for name in REQUIRED_PRIMITIVES:
        assert name in report["primitives"], f"Missing primitive: {name}"
        prim = report["primitives"][name]
        assert "status" in prim, f"{name}: missing 'status'"
        assert prim["status"] in ("pass", "fail"), \
            f"{name}: invalid status '{prim['status']}'"


def test_failed_primitives_have_evidence():
    """Each failed primitive must include evidence with hex fields."""
    _, report, _ = run_auditor(SUS_LIB)
    for name, result in report["primitives"].items():
        if result["status"] == "fail":
            assert "evidence" in result, \
                f"{name}: failed but missing 'evidence'"
            ev = result["evidence"]
            for field in ["input_hex", "expected_hex", "actual_hex"]:
                assert field in ev, \
                    f"{name}: evidence missing '{field}'"
                assert isinstance(ev[field], str), \
                    f"{name}: evidence['{field}'] not a string"
                assert len(ev[field]) > 0, \
                    f"{name}: evidence['{field}'] is empty"


# -----------------------------------------------------------------------
# Symbol discovery
# -----------------------------------------------------------------------

def test_symbol_count_reasonable():
    """symbol_count should reflect actual NaCl exports (>= 15)."""
    _, report, _ = run_auditor(REF_LIB)
    assert report["symbol_count"] >= 15, \
        f"Too few symbols: {report['symbol_count']}"


def test_symbol_count_matches_nm():
    """symbol_count should be consistent with nm -D output."""
    r = subprocess.run(
        ["nm", "-D", REF_LIB], capture_output=True, text=True
    )
    nm_text_syms = [
        line.split()[-1] for line in r.stdout.splitlines()
        if len(line.split()) >= 3 and line.split()[1] == "T"
    ]
    _, report, _ = run_auditor(REF_LIB)
    # Allow reasonable tolerance for filtering approaches
    assert abs(report["symbol_count"] - len(nm_text_syms)) <= 10, \
        f"symbol_count {report['symbol_count']} differs significantly " \
        f"from nm count {len(nm_text_syms)}"


# -----------------------------------------------------------------------
# Error handling
# -----------------------------------------------------------------------

def test_error_on_nonexistent_library():
    """Auditor should exit non-zero for a non-existent library path."""
    rc, _, _ = run_auditor("/nonexistent/library.so")
    assert rc != 0


def test_schema_validation():
    """Report should validate against the provided JSON schema."""
    import jsonschema

    with open("/app/audit_schema.json") as f:
        schema = json.load(f)

    _, report, _ = run_auditor(SUS_LIB)
    # This will raise if validation fails
    jsonschema.validate(instance=report, schema=schema)

    _, report_ref, _ = run_auditor(REF_LIB)
    jsonschema.validate(instance=report_ref, schema=schema)
