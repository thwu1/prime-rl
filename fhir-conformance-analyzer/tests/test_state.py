
import json
import os
import pytest

REPORT_PATH = "/app/output/conformance_report.json"


@pytest.fixture(scope="session")
def report():
    assert os.path.exists(REPORT_PATH), f"Conformance report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


class TestReportStructure:
    def test_top_level_keys(self, report):
        expected = {"must_support_coverage", "capability_gaps", "reference_integrity", "overall_conformance"}
        assert set(report.keys()) == expected

    def test_must_support_profile_names(self, report):
        expected_profiles = {
            "us-core-patient",
            "us-core-condition-encounter-diagnosis",
            "us-core-observation-lab",
            "us-core-vital-signs",
            "us-core-medicationrequest",
        }
        assert set(report["must_support_coverage"].keys()) == expected_profiles

    def test_must_support_profile_fields(self, report):
        for profile_name, profile_data in report["must_support_coverage"].items():
            assert "total_resources" in profile_data, f"{profile_name} missing total_resources"
            assert "covered_elements" in profile_data, f"{profile_name} missing covered_elements"
            assert "missing_elements" in profile_data, f"{profile_name} missing missing_elements"
            assert "coverage_pct" in profile_data, f"{profile_name} missing coverage_pct"

    def test_capability_gaps_keys(self, report):
        expected_types = {"Patient", "Condition", "Observation", "MedicationRequest"}
        assert set(report["capability_gaps"].keys()) == expected_types

    def test_reference_integrity_fields(self, report):
        ri = report["reference_integrity"]
        assert "total_references" in ri
        assert "valid_references" in ri
        assert "broken_references" in ri


class TestMustSupportPatient:
    def test_total_resources(self, report):
        assert report["must_support_coverage"]["us-core-patient"]["total_resources"] == 3

    def test_missing_elements(self, report):
        missing = sorted(report["must_support_coverage"]["us-core-patient"]["missing_elements"])
        assert missing == ["extension:birthsex", "telecom.use"]

    def test_covered_count(self, report):
        covered = report["must_support_coverage"]["us-core-patient"]["covered_elements"]
        assert len(covered) == 20

    def test_coverage_pct(self, report):
        pct = report["must_support_coverage"]["us-core-patient"]["coverage_pct"]
        assert abs(pct - 0.9091) < 0.001

    def test_covered_includes_extensions(self, report):
        covered = report["must_support_coverage"]["us-core-patient"]["covered_elements"]
        assert "extension:race" in covered
        assert "extension:ethnicity" in covered

    def test_covered_includes_nested(self, report):
        covered = report["must_support_coverage"]["us-core-patient"]["covered_elements"]
        assert "address.city" in covered
        assert "address.state" in covered
        assert "name.family" in covered
        assert "communication.language" in covered


class TestMustSupportCondition:
    def test_total_resources(self, report):
        assert report["must_support_coverage"]["us-core-condition-encounter-diagnosis"]["total_resources"] == 3

    def test_missing_elements(self, report):
        missing = sorted(
            report["must_support_coverage"]["us-core-condition-encounter-diagnosis"]["missing_elements"]
        )
        assert missing == ["abatementDateTime"]

    def test_covered_count(self, report):
        covered = report["must_support_coverage"]["us-core-condition-encounter-diagnosis"]["covered_elements"]
        assert len(covered) == 8

    def test_coverage_pct(self, report):
        pct = report["must_support_coverage"]["us-core-condition-encounter-diagnosis"]["coverage_pct"]
        assert abs(pct - 0.8889) < 0.001


class TestMustSupportObservationLab:
    def test_total_resources(self, report):
        assert report["must_support_coverage"]["us-core-observation-lab"]["total_resources"] == 2

    def test_missing_elements(self, report):
        missing = sorted(report["must_support_coverage"]["us-core-observation-lab"]["missing_elements"])
        assert missing == ["dataAbsentReason", "valueCodeableConcept", "valueString"]

    def test_covered_count(self, report):
        covered = report["must_support_coverage"]["us-core-observation-lab"]["covered_elements"]
        assert len(covered) == 10

    def test_coverage_pct(self, report):
        pct = report["must_support_coverage"]["us-core-observation-lab"]["coverage_pct"]
        assert abs(pct - 0.7692) < 0.001


class TestMustSupportVitalSigns:
    def test_total_resources(self, report):
        assert report["must_support_coverage"]["us-core-vital-signs"]["total_resources"] == 3

    def test_missing_elements(self, report):
        missing = sorted(report["must_support_coverage"]["us-core-vital-signs"]["missing_elements"])
        assert missing == ["component.dataAbsentReason", "dataAbsentReason", "effectivePeriod"]

    def test_covered_count(self, report):
        covered = report["must_support_coverage"]["us-core-vital-signs"]["covered_elements"]
        assert len(covered) == 16

    def test_coverage_pct(self, report):
        pct = report["must_support_coverage"]["us-core-vital-signs"]["coverage_pct"]
        assert abs(pct - 0.8421) < 0.001


