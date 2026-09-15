"""
OSCAL Multi-Profile Compliance Pipeline - Verification Tests.

Tests validate the resolved catalog and audit report produced by the agent.
"""

import json
import os
import pytest

REPORT_PATH = "/app/audit_report.json"
RESOLVED_PATH = "/app/resolved_catalog.json"


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), (
        f"Audit report not found at {REPORT_PATH}. "
        "The analysis must write its output to this path."
    )
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture
def resolved_catalog():
    assert os.path.exists(RESOLVED_PATH), (
        f"Resolved catalog not found at {RESOLVED_PATH}. "
        "The resolved catalog must be produced and written to this path."
    )
    with open(RESOLVED_PATH) as f:
        return json.load(f)


def _extract_control_ids(catalog_data):
    """Extract all control IDs from a resolved catalog."""
    ids = set()
    catalog = catalog_data.get("catalog", {})
    for group in catalog.get("groups", []):
        for ctrl in group.get("controls", []):
            ids.add(ctrl["id"])
            for enh in ctrl.get("controls", []):
                ids.add(enh["id"])
    for ctrl in catalog.get("controls", []):
        ids.add(ctrl["id"])
        for enh in ctrl.get("controls", []):
            ids.add(enh["id"])
    return ids


class TestResolvedCatalog:
    """Verify that the profile was resolved correctly."""

    EXPECTED_CONTROLS = sorted([
        "ac-1", "ac-2", "ac-2.1", "ac-3", "ac-4", "ac-6", "ac-6.1",
        "ac-7", "ac-8", "ac-11", "ac-17", "ac-17.1",
        "au-1", "au-2", "au-3", "au-6", "au-8", "au-12",
        "ia-1", "ia-2", "ia-2.1", "ia-5", "ia-5.1",
        "sc-7", "sc-8", "sc-12", "sc-13",
    ])

    def test_resolved_catalog_exists(self):
        assert os.path.exists(RESOLVED_PATH), (
            "Resolved catalog not found at /app/resolved_catalog.json."
        )

    def test_resolved_catalog_is_valid_oscal(self, resolved_catalog):
        assert "catalog" in resolved_catalog, (
            "Resolved catalog should have a 'catalog' root key"
        )
        catalog = resolved_catalog["catalog"]
        assert "uuid" in catalog, "Resolved catalog must have a UUID"
        assert "metadata" in catalog, "Resolved catalog must have metadata"

    def test_resolved_controls_match_expected(self, resolved_catalog):
        ids = sorted(_extract_control_ids(resolved_catalog))
        assert ids == self.EXPECTED_CONTROLS, (
            f"Resolved catalog controls mismatch.\n"
            f"Extra: {sorted(set(ids) - set(self.EXPECTED_CONTROLS))}\n"
            f"Missing: {sorted(set(self.EXPECTED_CONTROLS) - set(ids))}"
        )

    def test_resolved_control_count(self, resolved_catalog):
        ids = _extract_control_ids(resolved_catalog)
        assert len(ids) == 27, (
            f"Expected 27 controls in resolved catalog, got {len(ids)}"
        )

    def test_excluded_control_absent(self, resolved_catalog):
        ids = _extract_control_ids(resolved_catalog)
        assert "ac-6.5" not in ids, (
            "ac-6.5 should be excluded from the resolved catalog"
        )


class TestReportStructure:
    """Verify the audit report has the required top-level structure."""

    def test_report_has_resolved_profile(self, report):
        assert "resolved_profile" in report

    def test_report_has_gap_analysis(self, report):
        assert "gap_analysis" in report

    def test_report_has_compliance_summary(self, report):
        assert "compliance_summary" in report

    def test_report_has_remediation_tracking(self, report):
        assert "remediation_tracking" in report

    def test_resolved_profile_fields(self, report):
        rp = report["resolved_profile"]
        assert "required_controls" in rp
        assert "total_required" in rp
        assert "excluded_controls" in rp

    def test_gap_analysis_fields(self, report):
        ga = report["gap_analysis"]
        assert "missing_controls" in ga
        assert "incomplete_implementations" in ga
        assert "parameter_gaps" in ga
        assert "extraneous_controls" in ga
        assert "orphaned_component_refs" in ga

    def test_compliance_summary_fields(self, report):
        cs = report["compliance_summary"]
        assert "controls_implemented" in cs
        assert "controls_required" in cs
        assert "controls_fully_compliant" in cs
        assert "compliance_percentage" in cs

    def test_remediation_tracking_fields(self, report):
        rt = report["remediation_tracking"]
        assert "poam_items" in rt
        assert "gaps_with_poam" in rt
        assert "gaps_without_poam" in rt
        assert "total_poam_items" in rt
        assert "remediation_in_progress" in rt
        assert "remediation_completed" in rt
        assert "risk_accepted" in rt


