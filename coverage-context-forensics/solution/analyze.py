#!/usr/bin/env python3
"""Analyze coverage data and produce test impact report.

Queries the combined .coverage SQLite database using coverage.py's Python API
to produce /app/impact_report.json with:
- coverage_summary: per-file line and branch counts
- context_mapping: which test covers which files
- exclusive_coverage: lines only covered by a single test
- affected_tests: tests covering lines listed in changes.json
"""

import json
import os
import tempfile
import coverage as cov_module
from coverage.sqldata import CoverageData

APP_DIR = "/app"
COVERAGE_DB = os.path.join(APP_DIR, ".coverage")
CHANGES_FILE = os.path.join(APP_DIR, "changes.json")
REPORT_FILE = os.path.join(APP_DIR, "impact_report.json")


def get_relative_path(filepath):
    """Get path relative to APP_DIR, handling both abs and rel inputs."""
    if os.path.isabs(filepath):
        return os.path.relpath(filepath, APP_DIR)
    return filepath


def is_calclib_file(filepath):
    """Check if filepath is under calclib/."""
    rel = get_relative_path(filepath)
    return rel.startswith("calclib/") or rel.startswith("calclib" + os.sep)


def compute_coverage_summary():
    """Compute per-file coverage stats using coverage.py's json report."""
    cov = cov_module.Coverage()
    cov.load()

    tmpfile = tempfile.mktemp(suffix=".json")
    cov.json_report(outfile=tmpfile)
    with open(tmpfile) as f:
        report = json.load(f)
    os.unlink(tmpfile)

    summary = {}
    for fname, fdata in report["files"].items():
        s = fdata["summary"]
        summary[fname] = {
            "lines_covered": s["covered_lines"],
            "lines_total": s["num_statements"],
            "branches_covered": s["covered_branches"],
            "branches_total": s["num_branches"],
        }

    return summary


def compute_context_mapping(data):
    """Build mapping from test context to covered files."""
    context_to_files = {}

    for fname in data.measured_files():
        if not is_calclib_file(fname):
            continue
        rel = get_relative_path(fname)
        ctx_by_line = data.contexts_by_lineno(fname)
        for line, contexts in ctx_by_line.items():
            for ctx in contexts:
                if ctx:
                    if ctx not in context_to_files:
                        context_to_files[ctx] = set()
                    context_to_files[ctx].add(rel)

    return {ctx: sorted(files) for ctx, files in sorted(context_to_files.items())}


def compute_exclusive_coverage(data):
    """Find lines exclusively covered by a single test context."""
    line_contexts = {}

    for fname in data.measured_files():
        if not is_calclib_file(fname):
            continue
        rel = get_relative_path(fname)
        ctx_by_line = data.contexts_by_lineno(fname)
        for line, contexts in ctx_by_line.items():
            non_empty = {c for c in contexts if c}
            if non_empty:
                line_contexts[(rel, line)] = non_empty

    exclusive = {}
    for (fname, line), contexts in line_contexts.items():
        if len(contexts) == 1:
            ctx = next(iter(contexts))
            if ctx not in exclusive:
                exclusive[ctx] = {}
            if fname not in exclusive[ctx]:
                exclusive[ctx][fname] = []
            exclusive[ctx][fname].append(line)

    for ctx in exclusive:
        for fname in exclusive[ctx]:
            exclusive[ctx][fname].sort()

    return dict(sorted(exclusive.items()))


def compute_affected_tests(data):
    """Find tests that cover any of the changed lines."""
    with open(CHANGES_FILE) as f:
        changes = json.load(f)

    affected = set()
    for change in changes["changes"]:
        target_file = change["file"]
        target_lines = set(change["lines"])

        for fname in data.measured_files():
            rel = get_relative_path(fname)
            if rel == target_file:
                ctx_by_line = data.contexts_by_lineno(fname)
                for line in target_lines:
                    if line in ctx_by_line:
                        for ctx in ctx_by_line[line]:
                            if ctx:
                                affected.add(ctx)
                break

    return sorted(affected)


def main():
    os.chdir(APP_DIR)

    data = CoverageData(COVERAGE_DB)
    data.read()

    report = {
        "coverage_summary": compute_coverage_summary(),
        "context_mapping": compute_context_mapping(data),
        "exclusive_coverage": compute_exclusive_coverage(data),
        "affected_tests": compute_affected_tests(data),
    }

    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Impact report written to {REPORT_FILE}")


if __name__ == "__main__":
    main()
