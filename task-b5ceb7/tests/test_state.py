"""Tests for GPU shared memory profiling pipeline debug and optimization results."""


import json
import os

import pytest

RESULTS_PATH = "/app/results.json"

EXPECTED_METRICS = {
    "sequential": {"wavefronts": 1, "total_conflicts": 0, "conflict_free": True},
    "column_major": {"wavefronts": 32, "total_conflicts": 31, "conflict_free": False},
    "padded_column": {"wavefronts": 1, "total_conflicts": 0, "conflict_free": True},
    "stride_7": {"wavefronts": 1, "total_conflicts": 0, "conflict_free": True},
    "broadcast_groups": {"wavefronts": 2, "total_conflicts": 5, "conflict_free": False},
    "quadratic_scatter": {"wavefronts": 2, "total_conflicts": 3, "conflict_free": False},
}

EXPECTED_STRATEGIES = {
    "no_padding": {"stride": 32, "wavefronts": 32, "total_conflicts": 31},
    "pad_1": {"stride": 33, "wavefronts": 1, "total_conflicts": 0},
    "pad_2": {"stride": 34, "wavefronts": 2, "total_conflicts": 16},
    "xor_swizzle": {"stride": 32, "wavefronts": 1, "total_conflicts": 0},
}


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Results must be a JSON object"
    return data


# --- Bug identification tests ---


def test_bugs_found_count(results):
    """Exactly 3 bugs must be identified."""
    bugs = results.get("bugs_found", [])
    assert isinstance(bugs, list), "bugs_found must be an array"
    assert len(bugs) == 3, f"Expected 3 bugs, found {len(bugs)}"


def _bugs_text(results):
    """Concatenate all bug entries into a searchable string."""
    bugs = results.get("bugs_found", [])
    parts = []
    for b in bugs:
        for v in b.values():
            parts.append(str(v).lower())
    return " ".join(parts)


def test_bug_num_banks_identified(results):
    """One bug must identify the num_banks error (16 -> 32)."""
    text = _bugs_text(results)
    has_16 = "16" in text
    has_32 = "32" in text
    has_bank = "bank" in text
    assert has_16 and has_32 and has_bank, (
        "Expected a bug entry identifying num_banks wrong_value=16, correct_value=32"
    )


def test_bug_wavefronts_logic_identified(results):
    """One bug must identify the sum-vs-max wavefronts error."""
    text = _bugs_text(results)
    has_sum = "sum" in text
    has_max = "max" in text
    has_wavefront = "wavefront" in text or "wave" in text
    assert has_sum and has_max and (has_wavefront or "sim" in text), (
        "Expected a bug entry identifying wavefronts calculated as sum instead of max"
    )


def test_bug_stride_formula_identified(results):
    """One bug must identify the stride_7 formula error (t*24 -> t*28)."""
    text = _bugs_text(results)
    has_24 = "24" in text
    has_28 = "28" in text
    has_stride = "stride" in text or "formula" in text or "kernel" in text
    assert has_24 and has_28 and has_stride, (
        "Expected a bug entry identifying stride_7 formula wrong_value=t*24, correct_value=t*28"
    )


# --- Corrected metrics tests ---


def test_corrected_metrics_present(results):
    """All 6 kernel names must be present in corrected_metrics."""
    cm = results.get("corrected_metrics", {})
    for name in EXPECTED_METRICS:
        assert name in cm, f"Missing kernel '{name}' in corrected_metrics"


@pytest.mark.parametrize("kernel_name", list(EXPECTED_METRICS.keys()))
def test_corrected_wavefronts(results, kernel_name):
    cm = results["corrected_metrics"][kernel_name]
    expected = EXPECTED_METRICS[kernel_name]["wavefronts"]
    assert int(cm["wavefronts"]) == expected, (
        f"{kernel_name}: wavefronts expected {expected}, got {cm['wavefronts']}"
    )


@pytest.mark.parametrize("kernel_name", list(EXPECTED_METRICS.keys()))
def test_corrected_total_conflicts(results, kernel_name):
    cm = results["corrected_metrics"][kernel_name]
    expected = EXPECTED_METRICS[kernel_name]["total_conflicts"]
    assert int(cm["total_conflicts"]) == expected, (
        f"{kernel_name}: total_conflicts expected {expected}, got {cm['total_conflicts']}"
    )


@pytest.mark.parametrize("kernel_name", list(EXPECTED_METRICS.keys()))
def test_corrected_conflict_free(results, kernel_name):
    cm = results["corrected_metrics"][kernel_name]
    expected = EXPECTED_METRICS[kernel_name]["conflict_free"]
    actual = cm["conflict_free"]
    if isinstance(actual, str):
        actual = actual.lower() == "true"
    assert actual == expected, (
        f"{kernel_name}: conflict_free expected {expected}, got {cm['conflict_free']}"
    )


# --- Optimization analysis tests ---


def test_optimization_has_column_major(results):
    oa = results.get("optimization_analysis", {})
    assert "column_major" in oa, "optimization_analysis must contain 'column_major'"


def test_optimization_has_all_strategies(results):
    strategies = results["optimization_analysis"]["column_major"].get("strategies", {})
    for sname in EXPECTED_STRATEGIES:
        assert sname in strategies, f"Missing strategy '{sname}' in optimization_analysis"


@pytest.mark.parametrize("strategy_name", list(EXPECTED_STRATEGIES.keys()))
def test_strategy_wavefronts(results, strategy_name):
    s = results["optimization_analysis"]["column_major"]["strategies"][strategy_name]
    expected = EXPECTED_STRATEGIES[strategy_name]["wavefronts"]
    assert int(s["wavefronts"]) == expected, (
        f"Strategy {strategy_name}: wavefronts expected {expected}, got {s['wavefronts']}"
    )


@pytest.mark.parametrize("strategy_name", list(EXPECTED_STRATEGIES.keys()))
def test_strategy_total_conflicts(results, strategy_name):
    s = results["optimization_analysis"]["column_major"]["strategies"][strategy_name]
    expected = EXPECTED_STRATEGIES[strategy_name]["total_conflicts"]
    assert int(s["total_conflicts"]) == expected, (
        f"Strategy {strategy_name}: total_conflicts expected {expected}, got {s['total_conflicts']}"
    )


@pytest.mark.parametrize("strategy_name", list(EXPECTED_STRATEGIES.keys()))
def test_strategy_stride(results, strategy_name):
    s = results["optimization_analysis"]["column_major"]["strategies"][strategy_name]
    expected = EXPECTED_STRATEGIES[strategy_name]["stride"]
    assert int(s["stride"]) == expected, (
        f"Strategy {strategy_name}: stride expected {expected}, got {s['stride']}"
    )


def test_recommendation_is_optimal(results):
    """Recommendation must be a conflict-free strategy (pad_1 or xor_swizzle)."""
    rec = results["optimization_analysis"]["column_major"].get("recommendation", "")
    assert rec in ("pad_1", "xor_swizzle"), (
        f"Recommendation must be 'pad_1' or 'xor_swizzle', got '{rec}'"
    )
