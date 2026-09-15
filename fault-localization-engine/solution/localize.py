#!/usr/bin/env python3
"""
Spectrum-Based Fault Localization using the Ochiai metric.

Dynamically loads a subject's source and test modules, collects per-test
line coverage via sys.settrace, computes Ochiai suspiciousness scores,
and outputs ranked results as JSON.

"""

import importlib.util
import json
import math
import os
import sys


def load_module_from_file(module_name, file_path):
    """Load a Python module from a file path, registering it in sys.modules."""
    file_path = os.path.abspath(file_path)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None:
        raise ImportError(f"Cannot create module spec for {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_test_with_coverage(test_func, source_path):
    """
    Execute a test function while collecting line coverage from source_path.
    Returns (set_of_covered_line_numbers, bool_test_passed).
    """
    covered_lines = set()
    abs_source = os.path.realpath(source_path)

    def trace_func(frame, event, arg):
        if event == "call":
            # Check if this frame is from the source file
            try:
                frame_file = os.path.realpath(frame.f_code.co_filename)
            except (ValueError, OSError):
                return None
            if frame_file == abs_source:
                return local_trace
            return None
        return None

    def local_trace(frame, event, arg):
        if event == "line":
            covered_lines.add(frame.f_lineno)
        return local_trace

    old_trace = sys.gettrace()
    sys.settrace(trace_func)
    passed = True
    try:
        test_func()
    except Exception:
        passed = False
    finally:
        sys.settrace(old_trace)

    return covered_lines, passed


def compute_ochiai(failed_s, passed_s, total_failed):
    """
    Compute Ochiai suspiciousness score.

    Ochiai(s) = failed(s) / sqrt(total_failed * (failed(s) + passed(s)))
    Returns 0.0 when the denominator is 0.
    """
    if total_failed == 0:
        return 0.0
    denom_sq = total_failed * (failed_s + passed_s)
    if denom_sq <= 0:
        return 0.0
    return failed_s / math.sqrt(denom_sq)


def discover_test_functions(module):
    """Find all callable attributes whose name starts with 'test_'."""
    tests = []
    for name in sorted(dir(module)):
        if name.startswith("test_"):
            func = getattr(module, name)
            if callable(func):
                tests.append((name, func))
    return tests


def localize_subject(subject_dir):
    """
    Perform spectrum-based fault localization on a single subject.
    Returns a dict with rankings.
    """
    subject_dir = os.path.abspath(subject_dir)
    subject_name = os.path.basename(subject_dir)
    source_file = os.path.join(subject_dir, "source.py")
    test_file = os.path.join(subject_dir, "tests.py")

    if not os.path.exists(source_file):
        raise FileNotFoundError(f"source.py not found in {subject_dir}")
    if not os.path.exists(test_file):
        raise FileNotFoundError(f"tests.py not found in {subject_dir}")

    # Ensure subject dir is on sys.path for 'from source import ...' to work
    if subject_dir not in sys.path:
        sys.path.insert(0, subject_dir)

    # Clear any previously cached 'source' module to avoid cross-contamination
    if "source" in sys.modules:
        del sys.modules["source"]

    # Load the source module first (tests.py imports from it)
    load_module_from_file("source", source_file)

    # Load the test module
    test_module_name = f"_tests_{subject_name}"
    if test_module_name in sys.modules:
        del sys.modules[test_module_name]
    test_mod = load_module_from_file(test_module_name, test_file)

    # Discover test functions
    tests = discover_test_functions(test_mod)
    if not tests:
        raise ValueError(f"No test functions found in {test_file}")

    # Run each test and collect coverage
    test_results = []
    for test_name, test_func in tests:
        covered, passed = run_test_with_coverage(test_func, source_file)
        test_results.append(
            {"name": test_name, "covered": covered, "passed": passed}
        )

    # Separate passing and failing
    pass_results = [r for r in test_results if r["passed"]]
    fail_results = [r for r in test_results if not r["passed"]]
    total_failed = len(fail_results)
    total_passed = len(pass_results)

    # Collect all covered lines across all tests
    all_lines = set()
    for r in test_results:
        all_lines.update(r["covered"])

    # Compute Ochiai score for each line
    rankings = []
    for line in sorted(all_lines):
        failed_s = sum(1 for r in fail_results if line in r["covered"])
        passed_s = sum(1 for r in pass_results if line in r["covered"])
        score = compute_ochiai(failed_s, passed_s, total_failed)
        rankings.append({"line": line, "score": round(score, 6)})

    # Sort by score descending, then by line number ascending for ties
    rankings.sort(key=lambda x: (-x["score"], x["line"]))

    return {
        "subject": subject_name,
        "total_tests": len(tests),
        "total_passed": total_passed,
        "total_failed": total_failed,
        "rankings": rankings,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 localize.py <subject_dir> [subject_dir2 ...]")
        print("       python3 localize.py --all")
        sys.exit(1)

    if sys.argv[1] == "--all":
        subjects_dir = "/app/subjects"
        subject_dirs = sorted(
            [
                os.path.join(subjects_dir, d)
                for d in os.listdir(subjects_dir)
                if os.path.isdir(os.path.join(subjects_dir, d))
            ]
        )
    else:
        subject_dirs = sys.argv[1:]

    os.makedirs("/app/results", exist_ok=True)

    for subject_dir in subject_dirs:
        subject_name = os.path.basename(os.path.normpath(subject_dir))
        result = localize_subject(subject_dir)

        output_path = f"/app/results/{subject_name}.json"
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)

        print(f"[{subject_name}] {result['total_passed']} pass, "
              f"{result['total_failed']} fail, "
              f"top line: {result['rankings'][0]['line']} "
              f"(score={result['rankings'][0]['score']})")


if __name__ == "__main__":
    main()
