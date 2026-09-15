
import json
import os
import pytest

REPORT_PATH = "/app/report.json"


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), "report.json not found at /app/report.json"
    with open(REPORT_PATH) as f:
        return json.load(f)


def test_report_exists():
    assert os.path.exists(REPORT_PATH), "report.json must exist at /app/report.json"


def test_report_valid_json():
    with open(REPORT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "report.json must be a JSON object"


# --- Mustpass totals (extension-gated filtering) ---

def test_raw_mustpass_total(report):
    assert report["raw_mustpass_total"] == 194, (
        f"Expected 194 raw mustpass tests (176 core + 18 extension-gated), "
        f"got {report['raw_mustpass_total']}")


def test_applicable_mustpass_total(report):
    assert report["applicable_mustpass_total"] == 176, (
        f"Expected 176 applicable mustpass tests (excluding ray-tracing and "
        f"mesh-shader extension-gated groups), got {report['applicable_mustpass_total']}")


# --- Test coverage ---

def test_tests_with_results(report):
    assert report["tests_with_results"] == 171, (
        f"Expected 171 tests with results, got {report['tests_with_results']}")


def test_tests_missing_count(report):
    assert report["tests_missing_count"] == 5, (
        f"Expected 5 missing tests, got {report['tests_missing_count']}")


def test_missing_tests_exact(report):
    expected = sorted([
        "dEQP-VK.api.device_init.create_instance_layer_name",
        "dEQP-VK.compute.pipeline.basic.concurrent_compute",
        "dEQP-VK.spirv_assembly.instruction.compute.16bit_storage.uniform.array_stride_16_to_64",
        "dEQP-VK.synchronization.basic.event.multi_secondary_cmd_buf",
        "dEQP-VK.memory.allocation.oom.host_oom",
    ])
    actual = sorted(report["tests_missing"])
    assert actual == expected, f"Missing tests mismatch:\n  expected: {expected}\n  actual:   {actual}"


# --- Raw status counts (after duplicate + cross-fraction resolution, before waivers) ---

def test_raw_status_pass(report):
    assert report["raw_status_counts"]["Pass"] == 138, (
        f"Expected 138 raw Pass (139 minus 1 cross-fraction conflict resolved to "
        f"QualityWarning), got {report['raw_status_counts'].get('Pass')}")


def test_raw_status_not_supported(report):
    assert report["raw_status_counts"]["NotSupported"] == 14


def test_raw_status_quality_warning(report):
    assert report["raw_status_counts"]["QualityWarning"] == 5, (
        f"Expected 5 raw QualityWarning (4 from non-info tests + 1 from "
        f"cross-fraction conflict on info.platform), got "
        f"{report['raw_status_counts'].get('QualityWarning')}")


def test_raw_status_compatibility_warning(report):
    assert report["raw_status_counts"]["CompatibilityWarning"] == 1


def test_raw_status_fail(report):
    assert report["raw_status_counts"]["Fail"] == 9, (
        f"Expected 9 raw Fail, got {report['raw_status_counts'].get('Fail')}")


def test_raw_status_internal_error(report):
    assert report["raw_status_counts"]["InternalError"] == 2


def test_raw_status_crash(report):
    assert report["raw_status_counts"]["Crash"] == 1


def test_raw_status_resource_error(report):
    assert report["raw_status_counts"]["ResourceError"] == 1


# --- Waivers (with expired waiver detection) ---

def test_waived_tests_count(report):
    assert report["waived_tests_count"] == 4, (
        f"Expected 4 waived tests (f64 glob waiver only; "
        f"create_device_unsupported_features waiver is expired), "
        f"got {report['waived_tests_count']}")


def test_waived_tests_exact(report):
    expected = sorted([
        "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.f64.scalar",
        "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.f64.vec2",
        "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.f64.vec3",
        "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.f64.vec4",
    ])
    actual = sorted(report["waived_tests"])
    assert actual == expected, f"Waived tests mismatch:\n  expected: {expected}\n  actual:   {actual}"


def test_expired_waivers_count(report):
    assert report["expired_waivers_count"] == 1, (
        f"Expected 1 expired waiver (create_device_unsupported_features, "
        f"validUntil=1.3.7.0 < submission CTS 1.3.8.0), "
        f"got {report['expired_waivers_count']}")


def test_expired_waivers_exact(report):
    expected = ["dEQP-VK.api.device_init.create_device_unsupported_features"]
    actual = sorted(report["expired_waivers"])
    assert actual == expected, (
        f"Expired waivers mismatch:\n  expected: {expected}\n  actual:   {actual}")


# --- Effective status counts (after waiver application) ---

def test_effective_status_waiver(report):
    assert report["effective_status_counts"]["Waiver"] == 4


def test_effective_status_fail(report):
    assert report["effective_status_counts"]["Fail"] == 5, (
        f"Expected 5 effective Fail (9 raw - 4 waived), "
        f"got {report['effective_status_counts'].get('Fail')}")


def test_effective_pass(report):
    assert report["effective_status_counts"]["Pass"] == 138


def test_effective_quality_warning(report):
    assert report["effective_status_counts"]["QualityWarning"] == 5


# --- Conformance violations ---

def test_conformance_violations_count(report):
    assert report["conformance_violations_count"] == 9, (
        f"Expected 9 violations, got {report['conformance_violations_count']}")


def test_conformance_violations_exact(report):
    expected = sorted([
        "dEQP-VK.api.device_init.create_device_unsupported_features",
        "dEQP-VK.compute.pipeline.basic.copy_ssbo_bounds",
        "dEQP-VK.compute.pipeline.basic.copy_image_to_ssbo_large",
        "dEQP-VK.compute.pipeline.basic.image_atomic_op_local_size_8",
        "dEQP-VK.synchronization.basic.timeline_semaphore.wait_before_signal",
        "dEQP-VK.memory.allocation.random.mixed_sizes",
        "dEQP-VK.memory.allocation.oom.device_oom",
        "dEQP-VK.memory.mapping.basic.flush_invalidate",
        "dEQP-VK.spirv_assembly.instruction.compute.16bit_storage.uniform.scalar_uint_16_to_32",
    ])
    actual = sorted(report["conformance_violations"])
    assert actual == expected, (
        f"Violations mismatch:\n  expected: {expected}\n  actual:   {actual}")


# --- Intra-fraction duplicates ---

def test_duplicate_results_count(report):
    assert report["duplicate_results_count"] == 1


def test_duplicate_results_exact(report):
    expected = ["dEQP-VK.spirv_assembly.instruction.compute.16bit_storage.uniform.scalar_uint_16_to_32"]
    assert sorted(report["duplicate_results"]) == expected


# --- Cross-fraction conflicts ---

def test_cross_fraction_conflicts_count(report):
    assert report["cross_fraction_conflicts_count"] == 1, (
        f"Expected 1 cross-fraction conflict (info.platform: Pass vs "
        f"QualityWarning across fractions), got "
        f"{report['cross_fraction_conflicts_count']}")


def test_cross_fraction_conflicts_exact(report):
    expected = ["dEQP-VK.info.platform"]
    actual = sorted(report["cross_fraction_conflicts"])
    assert actual == expected, (
        f"Cross-fraction conflicts mismatch:\n  expected: {expected}\n  "
        f"actual:   {actual}")


# --- Fractions and mandatory ---

def test_fraction_count(report):
    assert report["fraction_count"] == 3


def test_fraction_mandatory_complete(report):
    assert report["fraction_mandatory_complete"] is True


# --- Statement and overall ---

def test_statement_valid(report):
    assert report["statement_valid"] is False, "STATEMENT is missing the OS field"


def test_statement_errors_mention_os(report):
    errors = report.get("statement_errors", [])
    assert any("OS" in e for e in errors), (
        f"Expected statement error about missing OS field, got: {errors}")


def test_overall_conformant(report):
    assert report["overall_conformant"] is False
