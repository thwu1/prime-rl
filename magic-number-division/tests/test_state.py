
import json
import subprocess
import os
import hashlib
import pytest


EXPECTED_AUDIT_HASH = "dba3791747064b331fbc0202d8411010402dfd11df353f1315200efa61d41ab0"
EXPECTED_REMED_HASH = "6c77301ed338e802b8094247abdeea060f3cb583c37edb093b0fc6437fad0190"

# Ground truth for evaluation
GROUND_TRUTH = [
    {"func_index": 0, "verdict": "correct", "actual_operation": "sdiv", "actual_divisor": 7},
    {"func_index": 1, "verdict": "buggy", "actual_operation": "udiv", "actual_divisor": 10,
     "bug_category": "signedness_mismatch"},
    {"func_index": 2, "verdict": "correct", "actual_operation": "umod", "actual_divisor": 17},
    {"func_index": 3, "verdict": "correct", "actual_operation": "sdiv", "actual_divisor": 6},
    {"func_index": 4, "verdict": "buggy", "actual_operation": "sdiv", "actual_divisor": 127,
     "bug_category": "wrong_divisor"},
    {"func_index": 5, "verdict": "correct", "actual_operation": "udiv", "actual_divisor": 641},
    {"func_index": 6, "verdict": "buggy", "actual_operation": "sdiv", "actual_divisor": 7,
     "bug_category": "wrong_operation"},
    {"func_index": 7, "verdict": "correct", "actual_operation": "udiv", "actual_divisor": 31337},
]

# Spec (what each function is INTENDED to compute)
SPEC = [
    {"func_index": 0, "intended_operation": "sdiv", "intended_divisor": 7},
    {"func_index": 1, "intended_operation": "sdiv", "intended_divisor": 10},
    {"func_index": 2, "intended_operation": "umod", "intended_divisor": 17},
    {"func_index": 3, "intended_operation": "sdiv", "intended_divisor": 6},
    {"func_index": 4, "intended_operation": "sdiv", "intended_divisor": 125},
    {"func_index": 5, "intended_operation": "udiv", "intended_divisor": 641},
    {"func_index": 6, "intended_operation": "smod", "intended_divisor": 7},
    {"func_index": 7, "intended_operation": "udiv", "intended_divisor": 31337},
]

# Expected remediation results
EXPECTED_REMEDIATION = [
    {"func_index": 1, "severity": "critical", "error_count": 2147483648, "priority_rank": 3},
    {"func_index": 4, "severity": "critical", "error_count": 4294959359, "priority_rank": 2},
    {"func_index": 6, "severity": "critical", "error_count": 4294967283, "priority_rank": 1},
]


def load_audit():
    with open("/app/audit.json") as f:
        return json.load(f)


def load_remediation():
    with open("/app/remediation.json") as f:
        return json.load(f)


