
import json
import os
import pytest

REPORT_PATH = "/app/diagnosis.json"


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


def test_report_has_required_fields(report):
    required = [
        "target_pid",
        "baseline_cpu_samples",
        "regression_cpu_samples",
        "new_functions",
        "removed_functions",
        "top_regressions",
        "root_cause_groups",
    ]
    for field in required:
        assert field in report, f"Missing required field: {field}"


def test_target_pid(report):
    assert report["target_pid"] == 4821


def test_baseline_cpu_samples(report):
    assert report["baseline_cpu_samples"] == 945, (
        f"Expected 945, got {report['baseline_cpu_samples']}"
    )


def test_regression_cpu_samples(report):
    assert report["regression_cpu_samples"] == 1661, (
        f"Expected 1661, got {report['regression_cpu_samples']}"
    )


def test_new_functions(report):
    expected = sorted([
        "base64_encode",
        "buffer_realloc",
        "build_query",
        "compute_shared_secret",
        "encoding_fallback",
        "expand_key_material",
        "file_write",
        "format_timestamp",
        "generate_params",
        "json_encode",
        "parse_response",
        "udp_send",
        "utf8_check_byte",
        "utf8_check_sequence",
        "wait_response",
    ])
    actual = report["new_functions"]
    assert isinstance(actual, list), "new_functions must be a list"
    assert actual == expected, (
        f"new_functions mismatch.\n"
        f"Expected: {expected}\n"
        f"Got:      {actual}\n"
        f"Missing:  {sorted(set(expected) - set(actual))}\n"
        f"Extra:    {sorted(set(actual) - set(expected))}"
    )


def test_removed_functions(report):
    expected = sorted(["cache_hit_return", "cached_session_resume"])
    actual = report["removed_functions"]
    assert isinstance(actual, list), "removed_functions must be a list"
    assert actual == expected, (
        f"removed_functions mismatch. Expected: {expected}, Got: {actual}"
    )


def test_top_regressions_count(report):
    entries = report["top_regressions"]
    assert isinstance(entries, list), "top_regressions must be a list"
    assert len(entries) == 10, f"Expected 10 entries, got {len(entries)}"


def test_top_regressions_functions(report):
    entries = report["top_regressions"]
    actual_funcs = [e["function"] for e in entries]
    expected_funcs = [
        "buffer_realloc",
        "compute_shared_secret",
        "utf8_check_byte",
        "generate_params",
        "wait_response",
        "utf8_check_sequence",
        "expand_key_material",
        "escape_string",
        "json_encode",
        "write_field",
    ]
    assert set(actual_funcs) == set(expected_funcs), (
        f"Top-10 function set mismatch.\n"
        f"Expected: {expected_funcs}\n"
        f"Got:      {actual_funcs}\n"
        f"Missing:  {sorted(set(expected_funcs) - set(actual_funcs))}\n"
        f"Extra:    {sorted(set(actual_funcs) - set(expected_funcs))}"
    )


def test_top_regressions_order(report):
    entries = report["top_regressions"]
    impacts = [e["impact"] for e in entries]
    for i in range(len(impacts) - 1):
        assert impacts[i] >= impacts[i + 1], (
            f"top_regressions not sorted descending at index {i}: "
            f"{impacts[i]} < {impacts[i+1]}"
        )


def test_top_regressions_values(report):
    entries = report["top_regressions"]
    nf = 1661.0 / 945.0

    expected_impacts = {
        "buffer_realloc": 43.0,
        "compute_shared_secret": 42.0,
        "utf8_check_byte": 38.0,
        "generate_params": 35.0,
        "wait_response": 31.0,
        "utf8_check_sequence": 29.0,
        "expand_key_material": 28.0,
        "escape_string": 62.0 - 20.0 * nf,
        "json_encode": 25.0,
        "write_field": 95.0 - 40.0 * nf,
    }

    for entry in entries:
        func = entry["function"]
        if func in expected_impacts:
            expected = expected_impacts[func]
            actual = entry["impact"]
            tolerance = max(abs(expected) * 0.05, 1.0)
            assert abs(actual - expected) < tolerance, (
                f"Impact for {func}: expected ~{expected:.2f}, got {actual:.2f}"
            )


def test_root_cause_groups_keys(report):
    groups = report["root_cause_groups"]
    assert isinstance(groups, dict), "root_cause_groups must be a dict"
    expected_keys = sorted([
        "buffer_realloc",
        "cache_miss",
        "derive_key_full",
        "log_request_body",
        "validate_encoding",
    ])
    actual_keys = sorted(groups.keys())
    assert actual_keys == expected_keys, (
        f"root_cause_groups keys mismatch.\n"
        f"Expected: {expected_keys}\n"
        f"Got:      {actual_keys}"
    )


def test_root_cause_groups_values(report):
    groups = report["root_cause_groups"]
    expected = {
        "buffer_realloc": ["buffer_realloc"],
        "cache_miss": sorted([
            "build_query", "parse_response", "udp_send", "wait_response"
        ]),
        "derive_key_full": sorted([
            "compute_shared_secret", "expand_key_material", "generate_params"
        ]),
        "log_request_body": sorted([
            "base64_encode", "file_write", "format_timestamp", "json_encode"
        ]),
        "validate_encoding": sorted([
            "encoding_fallback", "utf8_check_byte", "utf8_check_sequence"
        ]),
    }
    for key, expected_val in expected.items():
        assert key in groups, f"Missing group key: {key}"
        actual_val = groups[key]
        assert actual_val == expected_val, (
            f"Group '{key}' mismatch.\n"
            f"Expected: {expected_val}\n"
            f"Got:      {actual_val}"
        )
