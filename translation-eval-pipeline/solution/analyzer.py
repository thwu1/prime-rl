#!/usr/bin/env python3
"""Solution: Translation benchmark results analyzer.

"""

import json
import os
import re

DATA_DIR = "/data/benchmark"
RESULTS_FILE = "/app/results.json"

DYNAMIC_LANGUAGES = {"Python", "JavaScript", "Ruby", "Matlab"}
STATIC_LANGUAGES = {"Java", "C", "C++", "C#", "Go", "Rust"}


def strip_ansi(text):
    """Remove ANSI escape sequences from text."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


def detect_compile_success(build_log, meta):
    """Detect whether compilation succeeded from build log content."""
    if "No compilation step required" in build_log:
        return True

    build_tool = meta.get("build_tool", "")

    if build_tool == "maven":
        return "BUILD SUCCESS" in build_log
    elif build_tool == "cargo":
        if "error[E" in build_log:
            return False
        if "could not compile" in build_log:
            return False
        if "error: aborting" in build_log:
            return False
        return True
    elif build_tool == "go":
        if "cannot find" in build_log or "undefined:" in build_log:
            return False
        return True
    elif build_tool == "cmake":
        if re.search(r'error:', build_log, re.IGNORECASE):
            return False
        return True
    elif build_tool == "none":
        return True

    return True


def parse_junit_tests(test_log):
    """Parse JUnit/Maven test output. Returns (passed, total)."""
    pattern = r'Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)'
    matches = re.findall(pattern, test_log)
    if not matches:
        return 0, 0
    last = matches[-1]
    total = int(last[0])
    failures = int(last[1])
    errors = int(last[2])
    skipped = int(last[3])
    passed = total - failures - errors - skipped
    return passed, total


def parse_cargo_tests(test_log):
    """Parse cargo test output. Returns (passed, total)."""
    pattern = r'test result:.*?(\d+)\s+passed;\s+(\d+)\s+failed;\s+(\d+)\s+ignored'
    match = re.search(pattern, test_log)
    if match:
        passed = int(match.group(1))
        failed = int(match.group(2))
        total = passed + failed
        return passed, total
    return 0, 0


def parse_pytest_tests(test_log):
    """Parse pytest output. Returns (passed, total). Strips ANSI codes first."""
    clean = strip_ansi(test_log)
    passed = 0
    failed = 0
    error = 0

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


def parse_go_tests(test_log):
    """Parse go test output. Returns (passed, total).

    For subtests (name contains /), count only leaf-level tests.
    A test is a parent if any other test name starts with its name + '/'.
    """
    result_pattern = r'---\s+(PASS|FAIL):\s+(\S+)\s+\('
    matches = re.findall(result_pattern, test_log)
    if not matches:
        return 0, 0

    all_tests = {}
    for status, name in matches:
        all_tests[name] = status

    parents = set()
    test_names = set(all_tests.keys())
    for name in test_names:
        prefix = name + "/"
        for other in test_names:
            if other.startswith(prefix):
                parents.add(name)
                break

    passed = 0
    total = 0
    for name, status in all_tests.items():
        if name not in parents:
            total += 1
            if status == "PASS":
                passed += 1

    return passed, total


def parse_gtest_tests(test_log):
    """Parse Google Test output. Returns (passed, total)."""
    passed_match = re.search(r'\[\s+PASSED\s+\]\s+(\d+)\s+tests?', test_log)
    total_match = re.search(
        r'\[==========\]\s+(\d+)\s+tests?\s+from\s+\d+\s+test\s+suites?\s+ran',
        test_log,
    )
    if passed_match and total_match:
        passed = int(passed_match.group(1))
        total = int(total_match.group(1))
        return passed, total
    return 0, 0


def parse_tests(test_log, meta):
    """Dispatch to framework-specific parser. Returns (passed, total)."""
    framework = meta.get("test_framework", "")
    if framework == "junit":
        return parse_junit_tests(test_log)
    elif framework == "cargo_test":
        return parse_cargo_tests(test_log)
    elif framework == "pytest":
        return parse_pytest_tests(test_log)
    elif framework == "go_test":
        return parse_go_tests(test_log)
    elif framework == "gtest":
        return parse_gtest_tests(test_log)
    return 0, 0


def analyze():
    """Main analysis: read data, parse, aggregate, write results."""
    with open(os.path.join(DATA_DIR, "manifest.json"), "r") as f:
        manifest = json.load(f)

    projects_result = {}

    for proj_info in manifest["projects"]:
        proj_id = proj_info["id"]
        proj_dir = os.path.join(DATA_DIR, "projects", proj_id)

        with open(os.path.join(proj_dir, "meta.json"), "r") as f:
            meta = json.load(f)

        with open(os.path.join(proj_dir, "build.log"), "r") as f:
            build_log = f.read()

        with open(os.path.join(proj_dir, "test.log"), "r") as f:
            test_log = f.read()

        compile_success = detect_compile_success(build_log, meta)

        if compile_success:
            passed, total = parse_tests(test_log, meta)
        else:
            passed, total = 0, 0

        pass_rate = passed / total if total > 0 else 0.0
        all_pass = total > 0 and passed == total

        projects_result[proj_id] = {
            "source_lang": meta["source_language"],
            "target_lang": meta["target_language"],
            "compile_success": compile_success,
            "tests_passed": passed,
            "tests_total": total,
            "pass_rate": round(pass_rate, 4),
            "all_tests_pass": all_pass,
        }

    # Aggregate by language pair
    language_pairs = {}
    for proj_id, proj in projects_result.items():
        pair_key = f"{proj['source_lang']}_to_{proj['target_lang']}"
        language_pairs.setdefault(pair_key, []).append(proj)

    lp_result = {}
    for pair_key, projs in language_pairs.items():
        n = len(projs)
        compile_count = sum(1 for p in projs if p["compile_success"])
        success_count = sum(1 for p in projs if p["all_tests_pass"])
        avg_pass = sum(
            p["tests_passed"] / p["tests_total"] if p["tests_total"] > 0 else 0.0
            for p in projs
        ) / n

        lp_result[pair_key] = {
            "num_projects": n,
            "compile_rate": round(compile_count / n, 4),
            "success_rate": round(success_count / n, 4),
            "avg_pass_rate": round(avg_pass, 4),
        }

    # Overall statistics
    total_projects = len(projects_result)
    total_compile = sum(1 for p in projects_result.values() if p["compile_success"])
    total_success = sum(1 for p in projects_result.values() if p["all_tests_pass"])
    overall_avg_pass = sum(
        p["tests_passed"] / p["tests_total"] if p["tests_total"] > 0 else 0.0
        for p in projects_result.values()
    ) / total_projects

    overall = {
        "total_projects": total_projects,
        "compile_rate": round(total_compile / total_projects, 4),
        "success_rate": round(total_success / total_projects, 4),
        "avg_pass_rate": round(overall_avg_pass, 4),
    }

    # Directional analysis
    d2s_pairs = []
    s2d_pairs = []

    for pair_key, projs in language_pairs.items():
        src = projs[0]["source_lang"]
        tgt = projs[0]["target_lang"]

        if src in DYNAMIC_LANGUAGES and tgt in STATIC_LANGUAGES:
            d2s_pairs.append(pair_key)
        elif src in STATIC_LANGUAGES and tgt in DYNAMIC_LANGUAGES:
            s2d_pairs.append(pair_key)

    def compute_directional_stats(pair_keys):
        all_projs = []
        for pk in pair_keys:
            all_projs.extend(language_pairs[pk])

        n = len(all_projs)
        if n == 0:
            return {
                "pairs": sorted(pair_keys),
                "num_projects": 0,
                "compile_rate": 0.0,
                "success_rate": 0.0,
                "avg_pass_rate": 0.0,
            }

        compile_count = sum(1 for p in all_projs if p["compile_success"])
        success_count = sum(1 for p in all_projs if p["all_tests_pass"])
        avg_pass = sum(
            p["tests_passed"] / p["tests_total"] if p["tests_total"] > 0 else 0.0
            for p in all_projs
        ) / n

        return {
            "pairs": sorted(pair_keys),
            "num_projects": n,
            "compile_rate": round(compile_count / n, 4),
            "success_rate": round(success_count / n, 4),
            "avg_pass_rate": round(avg_pass, 4),
        }

    directional = {
        "dynamic_to_static": compute_directional_stats(d2s_pairs),
        "static_to_dynamic": compute_directional_stats(s2d_pairs),
    }

    result = {
        "projects": projects_result,
        "language_pairs": lp_result,
        "overall": overall,
        "directional_analysis": directional,
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Results written to {RESULTS_FILE}")


if __name__ == "__main__":
    analyze()
