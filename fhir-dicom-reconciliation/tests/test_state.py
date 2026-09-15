"""Tests for the FHIR-DICOM cross-standard reconciliation task outputs."""
import json
import os
import pytest


REPORT_PATH = "/app/output/reconciliation_report.json"
BUNDLE_PATH = "/app/output/corrected_bundle.json"
CORRECT_MODALITY_SYSTEM = "http://dicom.nema.org/resources/ontology/DCM"


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def find_resource(bundle, resource_type, resource_id):
    """Find a resource in a FHIR Bundle by resourceType and id."""
    for entry in bundle.get("entry", []):
        res = entry.get("resource", entry)
        if res.get("resourceType") == resource_type and res.get("id") == resource_id:
            return res
    for key in ("resources", "entries"):
        for item in bundle.get(key, []):
            if isinstance(item, dict):
                actual = item.get("resource", item)
                if (
                    actual.get("resourceType") == resource_type
                    and actual.get("id") == resource_id
                ):
                    return actual
    return None


def get_patient_mrn(patient):
    """Extract MRN value from a FHIR Patient resource."""
    for ident in patient.get("identifier", []):
        for c in ident.get("type", {}).get("coding", [{}]):
            if c.get("code") == "MR":
                return ident.get("value")
    if patient.get("identifier"):
        return patient["identifier"][0].get("value")
    return None


def get_study_uid(study):
    """Extract DICOM Study Instance UID from a FHIR ImagingStudy."""
    for ident in study.get("identifier", []):
        if ident.get("system") == "urn:dicom:uid":
            return ident.get("value", "").replace("urn:oid:", "")
    return None


def get_accession(study):
    """Extract accession number from a FHIR ImagingStudy."""
    for ident in study.get("identifier", []):
        for c in ident.get("type", {}).get("coding", [{}]):
            if c.get("code") == "ACSN":
                return ident.get("value")
    return None


def get_procedure_codes(study):
    """Extract procedure code values from a FHIR ImagingStudy."""
    codes = set()
    for cc in study.get("procedureCode", []):
        for coding in cc.get("coding", []):
            codes.add(coding.get("code", ""))
    return codes


def get_procedure_systems(study):
    """Extract procedure code system URIs from a FHIR ImagingStudy."""
    systems = set()
    for cc in study.get("procedureCode", []):
        for coding in cc.get("coding", []):
            systems.add(coding.get("system", ""))
    return systems


# ---------------------------------------------------------------------------
# Report structure tests
# ---------------------------------------------------------------------------

class TestReconciliationReport:

    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"

    def test_report_is_valid_json(self):
        report = load_json(REPORT_PATH)
        assert isinstance(report, dict), "Report root must be a JSON object"

    def test_report_has_inconsistencies(self):
        report = load_json(REPORT_PATH)
        items = report.get(
            "inconsistencies",
            report.get("findings", report.get("errors", [])),
        )
        assert len(items) >= 18, (
            f"Expected at least 18 inconsistencies, found {len(items)}"
        )

    def test_report_has_summary(self):
        report = load_json(REPORT_PATH)
        has_summary = any(
            k in report
            for k in ("summary", "total_inconsistencies", "patients_analyzed", "total")
        )
        assert has_summary, "Report must include a summary section"


# ---------------------------------------------------------------------------
# Corrected bundle structure tests
# ---------------------------------------------------------------------------

class TestCorrectedBundleStructure:

    def test_bundle_exists(self):
        assert os.path.exists(BUNDLE_PATH), f"Corrected bundle not found at {BUNDLE_PATH}"

    def test_bundle_is_valid_json(self):
        bundle = load_json(BUNDLE_PATH)
        assert isinstance(bundle, dict), "Bundle root must be a JSON object"

    def test_bundle_has_entries(self):
        bundle = load_json(BUNDLE_PATH)
        entries = bundle.get("entry", [])
        assert len(entries) >= 9, (
            f"Expected at least 9 entries (4 Patients + 5 ImagingStudies), "
            f"found {len(entries)}"
        )


# ---------------------------------------------------------------------------
# Patient-level correction tests
# ---------------------------------------------------------------------------