def _run_binary(binary_path, func_idx, value):
    """Run a binary and return the integer result."""
    result = subprocess.run(
        [binary_path, str(func_idx), str(value)],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, f"Binary failed for func {func_idx}, val {value}: {result.stderr}"
    return int(result.stdout.strip())


def _run_challenge(func_idx, value):
    return _run_binary("/app/challenge", func_idx, value)


def _run_fixed(func_idx, value):
    return _run_binary("/app/challenge_fixed", func_idx, value)


def _c_trunc_div(x, d):
    """C-style signed integer division (truncation toward zero)."""
    if d == 0:
        raise ValueError("Division by zero")
    if x >= 0:
        return x // d
    else:
        return -((-x) // d)


def _c_trunc_mod(x, d):
    """C-style signed integer modulo (result has sign of dividend)."""
    return x - _c_trunc_div(x, d) * d


def _compute_spec_expected(op, d, val):
    """Compute expected result per the SPECIFICATION."""
    if op == "sdiv":
        return _c_trunc_div(val, d)
    elif op == "smod":
        return _c_trunc_mod(val, d)
    elif op == "udiv":
        uval = val & 0xFFFFFFFF
        return uval // d
    elif op == "umod":
        uval = val & 0xFFFFFFFF
        return uval % d
    else:
        raise ValueError(f"Unknown operation: {op}")


# ===================================================================
# PART 1: Audit tests
# ===================================================================

def test_audit_file_exists():
    assert os.path.exists("/app/audit.json"), "/app/audit.json not found"


def test_audit_is_valid_json_array():
    data = load_audit()
    assert isinstance(data, list), "audit.json must be a JSON array"
    assert len(data) == 8, f"Expected 8 entries, got {len(data)}"


def test_all_func_indices_present():
    data = load_audit()
    indices = sorted(entry["func_index"] for entry in data)
    assert indices == list(range(8)), f"Expected func_index 0-7, got {indices}"


def test_all_verdicts_valid():
    data = load_audit()
    valid_verdicts = {"correct", "buggy"}
    for entry in data:
        assert entry["verdict"] in valid_verdicts, \
            f"func {entry['func_index']}: invalid verdict '{entry['verdict']}'"


def test_all_operations_valid():
    data = load_audit()
    valid_ops = {"sdiv", "smod", "udiv", "umod"}
    for entry in data:
        assert entry["actual_operation"] in valid_ops, \
            f"func {entry['func_index']}: invalid operation '{entry['actual_operation']}'"


def test_all_divisors_positive():
    data = load_audit()
    for entry in data:
        assert isinstance(entry["actual_divisor"], int) and entry["actual_divisor"] > 0, \
            f"func {entry['func_index']}: divisor must be a positive integer"


def test_buggy_entries_have_required_fields():
    data = load_audit()
    valid_categories = {"signedness_mismatch", "wrong_divisor", "wrong_operation"}
    for entry in data:
        if entry["verdict"] == "buggy":
            assert "bug_category" in entry, \
                f"func {entry['func_index']}: buggy entries must have 'bug_category'"
            assert entry["bug_category"] in valid_categories, \
                f"func {entry['func_index']}: invalid bug_category '{entry['bug_category']}'"
            assert "witness_input" in entry, \
                f"func {entry['func_index']}: buggy entries must have 'witness_input'"
            assert isinstance(entry["witness_input"], int), \
                f"func {entry['func_index']}: witness_input must be an integer"


def test_audit_answer_hash():
    """Verify the complete audit answer set matches the expected SHA-256 hash."""
    data = load_audit()
    data_sorted = sorted(data, key=lambda x: x["func_index"])
    parts = []
    for e in data_sorted:
        base = f"{e['func_index']}:{e['verdict']}:{e['actual_operation']}:{e['actual_divisor']}"
        if e["verdict"] == "buggy":
            base += f":{e['bug_category']}"
        parts.append(base)
    canonical = "|".join(parts)
    h = hashlib.sha256(canonical.encode()).hexdigest()
    assert h == EXPECTED_AUDIT_HASH, (
        f"Audit hash mismatch. Got '{h}', expected '{EXPECTED_AUDIT_HASH}'. "
        f"Canonical string: '{canonical}'"
    )


@pytest.mark.parametrize("idx", range(8), ids=[f"func{i}" for i in range(8)])
def test_verdict_correct(idx):
    data = load_audit()
    results = {entry["func_index"]: entry for entry in data}
    assert idx in results, f"Missing entry for func_index {idx}"
    expected = GROUND_TRUTH[idx]
    actual = results[idx]
    assert actual["verdict"] == expected["verdict"], (
        f"func {idx}: verdict '{actual['verdict']}', expected '{expected['verdict']}'"
    )


@pytest.mark.parametrize("idx", range(8), ids=[f"func{i}" for i in range(8)])
def test_actual_operation_and_divisor(idx):
    data = load_audit()
    results = {entry["func_index"]: entry for entry in data}
    assert idx in results, f"Missing entry for func_index {idx}"
    expected = GROUND_TRUTH[idx]
    actual = results[idx]
    assert actual["actual_operation"] == expected["actual_operation"], (
        f"func {idx}: actual_operation '{actual['actual_operation']}', "
        f"expected '{expected['actual_operation']}'"
    )
    assert actual["actual_divisor"] == expected["actual_divisor"], (
        f"func {idx}: actual_divisor {actual['actual_divisor']}, "
        f"expected {expected['actual_divisor']}"
    )


@pytest.mark.parametrize("idx", [1, 4, 6], ids=["func1", "func4", "func6"])
def test_bug_category(idx):
    data = load_audit()
    results = {entry["func_index"]: entry for entry in data}
    expected = GROUND_TRUTH[idx]
    actual = results[idx]
    assert actual["bug_category"] == expected["bug_category"], (
        f"func {idx}: bug_category '{actual['bug_category']}', "
        f"expected '{expected['bug_category']}'"
    )


@pytest.mark.parametrize("idx", [1, 4, 6], ids=["func1_witness", "func4_witness", "func6_witness"])
def test_witness_triggers_bug(idx):
    data = load_audit()
    results = {entry["func_index"]: entry for entry in data}
    entry = results[idx]
    spec = SPEC[idx]
    witness = entry["witness_input"]
    actual_output = _run_challenge(idx, witness)
    expected_output = _compute_spec_expected(
        spec["intended_operation"], spec["intended_divisor"], witness
    )
    assert actual_output != expected_output, (
        f"func {idx}: witness_input={witness} does not trigger a bug. "
        f"Binary output={actual_output}, spec expected={expected_output} (they match!)"
    )


@pytest.mark.parametrize("idx", [0, 2, 3, 5, 7],
                         ids=["func0", "func2", "func3", "func5", "func7"])
def test_correct_function_matches_spec(idx):
    data = load_audit()
    results = {entry["func_index"]: entry for entry in data}
    spec = SPEC[idx]
    op = spec["intended_operation"]
    d = spec["intended_divisor"]
    test_values = [0, 1, 2, d - 1, d, d + 1, 2 * d, 3 * d - 1, 100 * d]
    if op.startswith("s"):
        test_values += [-1, -d, -(d + 1), -2 * d]
    else:
        test_values += [2**31, 2**32 - 1]
    test_values = [v for v in test_values if v >= 0 or op.startswith("s")]
    for val in test_values:
        actual = _run_challenge(idx, val)
        expected = _compute_spec_expected(op, d, val)
        assert actual == expected, (
            f"func {idx} (marked correct): f({val}) = {actual}, "
            f"spec says {op} by {d} -> {expected}"
        )


def test_binary_exists_and_runs():
    assert os.path.exists("/app/challenge"), "Binary not found"
    result = subprocess.run(
        ["/app/challenge", "0", "0"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, f"Binary failed: {result.stderr}"


# ===================================================================
# PART 2: Remediation severity evaluation tests
# ===================================================================

def test_remediation_file_exists():
    assert os.path.exists("/app/remediation.json"), "/app/remediation.json not found"


def test_remediation_structure():
    data = load_remediation()
    assert "bugs" in data, "remediation.json must have 'bugs' key"
    bugs = data["bugs"]
    assert isinstance(bugs, list), "'bugs' must be a list"
    assert len(bugs) == 3, f"Expected 3 bug entries, got {len(bugs)}"
    indices = sorted(b["func_index"] for b in bugs)
    assert indices == [1, 4, 6], f"Expected func_index [1,4,6], got {indices}"


def test_remediation_required_fields():
    data = load_remediation()
    for bug in data["bugs"]:
        for field in ("func_index", "severity", "error_count", "priority_rank"):
            assert field in bug, f"Bug entry missing required field '{field}'"
        assert isinstance(bug["error_count"], int), \
            f"func {bug['func_index']}: error_count must be an integer"
        assert isinstance(bug["priority_rank"], int), \
            f"func {bug['func_index']}: priority_rank must be an integer"
        assert bug["severity"] in ("critical", "high", "medium", "low"), \
            f"func {bug['func_index']}: invalid severity '{bug['severity']}'"


@pytest.mark.parametrize("expected", EXPECTED_REMEDIATION,
                         ids=[f"func{e['func_index']}_error_count" for e in EXPECTED_REMEDIATION])
def test_remediation_error_count(expected):
    data = load_remediation()
    by_idx = {b["func_index"]: b for b in data["bugs"]}
    idx = expected["func_index"]
    assert idx in by_idx, f"Missing remediation entry for func_index {idx}"
    actual_count = by_idx[idx]["error_count"]
    expected_count = expected["error_count"]
    assert actual_count == expected_count, (
        f"func {idx}: error_count={actual_count}, expected={expected_count}"
    )


@pytest.mark.parametrize("expected", EXPECTED_REMEDIATION,
                         ids=[f"func{e['func_index']}_severity" for e in EXPECTED_REMEDIATION])
def test_remediation_severity(expected):
    data = load_remediation()
    by_idx = {b["func_index"]: b for b in data["bugs"]}
    idx = expected["func_index"]
    assert by_idx[idx]["severity"] == expected["severity"], (
        f"func {idx}: severity='{by_idx[idx]['severity']}', expected='{expected['severity']}'"
    )


@pytest.mark.parametrize("expected", EXPECTED_REMEDIATION,
                         ids=[f"func{e['func_index']}_priority" for e in EXPECTED_REMEDIATION])
def test_remediation_priority_rank(expected):
    data = load_remediation()
    by_idx = {b["func_index"]: b for b in data["bugs"]}
    idx = expected["func_index"]
    assert by_idx[idx]["priority_rank"] == expected["priority_rank"], (
        f"func {idx}: priority_rank={by_idx[idx]['priority_rank']}, "
        f"expected={expected['priority_rank']}"
    )


def test_remediation_answer_hash():
    """Anti-cheat hash for remediation results."""
    data = load_remediation()
    bugs_sorted = sorted(data["bugs"], key=lambda x: x["func_index"])
    parts = []
    for b in bugs_sorted:
        parts.append(f"{b['func_index']}:{b['severity']}:{b['error_count']}:{b['priority_rank']}")
    canonical = "|".join(parts)
    h = hashlib.sha256(canonical.encode()).hexdigest()
    assert h == EXPECTED_REMED_HASH, (
        f"Remediation hash mismatch. Got '{h}', expected '{EXPECTED_REMED_HASH}'."
    )


# ===================================================================
# PART 3: Corrected binary tests
# ===================================================================

def test_fixed_binary_exists():
    assert os.path.exists("/app/challenge_fixed"), "/app/challenge_fixed not found"
    assert os.access("/app/challenge_fixed", os.X_OK), "/app/challenge_fixed is not executable"


def test_fixed_binary_runs():
    result = subprocess.run(
        ["/app/challenge_fixed", "0", "0"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, f"Fixed binary failed: {result.stderr}"


@pytest.mark.parametrize("idx", range(8), ids=[f"fixed_func{i}" for i in range(8)])
def test_fixed_binary_correctness(idx):
    """Verify each function in the fixed binary matches the spec across many inputs."""
    spec = SPEC[idx]
    op = spec["intended_operation"]
    d = spec["intended_divisor"]

    test_values = [0, 1, 2, d - 1, d, d + 1, 2 * d, 3 * d - 1,
                   100 * d, 12345, 67890, 999999]
    if op.startswith("s"):
        test_values += [-1, -2, -(d - 1), -d, -(d + 1), -2 * d,
                        -12345, -67890, -(2**31), 2**31 - 1]
    else:
        test_values += [2**31, 2**31 + 1, 2**32 - 2, 2**32 - 1]

    for val in test_values:
        actual = _run_fixed(idx, val)
        expected = _compute_spec_expected(op, d, val)
        assert actual == expected, (
            f"Fixed binary func {idx}: f({val}) = {actual}, "
            f"spec says {op} by {d} -> {expected}"
        )


@pytest.mark.parametrize("idx", [1, 4, 6],
                         ids=["fixed_func1_was_buggy", "fixed_func4_was_buggy", "fixed_func6_was_buggy"])
def test_fixed_binary_bugs_resolved(idx):
    """Verify the previously-buggy functions are now correct, specifically on known failure inputs."""
    spec = SPEC[idx]
    op = spec["intended_operation"]
    d = spec["intended_divisor"]

    # Test with inputs that the original binary got wrong
    if idx == 1:
        # signedness_mismatch: negative inputs were wrong
        failure_inputs = [-1, -10, -100, -1000, -(2**31)]
    elif idx == 4:
        # wrong_divisor: 127 vs 125 boundary values
        failure_inputs = [125, 126, 250, 251, -125, -126, 1000, -1000]
    elif idx == 6:
        # wrong_operation: div vs mod — almost all inputs differ
        failure_inputs = [1, 2, 3, 5, 6, 7, 8, 13, 14, -1, -2, -7, -13]
    else:
        failure_inputs = []

    for val in failure_inputs:
        actual = _run_fixed(idx, val)
        expected = _compute_spec_expected(op, d, val)
        assert actual == expected, (
            f"Fixed binary func {idx} still buggy: f({val}) = {actual}, "
            f"spec says {op} by {d} -> {expected}"
        )
