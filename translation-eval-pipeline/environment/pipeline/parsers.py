"""Test output parsers for various test frameworks."""

import re


def strip_ansi(text):
    """Remove ANSI escape sequences from text."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


def parse_junit(test_log):
    """Parse JUnit/Maven test output. Returns (passed, total)."""
    pattern = (
        r'Tests run:\s*(\d+),\s*Failures:\s*(\d+),'
        r'\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)'
    )
    match = re.search(pattern, test_log)
    if not match:
        return 0, 0
    total = int(match.group(1))
    failures = int(match.group(2))
    errors = int(match.group(3))
    skipped = int(match.group(4))
    passed = total - failures - errors - skipped
    return passed, total


def parse_cargo_test(test_log):
    """Parse cargo test output. Returns (passed, total)."""
    pattern = (
        r'test result:.*?(\d+)\s+passed;\s+(\d+)\s+failed;'
        r'\s+(\d+)\s+ignored'
    )
    match = re.search(pattern, test_log)
    if not match:
        return 0, 0
    passed = int(match.group(1))
    failed = int(match.group(2))
    ignored = int(match.group(3))
    total = passed + failed + ignored
    return passed, total


def parse_pytest(test_log):
    """Parse pytest output. Returns (passed, total)."""
    clean = strip_ansi(test_log)
    passed = failed = error = 0

    m = re.search(r'(\d+)\s+passed', clean)
    if m:
        passed = int(m.group(1))

    m = re.search(r'(\d+)\s+failed', clean)
    if m:
        failed = int(m.group(1))

    m = re.search(r'(\d+)\s+error', clean)
    if m:
        error = int(m.group(1))

    total = passed + failed + error
    return passed, total


def parse_go_test(test_log):
    """Parse go test output. Returns (passed, total)."""
    result_pattern = r'---\s+(PASS|FAIL):\s+(\S+)\s+\('
    matches = re.findall(result_pattern, test_log)
    if not matches:
        return 0, 0

    passed = sum(1 for status, _ in matches if status == "PASS")
    total = len(matches)
    return passed, total


def parse_gtest(test_log):
    """Parse Google Test output. Returns (passed, total)."""
    passed_match = re.search(r'\[\s+PASSED\s+\]\s+(\d+)\s+tests?', test_log)
    total_match = re.search(
        r'\[==========\]\s+(\d+)\s+tests?\s+from\s+\d+\s+test\s+suites?\s+ran',
        test_log,
    )
    if passed_match and total_match:
        return int(passed_match.group(1)), int(total_match.group(1))
    return 0, 0


PARSERS = {
    "junit": parse_junit,
    "cargo_test": parse_cargo_test,
    "pytest": parse_pytest,
    "go_test": parse_go_test,
    "gtest": parse_gtest,
}
