
import os
import pytest


def test_output_file_exists():
    assert os.path.exists("/app/output.txt"), "/app/output.txt not found"


def test_output_not_empty():
    with open("/app/output.txt") as f:
        content = f.read().strip()
    assert len(content) > 0, "/app/output.txt is empty"


def test_correct_line_count():
    with open("/app/output.txt") as f:
        actual = [line.strip() for line in f if line.strip()]
    with open("/tests/expected_output.txt") as f:
        expected = [line.strip() for line in f if line.strip()]
    assert len(actual) == len(expected), (
        f"Expected {len(expected)} answer lines, got {len(actual)}"
    )


def test_all_answers_correct():
    with open("/app/output.txt") as f:
        actual = [line.strip() for line in f if line.strip()]
    with open("/tests/expected_output.txt") as f:
        expected = [line.strip() for line in f if line.strip()]

    assert len(actual) == len(expected), (
        f"Line count mismatch: expected {len(expected)}, got {len(actual)}"
    )

    mismatches = []
    for i, (a, e) in enumerate(zip(actual, expected)):
        if a != e:
            mismatches.append((i + 1, e, a))
            if len(mismatches) >= 10:
                break

    if mismatches:
        total = sum(1 for a, e in zip(actual, expected) if a.strip() != e.strip())
        msg = f"{total} mismatches out of {len(expected)} queries. First few:\n"
        for line_num, exp, act in mismatches:
            msg += f"  Query {line_num}: expected {exp}, got {act}\n"
        pytest.fail(msg)
