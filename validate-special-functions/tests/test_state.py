
import pytest
import json
import os
from mpmath import mp, mpf, gamma, besselj, airyai, airybi, pi, sqrt, fabs

mp.dps = 60

EXPECTED_ERROR_IDS = {"gamma_2_3", "bi_1", "ai_prime_2", "j0_10", "ai_prime_0"}

REFERENCE_VALUES = {
    "gamma_1_3": gamma(mpf(1) / 3),
    "gamma_2_3": gamma(mpf(2) / 3),
    "gamma_1_4": gamma(mpf(1) / 4),
    "gamma_3_4": gamma(mpf(3) / 4),
    "ai_1": airyai(mpf(1)),
    "ai_prime_1": airyai(mpf(1), derivative=1),
    "bi_1": airybi(mpf(1)),
    "bi_prime_1": airybi(mpf(1), derivative=1),
    "ai_2": airyai(mpf(2)),
    "ai_prime_2": airyai(mpf(2), derivative=1),
    "bi_2": airybi(mpf(2)),
    "bi_prime_2": airybi(mpf(2), derivative=1),
    "j0_1": besselj(0, mpf(1)),
    "j1_1": besselj(1, mpf(1)),
    "j2_1": besselj(2, mpf(1)),
    "j0_10": besselj(0, mpf(10)),
    "ai_0": airyai(mpf(0)),
    "bi_0": airybi(mpf(0)),
    "ai_prime_0": airyai(mpf(0), derivative=1),
    "bi_prime_0": airybi(mpf(0), derivative=1),
}


@pytest.fixture(scope="module")
def report():
    report_path = "/app/audit_report.json"
    assert os.path.exists(report_path), "audit_report.json not found at /app/audit_report.json"
    with open(report_path, "r") as f:
        return json.load(f)


class TestReportStructure:
    def test_report_has_errors(self, report):
        assert "errors" in report, "Report must contain 'errors' key"

    def test_report_has_validated_entries(self, report):
        assert "validated_entries" in report, "Report must contain 'validated_entries' key"

    def test_error_count(self, report):
        assert len(report["errors"]) == 5, (
            f"Expected exactly 5 errors, found {len(report['errors'])}"
        )

    def test_validated_count(self, report):
        assert len(report["validated_entries"]) == 15, (
            f"Expected exactly 15 validated entries, found {len(report['validated_entries'])}"
        )


class TestErrorDetection:
    def test_correct_error_ids_found(self, report):
        found_ids = set(e["id"] for e in report["errors"])
        assert found_ids == EXPECTED_ERROR_IDS, (
            f"Expected error IDs {EXPECTED_ERROR_IDS}, found {found_ids}"
        )

    def test_no_false_positives(self, report):
        found_ids = set(e["id"] for e in report["errors"])
        false_positives = found_ids - EXPECTED_ERROR_IDS
        assert not false_positives, (
            f"Correct entries incorrectly flagged as errors: {false_positives}"
        )

    def test_no_false_negatives(self, report):
        found_ids = set(e["id"] for e in report["errors"])
        missed = EXPECTED_ERROR_IDS - found_ids
        assert not missed, f"Errors missed: {missed}"


class TestCorrectedValues:
    def test_gamma_2_3_corrected(self, report):
        self._check_correction(report, "gamma_2_3")

    def test_bi_1_corrected(self, report):
        self._check_correction(report, "bi_1")

    def test_ai_prime_2_corrected(self, report):
        self._check_correction(report, "ai_prime_2")

    def test_j0_10_corrected(self, report):
        self._check_correction(report, "j0_10")

    def test_ai_prime_0_corrected(self, report):
        self._check_correction(report, "ai_prime_0")

    def _check_correction(self, report, entry_id):
        error_entry = None
        for e in report["errors"]:
            if e["id"] == entry_id:
                error_entry = e
                break
        assert error_entry is not None, f"Error entry {entry_id} not found"
        assert "corrected_value" in error_entry, (
            f"Error entry {entry_id} missing corrected_value"
        )
        corrected = mpf(error_entry["corrected_value"])
        ref = REFERENCE_VALUES[entry_id]
        if ref != 0:
            rel_err = fabs(corrected - ref) / fabs(ref)
        else:
            rel_err = fabs(corrected - ref)
        assert rel_err < mpf("1e-40"), (
            f"Corrected value for {entry_id} not accurate to 40 digits, "
            f"relative error = {float(rel_err):.2e}"
        )