class TestProfileResolution:
    """Verify correct profile resolution."""

    EXPECTED_REQUIRED = sorted([
        "ac-1", "ac-2", "ac-2.1", "ac-3", "ac-4", "ac-6", "ac-6.1",
        "ac-7", "ac-8", "ac-11", "ac-17", "ac-17.1",
        "au-1", "au-2", "au-3", "au-6", "au-8", "au-12",
        "ia-1", "ia-2", "ia-2.1", "ia-5", "ia-5.1",
        "sc-7", "sc-8", "sc-12", "sc-13",
    ])

    def test_required_controls_exact(self, report):
        actual = sorted(report["resolved_profile"]["required_controls"])
        assert actual == self.EXPECTED_REQUIRED, (
            f"Profile resolution produced wrong control set.\n"
            f"Extra: {sorted(set(actual) - set(self.EXPECTED_REQUIRED))}\n"
            f"Missing: {sorted(set(self.EXPECTED_REQUIRED) - set(actual))}"
        )

    def test_total_required_count(self, report):
        assert report["resolved_profile"]["total_required"] == 27

    def test_excluded_controls(self, report):
        excluded = report["resolved_profile"]["excluded_controls"]
        assert "ac-6.5" in excluded, "ac-6.5 should be in excluded controls"

    def test_excluded_not_in_required(self, report):
        required = report["resolved_profile"]["required_controls"]
        excluded = report["resolved_profile"]["excluded_controls"]
        for eid in excluded:
            assert eid not in required, (
                f"Excluded control {eid} should not appear in required controls"
            )


class TestMissingControls:
    """Verify detection of controls required but absent from SSP."""

    EXPECTED_MISSING = sorted(["ac-17.1", "au-12", "ia-5.1", "sc-8", "sc-13"])

    def test_missing_controls_exact(self, report):
        actual = sorted(report["gap_analysis"]["missing_controls"])
        assert actual == self.EXPECTED_MISSING, (
            f"Missing controls detection is wrong.\n"
            f"Expected: {self.EXPECTED_MISSING}\n"
            f"Got: {actual}"
        )

    def test_missing_count(self, report):
        assert len(report["gap_analysis"]["missing_controls"]) == 5


class TestIncompleteStatements:
    """Verify detection of controls with incomplete statement coverage."""

    def test_ac2_missing_statement_d(self, report):
        incomplete = report["gap_analysis"]["incomplete_implementations"]
        assert "ac-2" in incomplete, "ac-2 should have incomplete statement coverage"
        assert "ac-2_smt.d" in incomplete["ac-2"]["missing_statements"], (
            "ac-2 should be missing statement ac-2_smt.d"
        )

    def test_au6_missing_statement_b(self, report):
        incomplete = report["gap_analysis"]["incomplete_implementations"]
        assert "au-6" in incomplete, "au-6 should have incomplete statement coverage"
        assert "au-6_smt.b" in incomplete["au-6"]["missing_statements"], (
            "au-6 should be missing statement au-6_smt.b"
        )

    def test_no_false_positive_incomplete(self, report):
        incomplete = report["gap_analysis"]["incomplete_implementations"]
        should_be_complete = [
            "ac-1", "ac-3", "ac-4", "ac-6", "ac-8", "au-1",
            "au-3", "au-8", "ia-1", "ia-2", "sc-7", "sc-12",
        ]
        for ctrl in should_be_complete:
            assert ctrl not in incomplete, (
                f"{ctrl} should not be flagged as having incomplete statements"
            )


