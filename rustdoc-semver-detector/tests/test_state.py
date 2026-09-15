
import json
import pytest


def load_report():
    with open("/app/report.json") as f:
        return json.load(f)


def get_violations_set():
    report = load_report()
    return {(v["type"], v["path"]) for v in report["violations"]}


# ── Format tests ──────────────────────────────────────────────────────────


class TestReportFormat:
    def test_report_exists_and_valid_json(self):
        report = load_report()
        assert isinstance(report, dict), "Report must be a JSON object"
        assert "violations" in report, "Report must have a 'violations' key"
        assert isinstance(report["violations"], list), "'violations' must be a list"

    def test_violations_have_required_fields(self):
        report = load_report()
        for v in report["violations"]:
            assert "type" in v, f"Violation missing 'type' field: {v}"
            assert "path" in v, f"Violation missing 'path' field: {v}"
            assert isinstance(v["type"], str), f"'type' must be a string: {v}"
            assert isinstance(v["path"], str), f"'path' must be a string: {v}"


# ── Expected violations (all 8 must be detected) ─────────────────────────


class TestExpectedViolations:
    def test_function_parameter_count_changed_compute(self):
        assert (
            "function_parameter_count_changed",
            "semver_testbed::compute",
        ) in get_violations_set(), (
            "Must detect that compute() changed from 2 to 3 parameters"
        )

    def test_function_missing_removed_fn(self):
        assert (
            "function_missing",
            "semver_testbed::removed_fn",
        ) in get_violations_set(), "Must detect that removed_fn was removed"

    def test_constructible_struct_adds_field_config(self):
        assert (
            "constructible_struct_adds_field",
            "semver_testbed::Config",
        ) in get_violations_set(), (
            "Must detect that Config (exhaustive, all-public) gained field 'timeout'"
        )

    def test_repr_c_removed_ffi_point(self):
        assert (
            "repr_c_removed",
            "semver_testbed::FfiPoint",
        ) in get_violations_set(), "Must detect that FfiPoint lost #[repr(C)]"

    def test_struct_pub_field_missing_data(self):
        assert (
            "struct_pub_field_missing",
            "semver_testbed::Data",
        ) in get_violations_set(), (
            "Must detect that Data lost public field 'payload'"
        )

    def test_enum_variant_missing_color(self):
        assert (
            "enum_variant_missing",
            "semver_testbed::Color",
        ) in get_violations_set(), "Must detect that Color lost variant 'Blue'"

    def test_trait_method_added_processor(self):
        assert (
            "trait_method_added",
            "semver_testbed::Processor",
        ) in get_violations_set(), (
            "Must detect that Processor gained required method 'version'"
        )

    def test_pub_module_level_const_missing_max_size(self):
        assert (
            "pub_module_level_const_missing",
            "semver_testbed::MAX_SIZE",
        ) in get_violations_set(), "Must detect that MAX_SIZE constant was removed"


# ── False-positive traps (must NOT be reported) ──────────────────────────


class TestNoFalsePositives:
    def test_non_exhaustive_struct_field_addition_not_reported(self):
        """Settings is #[non_exhaustive], so adding verbose is fine."""
        assert (
            "constructible_struct_adds_field",
            "semver_testbed::Settings",
        ) not in get_violations_set()

    def test_private_field_struct_addition_not_reported(self):
        """PrivateFieldStruct has a private _internal field, so it's not
        externally constructible. Adding pub extra is not breaking."""
        assert (
            "constructible_struct_adds_field",
            "semver_testbed::PrivateFieldStruct",
        ) not in get_violations_set()

    def test_non_exhaustive_enum_variant_addition_not_reported(self):
        """LogLevel is #[non_exhaustive], so adding Debug is fine."""
        assert (
            "enum_variant_missing",
            "semver_testbed::LogLevel",
        ) not in get_violations_set()

    def test_total_violation_count_reasonable(self):
        """Should have at least 8 violations (our expected set) and not
        an unreasonable number of spurious detections."""
        report = load_report()
        n = len(report["violations"])
        assert n >= 8, f"Too few violations ({n}), expected at least 8"
        assert n <= 15, f"Too many violations ({n}), likely false positives"
