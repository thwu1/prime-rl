
import subprocess
import pytest
import json
import hashlib
import os

QUERY_DIR = "/app/queries"
EXPECTED_DIR = "/app/expected"
DIAGNOSTIC_PATH = "/app/diagnostic.json"
NUM_QUERIES = 10

# SHA-256 of the canonical diagnostic JSON (sorted entries, sort_keys, compact separators)
EXPECTED_DIAG_HASH = "8b16caa22f11f632335e5b6bb85f7c58acd7144f4d95e5e1265921368a5397ba"

VALID_CATEGORIES = {
    "alias_shadow", "group_order_precedence", "quoted_case",
    "window_scope", "union_expression", "collate_expression",
    "unary_expression", "none",
}


def run_query(qnum):
    """Execute a query file via psql and return output lines."""
    result = subprocess.run(
        [
            "psql", "-d", "benchdb", "-U", "postgres",
            "-t", "-A", "-F", "|",
            "-f", f"{QUERY_DIR}/q{qnum}.sql",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail(
            f"q{qnum} execution error (exit {result.returncode}):\n{result.stderr}"
        )
    lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
    return lines


def load_expected(qnum):
    """Load expected output lines for a query."""
    with open(f"{EXPECTED_DIR}/q{qnum}.txt") as f:
        return [line.strip() for line in f if line.strip()]


@pytest.mark.parametrize("qnum", list(range(1, NUM_QUERIES + 1)))
def test_query_produces_expected_output(qnum):
    """Each query must produce output matching its expected file."""
    actual = run_query(qnum)
    expected = load_expected(qnum)
    assert len(actual) == len(expected), (
        f"q{qnum}: expected {len(expected)} rows, got {len(actual)}.\n"
        f"Expected:\n" + "\n".join(expected) + "\n"
        f"Actual:\n" + "\n".join(actual)
    )
    for i, (act, exp) in enumerate(zip(actual, expected)):
        assert act == exp, (
            f"q{qnum} row {i + 1} mismatch:\n"
            f"  expected: {exp}\n"
            f"  actual:   {act}"
        )


def test_diagnostic_json_exists():
    """diagnostic.json must exist at the expected path."""
    assert os.path.isfile(DIAGNOSTIC_PATH), (
        f"{DIAGNOSTIC_PATH} not found"
    )


def test_diagnostic_json_structure():
    """diagnostic.json must have correct structure and valid categories."""
    with open(DIAGNOSTIC_PATH) as f:
        data = json.load(f)

    assert "queries" in data, "diagnostic.json must have a 'queries' key"
    entries = data["queries"]
    assert len(entries) == NUM_QUERIES, (
        f"Expected {NUM_QUERIES} entries, got {len(entries)}"
    )

    seen_queries = set()
    for entry in entries:
        assert "query" in entry, f"Entry missing 'query' field: {entry}"
        assert "status" in entry, f"Entry missing 'status' field: {entry}"
        assert "category" in entry, f"Entry missing 'category' field: {entry}"

        qnum = entry["query"]
        assert isinstance(qnum, int) and 1 <= qnum <= NUM_QUERIES, (
            f"Invalid query number: {qnum}"
        )
        assert qnum not in seen_queries, f"Duplicate query number: {qnum}"
        seen_queries.add(qnum)

        assert entry["status"] in ("buggy", "correct"), (
            f"q{qnum}: status must be 'buggy' or 'correct', got '{entry['status']}'"
        )
        assert entry["category"] in VALID_CATEGORIES, (
            f"q{qnum}: invalid category '{entry['category']}'"
        )
        if entry["status"] == "correct":
            assert entry["category"] == "none", (
                f"q{qnum}: correct queries must have category 'none'"
            )
        else:
            assert entry["category"] != "none", (
                f"q{qnum}: buggy queries must have a specific category, not 'none'"
            )


def test_diagnostic_classification_correctness():
    """All query classifications must be correct (verified via hash)."""
    with open(DIAGNOSTIC_PATH) as f:
        data = json.load(f)

    entries = sorted(data["queries"], key=lambda x: x["query"])
    # Normalize to only the fields that matter for classification
    normalized = [
        {"category": e["category"], "query": e["query"], "status": e["status"]}
        for e in entries
    ]
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    actual_hash = hashlib.sha256(canonical.encode()).hexdigest()

    assert actual_hash == EXPECTED_DIAG_HASH, (
        "diagnostic.json classifications do not match expected values. "
        "Verify that each query is correctly classified as buggy/correct "
        "with the right category."
    )