class TestParameterGaps:
    """Verify detection of profile-required parameters not set in SSP."""

    def test_ac7_missing_odp02(self, report):
        gaps = report["gap_analysis"]["parameter_gaps"]
        assert "ac-7" in gaps, "ac-7 should have parameter gaps"
        assert "ac-07_odp.02" in gaps["ac-7"]["missing"], (
            "ac-7 should be missing parameter ac-07_odp.02"
        )

    def test_au2_missing_odp01(self, report):
        gaps = report["gap_analysis"]["parameter_gaps"]
        assert "au-2" in gaps, "au-2 should have parameter gaps"
        assert "au-02_odp.01" in gaps["au-2"]["missing"], (
            "au-2 should be missing parameter au-02_odp.01"
        )

    def test_ia5_missing_odp01(self, report):
        gaps = report["gap_analysis"]["parameter_gaps"]
        assert "ia-5" in gaps, "ia-5 should have parameter gaps"
        assert "ia-05_odp.01" in gaps["ia-5"]["missing"], (
            "ia-5 should be missing parameter ia-05_odp.01"
        )

    def test_ac11_not_in_gaps(self, report):
        gaps = report["gap_analysis"]["parameter_gaps"]
        assert "ac-11" not in gaps, (
            "ac-11 should NOT have parameter gaps (ac-11_odp.01 is set in SSP)"
        )

    def test_ac7_odp01_not_in_gaps(self, report):
        gaps = report["gap_analysis"]["parameter_gaps"]
        if "ac-7" in gaps:
            assert "ac-07_odp.01" not in gaps["ac-7"]["missing"], (
                "ac-07_odp.01 should NOT be in gaps (it IS set in SSP)"
            )


class TestExtraneousControls:
    """Verify detection of controls implemented but not required."""

    def test_cm1_is_extraneous(self, report):
        extra = report["gap_analysis"]["extraneous_controls"]
        assert "cm-1" in extra, (
            "cm-1 is implemented in SSP but not required by profile"
        )

    def test_no_required_in_extraneous(self, report):
        extra = set(report["gap_analysis"]["extraneous_controls"])
        required = set(report["resolved_profile"]["required_controls"])
        overlap = extra & required
        assert not overlap, f"Required controls should not be extraneous: {overlap}"


class TestOrphanedComponents:
    """Verify detection of by-component refs to non-existent components."""

    def test_orphaned_uuid_detected(self, report):
        orphaned = report["gap_analysis"]["orphaned_component_refs"]
        assert "f1a2b3c4-dead-beef-cafe-123456789abc" in orphaned, (
            "Orphaned component UUID f1a2b3c4-dead-beef-cafe-123456789abc should be detected"
        )


class TestComplianceSummary:
    """Verify compliance metrics calculation."""

    def test_controls_required(self, report):
        assert report["compliance_summary"]["controls_required"] == 27

    def test_controls_implemented(self, report):
        assert report["compliance_summary"]["controls_implemented"] == 22

    def test_controls_fully_compliant(self, report):
        assert report["compliance_summary"]["controls_fully_compliant"] == 17, (
            "17 controls should be fully compliant (implemented with complete "
            "statement coverage and all profile-required params set)"
        )

    def test_compliance_percentage_range(self, report):
        pct = report["compliance_summary"]["compliance_percentage"]
        assert isinstance(pct, (int, float))
        assert 62.0 <= pct <= 63.5, (
            f"Compliance percentage should be ~62.96% (17/27*100), got {pct}"
        )

    def test_compliance_percentage_exact(self, report):
        pct = report["compliance_summary"]["compliance_percentage"]
        expected = round(17 / 27 * 100, 2)
        assert abs(pct - expected) < 0.1, (
            f"Expected compliance percentage {expected}, got {pct}"
        )


