"""Main entry point for the IDoFT standalone format checker."""


import csv
import json
import os

from utils import ErrorTracker
from common_checks import (
    check_url, check_sha, check_module_path, check_test_name,
    check_sort, check_duplicates,
)
from pr_checker import (
    check_category, check_status, check_status_consistency,
)


def audit_file(tracker, filename, filepath):
    """Run all validation checks on a single CSV file."""
    is_python = filename == "py-data.csv"

    with open(filepath, newline="") as f:
        rows = list(csv.DictReader(f))

    for i, row in enumerate(rows):
        row_num = i + 1

        check_url(tracker, filename, row_num, row)
        check_sha(tracker, filename, row_num, row)

        if not is_python:
            check_module_path(tracker, filename, row_num, row)

        check_test_name(tracker, filename, row_num, row, is_python)
        check_category(tracker, filename, row_num, row)
        check_status(tracker, filename, row_num, row)
        check_status_consistency(tracker, filename, row_num, row)

    check_sort(tracker, filename, rows, is_python)
    check_duplicates(tracker, filename, rows, is_python)

    return rows


def main():
    data_dir = os.environ.get("DATA_DIR", "/app/data")
    output_path = os.environ.get("OUTPUT_PATH", "/app/checker_report.json")

    tracker = ErrorTracker()

    pr_rows = audit_file(tracker, "pr-data.csv",
                         os.path.join(data_dir, "pr-data.csv"))
    gr_rows = audit_file(tracker, "gr-data.csv",
                         os.path.join(data_dir, "gr-data.csv"))
    audit_file(tracker, "py-data.csv",
               os.path.join(data_dir, "py-data.csv"))

    report = tracker.get_report()

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Validation complete. Found {report['summary']['total']} violations.")
    for fname, count in sorted(report["summary"]["by_file"].items()):
        print(f"  {fname}: {count}")


if __name__ == "__main__":
    main()