class TestMustSupportMedicationRequest:
    def test_total_resources(self, report):
        assert report["must_support_coverage"]["us-core-medicationrequest"]["total_resources"] == 3

    def test_missing_elements(self, report):
        missing = sorted(report["must_support_coverage"]["us-core-medicationrequest"]["missing_elements"])
        assert missing == ["reportedReference"]

    def test_covered_count(self, report):
        covered = report["must_support_coverage"]["us-core-medicationrequest"]["covered_elements"]
        assert len(covered) == 12

    def test_coverage_pct(self, report):
        pct = report["must_support_coverage"]["us-core-medicationrequest"]["coverage_pct"]
        assert abs(pct - 0.9231) < 0.001


class TestCapabilityGaps:
    def test_patient_missing_search_params(self, report):
        gaps = report["capability_gaps"]["Patient"]
        assert sorted(gaps["missing_search_params"]) == ["gender"]

    def test_patient_missing_interactions(self, report):
        gaps = report["capability_gaps"]["Patient"]
        assert sorted(gaps["missing_interactions"]) == ["vread"]

    def test_condition_missing_search_params(self, report):
        gaps = report["capability_gaps"]["Condition"]
        assert sorted(gaps["missing_search_params"]) == ["clinical-status", "onset-date"]

    def test_condition_no_missing_interactions(self, report):
        gaps = report["capability_gaps"]["Condition"]
        assert gaps["missing_interactions"] == []

    def test_observation_missing_search_params(self, report):
        gaps = report["capability_gaps"]["Observation"]
        assert sorted(gaps["missing_search_params"]) == ["date", "status"]

    def test_observation_no_missing_interactions(self, report):
        gaps = report["capability_gaps"]["Observation"]
        assert gaps["missing_interactions"] == []

    def test_medrq_missing_search_params(self, report):
        gaps = report["capability_gaps"]["MedicationRequest"]
        assert sorted(gaps["missing_search_params"]) == ["authoredon", "status"]

    def test_medrq_missing_interactions(self, report):
        gaps = report["capability_gaps"]["MedicationRequest"]
        assert sorted(gaps["missing_interactions"]) == ["vread"]


class TestReferenceIntegrity:
    def test_total_references(self, report):
        assert report["reference_integrity"]["total_references"] == 18

    def test_valid_references(self, report):
        assert report["reference_integrity"]["valid_references"] == 13

    def test_broken_count(self, report):
        broken = report["reference_integrity"]["broken_references"]
        assert len(broken) == 5

    def test_broken_reference_cond2_encounter(self, report):
        broken = report["reference_integrity"]["broken_references"]
        broken_sorted = sorted(broken, key=lambda x: (x["source_resource"], x["field"]))
        entry = broken_sorted[0]
        assert entry["source_resource"] == "Condition/cond-2"
        assert entry["reference"] == "Encounter/enc-2"
        assert entry["field"] == "encounter"

    def test_broken_reference_medrq2_encounter(self, report):
        broken = report["reference_integrity"]["broken_references"]
        broken_sorted = sorted(broken, key=lambda x: (x["source_resource"], x["field"]))
        entry = broken_sorted[1]
        assert entry["source_resource"] == "MedicationRequest/medrq-2"
        assert entry["reference"] == "Encounter/enc-2"
        assert entry["field"] == "encounter"

    def test_broken_reference_medrq2_medication(self, report):
        broken = report["reference_integrity"]["broken_references"]
        broken_sorted = sorted(broken, key=lambda x: (x["source_resource"], x["field"]))
        entry = broken_sorted[2]
        assert entry["source_resource"] == "MedicationRequest/medrq-2"
        assert entry["reference"] == "Medication/med-2"
        assert entry["field"] == "medicationReference"

    def test_broken_reference_medrq2_requester(self, report):
        broken = report["reference_integrity"]["broken_references"]
        broken_sorted = sorted(broken, key=lambda x: (x["source_resource"], x["field"]))
        entry = broken_sorted[3]
        assert entry["source_resource"] == "MedicationRequest/medrq-2"
        assert entry["reference"] == "Practitioner/prac-2"
        assert entry["field"] == "requester"

    def test_broken_reference_medrq3_requester(self, report):
        broken = report["reference_integrity"]["broken_references"]
        broken_sorted = sorted(broken, key=lambda x: (x["source_resource"], x["field"]))
        entry = broken_sorted[4]
        assert entry["source_resource"] == "MedicationRequest/medrq-3"
        assert entry["reference"] == "Practitioner/prac-3"
        assert entry["field"] == "requester"


class TestOverallConformance:
    def test_must_support_score(self, report):
        score = report["overall_conformance"]["must_support_score"]
        assert abs(score - 0.8665) < 0.002

    def test_capability_score(self, report):
        score = report["overall_conformance"]["capability_score"]
        assert abs(score - 0.6897) < 0.002

    def test_reference_integrity_score(self, report):
        score = report["overall_conformance"]["reference_integrity_score"]
        assert abs(score - 0.7222) < 0.002

    def test_total_score(self, report):
        score = report["overall_conformance"]["total_score"]
        assert abs(score - 0.7595) < 0.002

    def test_scores_are_floats(self, report):
        oc = report["overall_conformance"]
        assert isinstance(oc["must_support_score"], float)
        assert isinstance(oc["capability_score"], float)
        assert isinstance(oc["reference_integrity_score"], float)
        assert isinstance(oc["total_score"], float)