class TestRemediationTracking:
    """Verify POAM XML cross-referencing and remediation tracking."""

    def test_total_poam_items(self, report):
        rt = report["remediation_tracking"]
        assert rt["total_poam_items"] == 5, (
            f"Expected 5 POAM items, got {rt['total_poam_items']}"
        )

    def test_remediation_in_progress(self, report):
        rt = report["remediation_tracking"]
        assert rt["remediation_in_progress"] == 3, (
            f"Expected 3 in-progress remediations, got {rt['remediation_in_progress']}"
        )

    def test_remediation_completed(self, report):
        rt = report["remediation_tracking"]
        assert rt["remediation_completed"] == 1, (
            f"Expected 1 completed remediation, got {rt['remediation_completed']}"
        )

    def test_risk_accepted(self, report):
        rt = report["remediation_tracking"]
        assert rt["risk_accepted"] == 1, (
            f"Expected 1 risk-accepted item, got {rt['risk_accepted']}"
        )

    def test_gaps_with_poam(self, report):
        rt = report["remediation_tracking"]
        expected = sorted(["ac-17.1", "sc-8", "ac-2", "au-2", "sc-13"])
        actual = sorted(rt["gaps_with_poam"])
        assert actual == expected, (
            f"gaps_with_poam mismatch.\nExpected: {expected}\nGot: {actual}"
        )

    def test_gaps_without_poam(self, report):
        rt = report["remediation_tracking"]
        expected = sorted(["ac-7", "au-12", "au-6", "ia-5", "ia-5.1"])
        actual = sorted(rt["gaps_without_poam"])
        assert actual == expected, (
            f"gaps_without_poam mismatch.\nExpected: {expected}\nGot: {actual}"
        )

    def test_poam_item_ac17_1(self, report):
        items = report["remediation_tracking"]["poam_items"]
        matched = [i for i in items if i["control_id"] == "ac-17.1"]
        assert len(matched) == 1, "Expected exactly one POAM item for ac-17.1"
        item = matched[0]
        assert item["status"] == "in-progress"
        assert item["risk_status"] == "open"
        assert item["gap_type"] == "missing_control"

    def test_poam_item_sc8(self, report):
        items = report["remediation_tracking"]["poam_items"]
        matched = [i for i in items if i["control_id"] == "sc-8"]
        assert len(matched) == 1, "Expected exactly one POAM item for sc-8"
        item = matched[0]
        assert item["status"] == "risk-accepted"
        assert item["risk_status"] == "open"
        assert item["gap_type"] == "missing_control"

    def test_poam_item_ac2(self, report):
        items = report["remediation_tracking"]["poam_items"]
        matched = [i for i in items if i["control_id"] == "ac-2"]
        assert len(matched) == 1, "Expected exactly one POAM item for ac-2"
        item = matched[0]
        assert item["status"] == "in-progress"
        assert item["risk_status"] == "investigating"
        assert item["gap_type"] == "incomplete_statements"

    def test_poam_item_au2(self, report):
        items = report["remediation_tracking"]["poam_items"]
        matched = [i for i in items if i["control_id"] == "au-2"]
        assert len(matched) == 1, "Expected exactly one POAM item for au-2"
        item = matched[0]
        assert item["status"] == "completed"
        assert item["risk_status"] == "open"
        assert item["gap_type"] == "parameter_gap"

    def test_poam_item_sc13(self, report):
        items = report["remediation_tracking"]["poam_items"]
        matched = [i for i in items if i["control_id"] == "sc-13"]
        assert len(matched) == 1, "Expected exactly one POAM item for sc-13"
        item = matched[0]
        assert item["status"] == "in-progress"
        assert item["risk_status"] == "open"
        assert item["gap_type"] == "missing_control"

    def test_all_poam_items_have_required_fields(self, report):
        items = report["remediation_tracking"]["poam_items"]
        required_fields = {
            "poam_uuid", "control_id", "title", "status",
            "risk_status", "gap_type",
        }
        for item in items:
            missing = required_fields - set(item.keys())
            assert not missing, (
                f"POAM item missing fields: {missing}"
            )

    def test_poam_uuids_are_correct(self, report):
        items = report["remediation_tracking"]["poam_items"]
        uuids = {i["poam_uuid"] for i in items}
        expected_uuids = {
            "poam-0001-aaaa-1111-2222bbbbcccc",
            "poam-0002-bbbb-3333-4444ccccdddd",
            "poam-0003-cccc-5555-6666ddddeeee",
            "poam-0004-dddd-7777-8888eeeeffff",
            "poam-0005-eeee-9999-0000ffffaaaa",
        }
        assert uuids == expected_uuids, (
            f"POAM UUIDs mismatch.\nExpected: {expected_uuids}\nGot: {uuids}"
        )
