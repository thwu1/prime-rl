
"""Tests for perf-regression-triage task."""

import json
import os
import subprocess
import time


def test_triage_classification():
    """Verify triage.json correctly classifies all anomalous functions."""
    assert os.path.exists("/app/triage.json"), "triage.json not found"

    with open("/app/triage.json") as f:
        data = json.load(f)

    assert "triage" in data, "Missing 'triage' key in triage.json"
    entries = data["triage"]
    assert len(entries) >= 6, (
        f"Expected at least 6 triage entries covering all anomalous functions, "
        f"got {len(entries)}"
    )

    # Build function->classification mapping
    classified = {}
    for entry in entries:
        assert "function" in entry, f"Missing 'function' in entry: {entry}"
        assert "classification" in entry, f"Missing 'classification' in entry: {entry}"
        assert "justification" in entry, f"Missing 'justification' in entry: {entry}"
        assert len(entry["justification"]) > 20, (
            f"Justification too short for {entry['function']}: must provide "
            f"evidence-based reasoning"
        )
        valid_cls = {"genuine_regression", "intentional_addition", "expected_overhead"}
        assert entry["classification"] in valid_cls, (
            f"Invalid classification '{entry['classification']}' for "
            f"{entry['function']}. Must be one of: {valid_cls}"
        )
        classified[entry["function"]] = entry["classification"]

    # Check the 4 genuine regressions are correctly identified
    regression_checks = [
        (["check_config", "config_valid"], "check_config_valid"),
        (["alloc_record", "record_buf"], "alloc_record_buf"),
        (["normalize", "dedup"], "normalize_text/dedup"),
        (["rebuild", "rebuild_index"], "rebuild_index"),
    ]
    for patterns, name in regression_checks:
        found = False
        for func, cls in classified.items():
            if any(p in func.lower() for p in patterns) and cls == "genuine_regression":
                found = True
                break
        assert found, (
            f"Genuine regression '{name}' not correctly classified as "
            f"genuine_regression. Classifications: {classified}"
        )

    # Decoy 1: sanitize_key must be present and NOT classified as genuine_regression
    sanitize_found = False
    for func, cls in classified.items():
        if "sanitize" in func.lower():
            sanitize_found = True
            assert cls != "genuine_regression", (
                f"sanitize_key incorrectly classified as genuine_regression. "
                f"It is an intentional security addition — removing it would "
                f"re-introduce input validation vulnerabilities."
            )
    assert sanitize_found, (
        f"sanitize_key not found in triage — all anomalous functions must be "
        f"classified. Functions found: {list(classified.keys())}"
    )

    # Decoy 2: accumulate_stats must be present and NOT classified as genuine_regression
    stats_found = False
    for func, cls in classified.items():
        if "accumulate" in func.lower() or (
            "stats" in func.lower() and "stat" != func.lower()
        ):
            stats_found = True
            assert cls != "genuine_regression", (
                f"accumulate_stats incorrectly classified as genuine_regression. "
                f"It is expected monitoring overhead — its sample increase is "
                f"proportional to workload growth."
            )
    assert stats_found, (
        f"accumulate_stats not found in triage — all anomalous functions must "
        f"be classified. Functions found: {list(classified.keys())}"
    )


