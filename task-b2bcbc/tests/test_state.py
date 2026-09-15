"""Verification: apply specific mutations and check the agent's test suite catches them.
Also verify equivalent mutations are annotated with pragma.
Also verify tool output files (mutation_analysis.json, coverage.json) exist and are valid."""

import json
import os
import shutil
import subprocess

import pytest

APP_DIR = "/app"

# Non-equivalent mutations: the agent's test suite must detect each one.
MUTATIONS = [
    {
        "file": "intervallib/intervals.py",
        "original": "    return a[0] < b[1] and b[0] < a[1]",
        "mutated":  "    return a[0] <= b[1] and b[0] < a[1]",
        "id": "M01_overlaps_left_boundary",
    },
    {
        "file": "intervallib/intervals.py",
        "original": "    return a[0] < b[1] and b[0] < a[1]",
        "mutated":  "    return a[0] < b[1] and b[0] <= a[1]",
        "id": "M02_overlaps_right_boundary",
    },
    {
        "file": "intervallib/intervals.py",
        "original": "        if start <= result[-1][1]:",
        "mutated":  "        if start < result[-1][1]:",
        "id": "M03_merge_adjacent",
    },
    {
        "file": "intervallib/intervals.py",
        "original": "        if start > current:",
        "mutated":  "        if start >= current:",
        "id": "M04_complement_start",
    },
    {
        "file": "intervallib/intervals.py",
        "original": "    if current < hi:",
        "mutated":  "    if current <= hi:",
        "id": "M05_complement_end",
    },
    {
        "file": "intervallib/intervals.py",
        "original": "            total += ce - cs",
        "mutated":  "            total += ce + cs",
        "id": "M06_coverage_subtraction",
    },
    {
        "file": "intervallib/intervals.py",
        "original": "    return total / (hi - lo)",
        "mutated":  "    return total / (hi + lo)",
        "id": "M07_coverage_denominator",
    },
    {
        "file": "intervallib/scheduling.py",
        "original": "            if indexed[mid][1][1] <= target_start:",
        "mutated":  "            if indexed[mid][1][1] < target_start:",
        "id": "M08_weighted_schedule_boundary",
    },
    {
        "file": "intervallib/scheduling.py",
        "original": "        time += proc_time",
        "mutated":  "        time = proc_time",
        "id": "M09_edf_accumulation",
    },
    {
        "file": "intervallib/solver.py",
        "original": "            if dp[0] >= dp[1] or ds[0] >= ds[1]:",
        "mutated":  "            if dp[0] > dp[1] or ds[0] >= ds[1]:",
        "id": "M12_empty_domain_check",
    },
    {
        "file": "intervallib/solver.py",
        "original": "    while t < time_end:",
        "mutated":  "    while t <= time_end:",
        "id": "M13_load_profile_boundary",
    },
    {
        "file": "intervallib/solver.py",
        "original": "        if load > capacity:",
        "mutated":  "        if load >= capacity:",
        "id": "M14_overload_threshold",
    },
    {
        "file": "intervallib/solver.py",
        "original": "        while (len(active) >= resource_capacity or not ready) and active:",
        "mutated":  "        while (len(active) > resource_capacity or not ready) and active:",
        "id": "M15_capacity_enforcement",
    },
]


