#!/usr/bin/env python3
"""Fix all bugs in the evaluation pipeline and implement framework_analyzer.

"""

import json


def patch_file(path, replacements):
    """Apply a list of (old, new) string replacements to a file."""
    with open(path) as f:
        content = f.read()
    for old, new in replacements:
        assert old in content, f"Patch target not found in {path}: {old[:60]!r}..."
        content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)


# --- Fix pipeline_config.json: Go is statically typed; gtest parser name ---
with open("/app/pipeline_config.json") as f:
    config = json.load(f)

config["language_types"]["dynamic"].remove("Go")
config["language_types"]["static"].append("Go")
config["framework_parsers"]["gtest"] = "gtest"

with open("/app/pipeline_config.json", "w") as f:
    json.dump(config, f, indent=2)


# --- Fix parsers.py: three parser bugs ---
patch_file("/app/pipeline/parsers.py", [
    # JUnit: use last summary line, not first per-class match
    (
        '    match = re.search(pattern, test_log)\n'
        '    if not match:\n'
        '        return 0, 0\n'
        '    total = int(match.group(1))\n'
        '    failures = int(match.group(2))\n'
        '    errors = int(match.group(3))\n'
        '    skipped = int(match.group(4))',
        '    matches = re.findall(pattern, test_log)\n'
        '    if not matches:\n'
        '        return 0, 0\n'
        '    last = matches[-1]\n'
        '    total = int(last[0])\n'
        '    failures = int(last[1])\n'
        '    errors = int(last[2])\n'
        '    skipped = int(last[3])',
    ),
    # Cargo: exclude ignored tests from total
    (
        '    total = passed + failed + ignored',
        '    total = passed + failed',
    ),
    # Go: filter out parent tests when subtests exist
    (
        '    passed = sum(1 for status, _ in matches if status == "PASS")\n'
        '    total = len(matches)\n'
        '    return passed, total',
        '    all_tests = {}\n'
        '    for status, name in matches:\n'
        '        all_tests[name] = status\n'
        '\n'
        '    parents = set()\n'
        '    test_names = set(all_tests.keys())\n'
        '    for name in test_names:\n'
        '        for other in test_names:\n'
        '            if other.startswith(name + "/"):\n'
        '                parents.add(name)\n'
        '                break\n'
        '\n'
        '    passed = 0\n'
        '    total = 0\n'
        '    for name, status in all_tests.items():\n'
        '        if name not in parents:\n'
        '            total += 1\n'
        '            if status == "PASS":\n'
        '                passed += 1\n'
        '\n'
        '    return passed, total',
    ),
])

# --- Fix aggregator.py: include compile failures in avg_pass_rate denominator ---
patch_file("/app/pipeline/aggregator.py", [
    # compute_overall_stats: average over ALL projects, not just compiled
    (
        '    compiled_projects = [p for p in all_projects.values() if p["compile_success"]]\n'
        '    avg_pass = sum(\n'
        '        p["tests_passed"] / p["tests_total"] if p["tests_total"] > 0 else 0.0\n'
        '        for p in compiled_projects\n'
        '    ) / len(compiled_projects)',
        '    avg_pass = sum(\n'
        '        p["tests_passed"] / p["tests_total"] if p["tests_total"] > 0 else 0.0\n'
        '        for p in all_projects.values()\n'
        '    ) / n',
    ),
    # compute_directional_analysis: same fix for directional stats
    (
        '        compiled = [p for p in all_projs if p["compile_success"]]\n'
        '        avg_pass = (\n'
        '            sum(\n'
        '                p["tests_passed"] / p["tests_total"]\n'
        '                if p["tests_total"] > 0\n'
        '                else 0.0\n'
        '                for p in compiled\n'
        '            )\n'
        '            / len(compiled)\n'
        '            if compiled\n'
        '            else 0.0\n'
        '        )',
        '        avg_pass = sum(\n'
        '            p["tests_passed"] / p["tests_total"]\n'
        '            if p["tests_total"] > 0\n'
        '            else 0.0\n'
        '            for p in all_projs\n'
        '        ) / n',
    ),
])

# --- Implement framework_analyzer.py ---
FRAMEWORK_ANALYZER_CODE = '''\
"""Framework-level analysis for the translation benchmark.

Computes per-test-framework aggregate metrics across all benchmark projects.
"""


def compute_framework_analysis(all_projects, project_metadata):
    """Compute per-test-framework aggregate metrics.

    Groups projects by test framework and computes aggregate statistics
    including total tests executed, total tests passed, and pass rates.
    Compile-failed projects contribute 0 tests to their framework's totals.
    """
    frameworks = {}

    for proj_id, result in all_projects.items():
        meta = project_metadata[proj_id]
        fw = meta.get("test_framework", "unknown")

        if fw not in frameworks:
            frameworks[fw] = {
                "projects_using": 0,
                "projects_compiled": 0,
                "total_tests_executed": 0,
                "total_tests_passed": 0,
            }

        frameworks[fw]["projects_using"] += 1
        if result["compile_success"]:
            frameworks[fw]["projects_compiled"] += 1
        frameworks[fw]["total_tests_executed"] += result["tests_total"]
        frameworks[fw]["total_tests_passed"] += result["tests_passed"]

    for fw, metrics in frameworks.items():
        total = metrics["total_tests_executed"]
        passed = metrics["total_tests_passed"]
        metrics["aggregate_pass_rate"] = round(passed / total, 4) if total > 0 else 0.0

    return frameworks
'''

with open("/app/pipeline/framework_analyzer.py", "w") as f:
    f.write(FRAMEWORK_ANALYZER_CODE)

print("All pipeline bugs fixed and framework_analyzer implemented.")
