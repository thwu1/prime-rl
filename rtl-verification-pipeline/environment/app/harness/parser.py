"""Parses simulation output."""
import re


def parse_results(log_path):
    """Parse simulation log for test results."""
    with open(log_path) as f:
        content = f.read()

    match = re.search(r'\{RESULTS\}\s+(\d+)\s+pass,\s+(\d+)\s+fail', content)

    if match:
        passed = int(match.group(1))
        failed = int(match.group(2))
        return {"total": passed + failed, "passed": passed, "failed": failed}

    return {"total": 0, "passed": 0, "failed": 0}