def test_original_passes():
    """The test suite must pass on the original unmodified library code."""
    result = subprocess.run(
        ["python3", "-m", "pytest", os.path.join(APP_DIR, "tests"), "-x", "-q"],
        capture_output=True,
        text=True,
        cwd=APP_DIR,
        env={**os.environ, "PYTHONPATH": APP_DIR, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, (
        f"Tests fail on original code!\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda m: m["id"])
def test_mutation_killed(mutation, tmp_path):
    """Each non-equivalent mutation must be detected (cause at least one test failure)."""
    # Copy the entire /app to a temp directory
    app_copy = str(tmp_path / "app")
    shutil.copytree(
        APP_DIR,
        app_copy,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".mutmut-cache", "mutants"),
    )

    # Fix any conftest.py that might hardcode /app
    tests_dir = os.path.join(app_copy, "tests")
    for fname in os.listdir(tests_dir):
        if fname == "conftest.py":
            fpath = os.path.join(tests_dir, fname)
            with open(fpath) as f:
                content = f.read()
            if "/app" in content:
                content = content.replace('"/app"', f'"{app_copy}"')
                content = content.replace("'/app'", f"'{app_copy}'")
                with open(fpath, "w") as f:
                    f.write(content)

    # Apply the mutation
    filepath = os.path.join(app_copy, mutation["file"])
    with open(filepath) as f:
        content = f.read()

    assert mutation["original"] in content, (
        f"Original string not found in {mutation['file']}. "
        f"The library code may have been modified.\n"
        f"Looking for: {mutation['original']!r}"
    )

    modified = content.replace(mutation["original"], mutation["mutated"], 1)
    assert modified != content, "Mutation was not applied (identical strings)"

    with open(filepath, "w") as f:
        f.write(modified)

    # Run the agent's test suite against the mutated code
    result = subprocess.run(
        ["python3", "-m", "pytest", tests_dir, "-x", "-q", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=app_copy,
        env={**os.environ, "PYTHONPATH": app_copy, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=60,
    )

    assert result.returncode != 0, (
        f"Mutation SURVIVED (tests still pass): {mutation['id']}\n"
        f"Applied: {mutation['original']!r} -> {mutation['mutated']!r}\n"
        f"stdout:\n{result.stdout}"
    )


def test_equivalent_M10_annotated():
    """M10 (es > earliest_start[v] -> es >= ...) is equivalent.
    The agent must annotate this line with '# pragma: no mutate'."""
    filepath = os.path.join(APP_DIR, "intervallib/scheduling.py")
    with open(filepath) as f:
        content = f.read()
    for line in content.splitlines():
        if "es > earliest_start[v]" in line or "es >= earliest_start[v]" in line:
            assert "pragma: no mutate" in line, (
                "Line with 'es > earliest_start[v]' in scheduling.py must have "
                "'# pragma: no mutate' annotation to mark it as an equivalent mutation"
            )
            return
    pytest.fail("Could not find the target line (es > earliest_start[v]) in scheduling.py")


def test_equivalent_M11_annotated():
    """M11 (dp[1] > ds[1] -> dp[1] >= ...) is equivalent.
    The agent must annotate this line with '# pragma: no mutate'."""
    filepath = os.path.join(APP_DIR, "intervallib/solver.py")
    with open(filepath) as f:
        content = f.read()
    for line in content.splitlines():
        if "dp[1] > ds[1]" in line or "dp[1] >= ds[1]" in line:
            assert "pragma: no mutate" in line, (
                "Line with 'dp[1] > ds[1]' in solver.py must have "
                "'# pragma: no mutate' annotation to mark it as an equivalent mutation"
            )
            return
    pytest.fail("Could not find the target line (dp[1] > ds[1]) in solver.py")


def test_mutation_analysis_report():
    """The agent must produce a mutation_analysis.json report with valid structure."""
    report_path = os.path.join(APP_DIR, "mutation_analysis.json")
    assert os.path.exists(report_path), (
        "mutation_analysis.json not found at /app/ — "
        "this report must be generated as part of the mutation analysis workflow"
    )
    with open(report_path) as f:
        report = json.load(f)
    required_keys = {"total_mutants", "killed", "survived", "equivalent", "mutation_score"}
    missing = required_keys - set(report.keys())
    assert not missing, f"mutation_analysis.json missing required keys: {missing}"
    assert report["total_mutants"] == 15, (
        f"Expected 15 total mutants (from mutations.json catalog), got {report['total_mutants']}"
    )
    assert isinstance(report["mutation_score"], (int, float)), "mutation_score must be numeric"
    assert report["mutation_score"] > 0.8, (
        f"Mutation score too low: {report['mutation_score']} — "
        "expected high kill rate across the 15 cataloged mutations"
    )


def test_coverage_report():
    """The agent must produce a coverage.json report using the coverage tool."""
    coverage_path = os.path.join(APP_DIR, "coverage.json")
    assert os.path.exists(coverage_path), (
        "coverage.json not found at /app/ — "
        "use 'coverage run -m pytest tests/' then 'coverage json' to generate it"
    )
    with open(coverage_path) as f:
        cov_data = json.load(f)
    assert "totals" in cov_data, (
        "coverage.json missing 'totals' key — invalid coverage report format"
    )
    pct = cov_data["totals"].get("percent_covered", 0)
    assert pct >= 80, (
        f"Line coverage too low: {pct}% — expected >= 80% with mutation-killing tests added"
    )