def test_compile_and_correct():
    """Verify fixed workload.c compiles and produces correct output."""
    assert os.path.exists("/app/workload.c"), "workload.c not found"

    result = subprocess.run(
        ["gcc", "-O2", "-o", "/app/workload", "/app/workload.c"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"

    result = subprocess.run(
        ["/app/workload", "/app/test_data.txt", "/app/index_data.txt",
         "/tmp/test_output.txt"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Execution failed:\n{result.stderr}"

    with open("/tmp/test_output.txt") as f:
        actual = f.read().strip()
    with open("/app/reference_output.txt") as f:
        expected = f.read().strip()

    assert actual == expected, (
        f"Output mismatch.\nExpected:\n{expected}\n\nActual:\n{actual}"
    )


def test_decoy_functions_preserved():
    """Verify intentional additions were not removed during optimization."""
    with open("/app/workload.c") as f:
        code = f.read()

    # sanitize_key must still be defined AND called in the processing pipeline
    assert code.count("sanitize_key") >= 2, (
        "sanitize_key appears fewer than 2 times in the fixed code — it must "
        "be both defined and called. It is an intentional security addition "
        "that should NOT be removed when fixing performance regressions."
    )

    # accumulate_stats must still be defined AND called
    assert code.count("accumulate_stats") >= 2, (
        "accumulate_stats appears fewer than 2 times in the fixed code — it "
        "must be both defined and called. It is intentional monitoring "
        "instrumentation that should NOT be removed."
    )


def _generate_large_test(data_path, index_path, n_records, n_index):
    """Generate large test data for performance testing."""
    keys = [f"key_{i:05d}" for i in range(n_index)]

    with open(index_path, "w") as f:
        for i, key in enumerate(keys):
            f.write(f"{key}\tdata_{i:05d}\n")

    with open(data_path, "w") as f:
        for i in range(n_records):
            key = keys[i % n_index]
            text = f"Sample text for record number {i} with letters aabbccdd"
            f.write(f"{key}\t{text}\n")


def test_performance():
    """Verify fixed program runs fast enough (genuine regressions are fixed)."""
    if not os.path.exists("/app/workload"):
        result = subprocess.run(
            ["gcc", "-O2", "-o", "/app/workload", "/app/workload.c"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"

    _generate_large_test("/tmp/large_test.txt", "/tmp/large_index.txt", 2000, 500)

    start = time.time()
    result = subprocess.run(
        ["/app/workload", "/tmp/large_test.txt", "/tmp/large_index.txt",
         "/tmp/large_output.txt"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    elapsed = time.time() - start

    assert result.returncode == 0, f"Execution failed:\n{result.stderr}"
    assert os.path.getsize("/tmp/large_output.txt") > 0, "Output file is empty"
    assert elapsed < 10, (
        f"Too slow: {elapsed:.2f}s (must be < 10s). "
        f"Genuine performance regressions may not be fully fixed."
    )


def test_impact_analysis():
    """Verify Amdahl's law impact analysis for genuine regressions."""
    assert os.path.exists("/app/impact_analysis.json"), (
        "impact_analysis.json not found"
    )

    with open("/app/impact_analysis.json") as f:
        data = json.load(f)

    assert "analysis" in data, "Missing 'analysis' key in impact_analysis.json"
    entries = data["analysis"]
    assert len(entries) == 4, (
        f"Expected 4 analysis entries (one per genuine regression), "
        f"got {len(entries)}"
    )

    required_fields = {
        "function", "before_samples", "after_samples", "regression_delta",
        "total_after_samples", "fraction_of_profile", "amdahl_projected_speedup"
    }

    for entry in entries:
        for field in required_fields:
            assert field in entry, (
                f"Missing field '{field}' in impact analysis entry for "
                f"{entry.get('function', '?')}"
            )

    # Verify function coverage — all 4 genuine regressions must be analyzed
    functions = {e["function"] for e in entries}
    assert any("check_config" in f or "config_valid" in f for f in functions), \
        f"Missing check_config_valid in analysis. Functions: {functions}"
    assert any("alloc_record" in f or "record_buf" in f for f in functions), \
        f"Missing alloc_record_buf in analysis. Functions: {functions}"
    assert any("normalize" in f or "dedup" in f for f in functions), \
        f"Missing normalize_text/dedup in analysis. Functions: {functions}"
    assert any("rebuild" in f or "rebuild_index" in f for f in functions), \
        f"Missing rebuild_index in analysis. Functions: {functions}"

    # Verify Amdahl's law calculations are self-consistent
    total_fraction = 0
    for entry in entries:
        frac = entry["fraction_of_profile"]
        speedup = entry["amdahl_projected_speedup"]
        delta = entry["regression_delta"]
        total_samples = entry["total_after_samples"]
        total_fraction += frac

        assert 0.0 < frac < 1.0, (
            f"fraction_of_profile {frac} out of range for {entry['function']}"
        )
        assert speedup > 1.0, (
            f"Speedup {speedup} should be > 1.0 for {entry['function']}"
        )

        # Verify fraction = delta / total_samples (within tolerance)
        expected_frac = delta / total_samples if total_samples > 0 else 0
        assert abs(frac - expected_frac) < 0.05, (
            f"fraction_of_profile {frac} inconsistent with "
            f"delta/total ({expected_frac:.4f}) for {entry['function']}"
        )

        # Amdahl's law: speedup = 1 / (1 - fraction)
        expected_speedup = 1.0 / (1.0 - frac)
        relative_error = abs(speedup - expected_speedup) / expected_speedup
        assert relative_error < 0.15, (
            f"Amdahl's law inconsistency for {entry['function']}: "
            f"fraction={frac}, claimed speedup={speedup}, "
            f"expected speedup={expected_speedup:.3f}, error={relative_error:.1%}"
        )

    # Total regression fraction should account for most of the profile overhead
    assert 0.5 < total_fraction < 0.95, (
        f"Total regression fraction {total_fraction:.3f} out of expected range "
        f"(0.5-0.95). The genuine regressions should account for the majority "
        f"of the degraded profile's overhead."
    )


def test_perf_guardian():
    """Verify perf_guardian.py automated regression detection tool."""
    assert os.path.exists("/app/perf_guardian.py"), "perf_guardian.py not found"

    # Run with default threshold
    result = subprocess.run(
        ["python3", "/app/perf_guardian.py",
         "/app/profile_before.folded", "/app/profile_after.folded"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"perf_guardian.py failed:\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

    output = json.loads(result.stdout)
    assert "regressions" in output, (
        "Missing 'regressions' key in perf_guardian output"
    )

    regressions = output["regressions"]
    assert len(regressions) > 0, "No regressions detected by perf_guardian.py"

    # Verify entry structure
    for r in regressions:
        assert "function" in r, f"Missing 'function' in regression entry: {r}"
        assert "delta" in r, f"Missing 'delta' in regression entry: {r}"
        assert "severity" in r, f"Missing 'severity' in regression entry: {r}"
        assert r["severity"] in ("critical", "warning", "info"), (
            f"Invalid severity '{r['severity']}' for {r['function']}"
        )

    # All 4 genuine regressions must be detected
    all_funcs = [r["function"] for r in regressions]
    has_stat = any(
        "stat" in f or "check_config" in f or "path_lookupat" in f
        for f in all_funcs
    )
    has_alloc = any("alloc_record" in f for f in all_funcs)
    has_memmove = any("memmove" in f or "dedup" in f for f in all_funcs)
    has_rebuild = any("rebuild" in f for f in all_funcs)

    assert has_stat, (
        f"check_config_valid/stat regression not detected by perf_guardian. "
        f"Detected functions: {all_funcs}"
    )
    assert has_alloc, (
        f"alloc_record_buf regression not detected by perf_guardian. "
        f"Detected functions: {all_funcs}"
    )
    assert has_memmove, (
        f"memmove/dedup regression not detected by perf_guardian. "
        f"Detected functions: {all_funcs}"
    )
    assert has_rebuild, (
        f"rebuild_index regression not detected by perf_guardian. "
        f"Detected functions: {all_funcs}"
    )

    # Test --threshold parameter reduces output
    result2 = subprocess.run(
        ["python3", "/app/perf_guardian.py",
         "/app/profile_before.folded", "/app/profile_after.folded",
         "--threshold", "50000"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result2.returncode == 0, (
        f"perf_guardian with --threshold failed: {result2.stderr}"
    )
    output2 = json.loads(result2.stdout)
    assert len(output2["regressions"]) < len(regressions), (
        "Higher --threshold should reduce the number of detected regressions"
    )