class TestPatientCorrections:

    def test_sally_birthdate_corrected(self):
        """Sally DOB should be 1950-04-12 (not 1951)."""
        bundle = load_json(BUNDLE_PATH)
        sally = find_resource(bundle, "Patient", "siim-sally")
        assert sally is not None, "Patient siim-sally not found"
        assert sally["birthDate"] == "1950-04-12", (
            f"Expected 1950-04-12, got {sally['birthDate']}"
        )

    def test_joe_mrn_corrected(self):
        """Joe MRN should be TCGA-17-Z058 (not Z059)."""
        bundle = load_json(BUNDLE_PATH)
        joe = find_resource(bundle, "Patient", "siim-joe")
        assert joe is not None, "Patient siim-joe not found"
        mrn = get_patient_mrn(joe)
        assert mrn == "TCGA-17-Z058", f"Expected TCGA-17-Z058, got {mrn}"

    def test_andy_gender_corrected(self):
        """Andy gender should be male (not female)."""
        bundle = load_json(BUNDLE_PATH)
        andy = find_resource(bundle, "Patient", "siim-andy")
        assert andy is not None, "Patient siim-andy not found"
        assert andy["gender"] == "male", f"Expected male, got {andy['gender']}"


# ---------------------------------------------------------------------------
# Sally ImagingStudy corrections
# ---------------------------------------------------------------------------

class TestSallyStudyCorrections:

    def test_sally_study_date_corrected(self):
        """Sally study started date should be 2008-04-12 (not 04-13)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "sally-mammogram")
        assert study is not None, "ImagingStudy sally-mammogram not found"
        assert "2008-04-12" in study["started"], (
            f"Expected date 2008-04-12 in started, got {study['started']}"
        )

    def test_sally_num_series_corrected(self):
        """Sally numberOfSeries should be 2 (not 3)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "sally-mammogram")
        assert study is not None, "ImagingStudy sally-mammogram not found"
        assert study["numberOfSeries"] == 2, (
            f"Expected 2, got {study['numberOfSeries']}"
        )

    def test_sally_description_corrected(self):
        """Sally description should contain 'Diagnostic' (not 'Screening')."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "sally-mammogram")
        assert study is not None, "ImagingStudy sally-mammogram not found"
        assert "Diagnostic" in study["description"], (
            f"Expected 'Diagnostic' in description, got {study['description']}"
        )

    def test_sally_procedure_code_added(self):
        """Sally study should have procedureCode with SNOMED 71651007 (Mammography)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "sally-mammogram")
        assert study is not None, "ImagingStudy sally-mammogram not found"
        codes = get_procedure_codes(study)
        assert "71651007" in codes, (
            f"Expected procedureCode with code 71651007, got codes {codes}"
        )


# ---------------------------------------------------------------------------
# Joe ImagingStudy corrections (including cross-reference)
# ---------------------------------------------------------------------------

class TestJoeStudyCorrections:

    def test_joe_subject_reference_corrected(self):
        """Joe study subject should reference Patient/siim-joe (not siim-andy)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "joe-ct-chest")
        assert study is not None, "ImagingStudy joe-ct-chest not found"
        ref = study.get("subject", {}).get("reference", "")
        assert ref == "Patient/siim-joe", (
            f"Expected Patient/siim-joe, got {ref}"
        )

    def test_joe_study_uid_corrected(self):
        """Joe study UID should end ...93853029328343 (not ...344)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "joe-ct-chest")
        assert study is not None, "ImagingStudy joe-ct-chest not found"
        uid = get_study_uid(study)
        assert uid == "1.2.826.0.1.3680043.8.498.93853029328343", (
            f"Expected UID ending 28343, got {uid}"
        )

    def test_joe_modality_corrected(self):
        """Joe series modality should be CT (not MR)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "joe-ct-chest")
        assert study is not None, "ImagingStudy joe-ct-chest not found"
        series = study.get("series", [])
        assert len(series) >= 1, "Joe study must have at least 1 series"
        code = series[0].get("modality", {}).get("code")
        assert code == "CT", f"Expected CT, got {code}"

    def test_joe_num_instances_corrected(self):
        """Joe numberOfInstances should be 3 (not 5)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "joe-ct-chest")
        assert study is not None, "ImagingStudy joe-ct-chest not found"
        assert study["numberOfInstances"] == 3, (
            f"Expected 3, got {study['numberOfInstances']}"
        )


# ---------------------------------------------------------------------------
# Andy ImagingStudy corrections (including modality system URI)
# ---------------------------------------------------------------------------