class TestIdentityValidation:
    def test_at_least_3_identity_types(self, report):
        identity_types = set()
        for entry in report.get("validated_entries", []):
            vd = entry.get("validation", {})
            it = vd.get("identity_type", "")
            if it:
                identity_types.add(it)
        for entry in report.get("errors", []):
            db = entry.get("detected_by", {})
            it = db.get("identity_type", "")
            if it:
                identity_types.add(it)
        assert len(identity_types) >= 3, (
            f"Expected >= 3 identity types, got {identity_types}"
        )

    def test_reflection_identity_used(self, report):
        all_types = self._collect_identity_types(report)
        assert any("reflection" in t.lower() for t in all_types), (
            "Gamma reflection formula must be used for validation"
        )

    def test_wronskian_identity_used(self, report):
        all_types = self._collect_identity_types(report)
        assert any("wronskian" in t.lower() for t in all_types), (
            "Airy Wronskian identity must be used for validation"
        )

    def test_bessel_recurrence_used(self, report):
        all_types = self._collect_identity_types(report)
        assert any("bessel" in t.lower() or "recurrence" in t.lower() for t in all_types), (
            "Bessel recurrence identity must be used for validation"
        )

    def test_each_error_has_detection_method(self, report):
        for err in report["errors"]:
            assert "detected_by" in err, (
                f"Error {err['id']} missing 'detected_by' field"
            )
            assert "identity_type" in err["detected_by"], (
                f"Error {err['id']} missing 'identity_type' in detected_by"
            )

    def test_each_validated_has_validation(self, report):
        for entry in report["validated_entries"]:
            assert "validation" in entry, (
                f"Validated entry {entry['id']} missing 'validation' field"
            )
            assert "identity_type" in entry["validation"], (
                f"Validated entry {entry['id']} missing 'identity_type' in validation"
            )

    def _collect_identity_types(self, report):
        types = set()
        for entry in report.get("validated_entries", []):
            it = entry.get("validation", {}).get("identity_type", "")
            if it:
                types.add(it)
        for entry in report.get("errors", []):
            it = entry.get("detected_by", {}).get("identity_type", "")
            if it:
                types.add(it)
        return types


class TestDLMFIdentitiesHold:
    """Verify that the corrected values actually satisfy DLMF identities."""

    def _get_corrected_value(self, report, entry_id):
        """Get corrected value from errors, or original from validated."""
        for err in report["errors"]:
            if err["id"] == entry_id:
                return mpf(err["corrected_value"])
        for val in report["validated_entries"]:
            if val["id"] == entry_id:
                return REFERENCE_VALUES[entry_id]
        return REFERENCE_VALUES[entry_id]

    def test_gamma_reflection_1_3(self, report):
        g13 = self._get_corrected_value(report, "gamma_1_3")
        g23 = self._get_corrected_value(report, "gamma_2_3")
        lhs = g13 * g23
        rhs = 2 * pi / sqrt(3)
        assert fabs(lhs - rhs) < mpf("1e-40"), "Γ(1/3)·Γ(2/3) != 2π/√3"

    def test_gamma_reflection_1_4(self, report):
        g14 = self._get_corrected_value(report, "gamma_1_4")
        g34 = self._get_corrected_value(report, "gamma_3_4")
        lhs = g14 * g34
        rhs = pi * sqrt(2)
        assert fabs(lhs - rhs) < mpf("1e-40"), "Γ(1/4)·Γ(3/4) != π√2"

    def test_airy_wronskian_x1(self, report):
        ai = self._get_corrected_value(report, "ai_1")
        aip = self._get_corrected_value(report, "ai_prime_1")
        bi = self._get_corrected_value(report, "bi_1")
        bip = self._get_corrected_value(report, "bi_prime_1")
        w = ai * bip - aip * bi
        assert fabs(w - 1 / pi) < mpf("1e-40"), "Wronskian at x=1 failed"

    def test_airy_wronskian_x2(self, report):
        ai = self._get_corrected_value(report, "ai_2")
        aip = self._get_corrected_value(report, "ai_prime_2")
        bi = self._get_corrected_value(report, "bi_2")
        bip = self._get_corrected_value(report, "bi_prime_2")
        w = ai * bip - aip * bi
        assert fabs(w - 1 / pi) < mpf("1e-40"), "Wronskian at x=2 failed"

    def test_airy_wronskian_x0(self, report):
        ai = self._get_corrected_value(report, "ai_0")
        aip = self._get_corrected_value(report, "ai_prime_0")
        bi = self._get_corrected_value(report, "bi_0")
        bip = self._get_corrected_value(report, "bi_prime_0")
        w = ai * bip - aip * bi
        assert fabs(w - 1 / pi) < mpf("1e-40"), "Wronskian at x=0 failed"

    def test_bessel_recurrence_x1(self, report):
        j0 = self._get_corrected_value(report, "j0_1")
        j1 = self._get_corrected_value(report, "j1_1")
        j2 = self._get_corrected_value(report, "j2_1")
        lhs = j0 + j2
        rhs = 2 * j1
        assert fabs(lhs - rhs) < mpf("1e-40"), "J_0(1)+J_2(1) != 2·J_1(1)"
