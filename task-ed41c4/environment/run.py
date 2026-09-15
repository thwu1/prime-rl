#!/usr/bin/env python3
"""FHIR Data Quality Pipeline — run analysis and generate report."""

import json
import os
import sys

from engine.store import ResourceStore
from engine.references import ReferenceChecker
from engine.search import SearchEngine
from engine.report import ReportGenerator


def main():
    data_dir = "/app/data"
    output_path = "/app/output/report.json"

    store = ResourceStore()
    store.load_directory(data_dir)

    checker = ReferenceChecker(store)
    search = SearchEngine(store)
    reporter = ReportGenerator(store, checker, search)

    report = reporter.generate()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)

    print(f"Report written to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