class TestAndyStudyCorrections:

    def test_andy_accession_corrected(self):
        """Andy accession should be a508258761846499 (not ...846400)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "andy-ct-chest")
        assert study is not None, "ImagingStudy andy-ct-chest not found"
        acc = get_accession(study)
        assert acc == "a508258761846499", f"Expected a508258761846499, got {acc}"

    def test_andy_referrer_corrected(self):
        """Andy referrer should contain SMITH (not Jones)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "andy-ct-chest")
        assert study is not None, "ImagingStudy andy-ct-chest not found"
        referrer = study.get("referrer", {}).get("display", "")
        assert "SMITH" in referrer.upper(), (
            f"Expected SMITH in referrer, got {referrer}"
        )

    def test_andy_num_instances_corrected(self):
        """Andy numberOfInstances should be 2 (not 4)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "andy-ct-chest")
        assert study is not None, "ImagingStudy andy-ct-chest not found"
        assert study["numberOfInstances"] == 2, (
            f"Expected 2, got {study['numberOfInstances']}"
        )

    def test_andy_modality_system_uri_corrected(self):
        """Andy series modality system should use correct DICOM ontology URI."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "andy-ct-chest")
        assert study is not None, "ImagingStudy andy-ct-chest not found"
        series = study.get("series", [])
        assert len(series) >= 1, "Andy study must have at least 1 series"
        sys_uri = series[0].get("modality", {}).get("system", "")
        assert sys_uri == CORRECT_MODALITY_SYSTEM, (
            f"Expected {CORRECT_MODALITY_SYSTEM}, got {sys_uri}"
        )


# ---------------------------------------------------------------------------
# Ravi CT ImagingStudy corrections (including procedureCode)
# ---------------------------------------------------------------------------

class TestRaviCtStudyCorrections:

    def test_ravi_ct_study_date_corrected(self):
        """Ravi CT study started should contain 2000-01-01 (not 01-02)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "ravi-ct-chest")
        assert study is not None, "ImagingStudy ravi-ct-chest not found"
        assert "2000-01-01" in study["started"], (
            f"Expected 2000-01-01 in started, got {study['started']}"
        )

    def test_ravi_ct_num_series_corrected(self):
        """Ravi CT numberOfSeries should be 2 (not 3)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "ravi-ct-chest")
        assert study is not None, "ImagingStudy ravi-ct-chest not found"
        assert study["numberOfSeries"] == 2, (
            f"Expected 2, got {study['numberOfSeries']}"
        )

    def test_ravi_ct_num_instances_corrected(self):
        """Ravi CT numberOfInstances should be 4 (not 6)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "ravi-ct-chest")
        assert study is not None, "ImagingStudy ravi-ct-chest not found"
        assert study["numberOfInstances"] == 4, (
            f"Expected 4, got {study['numberOfInstances']}"
        )

    def test_ravi_ct_procedure_code_corrected(self):
        """Ravi CT procedureCode should have SNOMED 75385009 (not LOINC CT)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "ravi-ct-chest")
        assert study is not None, "ImagingStudy ravi-ct-chest not found"
        codes = get_procedure_codes(study)
        assert "75385009" in codes, (
            f"Expected procedureCode with code 75385009, got codes {codes}"
        )
        systems = get_procedure_systems(study)
        assert "http://loinc.org" not in systems, (
            f"procedureCode should not use http://loinc.org system, got {systems}"
        )


# ---------------------------------------------------------------------------
# Ravi CR ImagingStudy corrections (including modality system URI)
# ---------------------------------------------------------------------------

class TestRaviCrStudyCorrections:

    def test_ravi_cr_description_corrected(self):
        """Ravi CR description should be 'Chest PA Radiograph' (not 'Chest XR')."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "ravi-cr-chest")
        assert study is not None, "ImagingStudy ravi-cr-chest not found"
        assert study["description"] == "Chest PA Radiograph", (
            f"Expected 'Chest PA Radiograph', got {study['description']}"
        )

    def test_ravi_cr_accession_corrected(self):
        """Ravi CR accession should be a819497684894127 (not ...128)."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "ravi-cr-chest")
        assert study is not None, "ImagingStudy ravi-cr-chest not found"
        acc = get_accession(study)
        assert acc == "a819497684894127", f"Expected a819497684894127, got {acc}"

    def test_ravi_cr_modality_system_uri_corrected(self):
        """Ravi CR series modality system should use correct DICOM ontology URI."""
        bundle = load_json(BUNDLE_PATH)
        study = find_resource(bundle, "ImagingStudy", "ravi-cr-chest")
        assert study is not None, "ImagingStudy ravi-cr-chest not found"
        series = study.get("series", [])
        assert len(series) >= 1, "Ravi CR study must have at least 1 series"
        sys_uri = series[0].get("modality", {}).get("system", "")
        assert sys_uri == CORRECT_MODALITY_SYSTEM, (
            f"Expected {CORRECT_MODALITY_SYSTEM}, got {sys_uri}"
        )
