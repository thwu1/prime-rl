
"""
Verification tests for the DICOM-FHIR conformance audit pipeline.

Tests validate the reconciliation report, corrected FHIR resources,
and the FHIR Transaction Bundle output.
"""

import json
import os

import pytest

REPORT_PATH = "/app/output/reconciliation_report.json"
CORRECTED_DIR = "/app/output/corrected"
BUNDLE_PATH = "/app/output/transaction_bundle.json"


# -- Helpers -------------------------------------------------------------------

def load_report():
    with open(REPORT_PATH) as f:
        return json.load(f)


def load_corrected(name):
    path = os.path.join(CORRECTED_DIR, f"{name}.json")
    with open(path) as f:
        return json.load(f)


def load_bundle():
    with open(BUNDLE_PATH) as f:
        return json.load(f)


def _has_discrepancy(report, *keywords):
    """Return True if any discrepancy entry contains ALL keywords (case-insensitive)."""
    for d in report.get("discrepancies", []):
        text = json.dumps(d, default=str).lower()
        if all(kw.lower() in text for kw in keywords):
            return True
    return False


# -- Report Structure ----------------------------------------------------------

class TestReportStructure:
    def test_report_file_exists(self):
        assert os.path.isfile(REPORT_PATH), "reconciliation_report.json not found"

    def test_report_is_valid_json_with_discrepancies_key(self):
        data = load_report()
        assert "discrepancies" in data, "Report must have a 'discrepancies' key"
        assert isinstance(data["discrepancies"], list)

    def test_at_least_fifteen_discrepancies_found(self):
        data = load_report()
        n = len(data["discrepancies"])
        assert n >= 15, f"Expected >= 15 discrepancies, found {n}"


# -- Specific Discrepancy Detection --------------------------------------------

class TestDiscrepancyDetection:
    """Spot-check that key discrepancies appear in the report."""

    def test_patient_name_discrepancy_detected(self):
        """Sally's given name: Sarah (FHIR) vs Sally (DICOM)"""
        data = load_report()
        assert _has_discrepancy(data, "Sarah", "Sally"), \
            "Missing: Sally name mismatch (Sarah vs Sally)"

    def test_birthdate_discrepancy_detected(self):
        """Ravi's birthDate: 1940-01-02 (FHIR) vs 1940-01-01 (DICOM)"""
        data = load_report()
        found = (_has_discrepancy(data, "1940-01-02", "1940-01-01")
                 or _has_discrepancy(data, "19400102", "19400101"))
        assert found, "Missing: Ravi birthdate mismatch"

    def test_study_date_discrepancy_detected(self):
        """Sally mammogram started: 2008-04-13 (FHIR) vs 2008-04-12 (DICOM)"""
        data = load_report()
        found = (_has_discrepancy(data, "2008-04-13", "2008-04-12")
                 or _has_discrepancy(data, "20080413", "20080412"))
        assert found, "Missing: Sally mammogram date mismatch"

    def test_accession_discrepancy_detected(self):
        """Joe PET accession: a819497684894126 (FHIR) vs a819497684894999 (DICOM)"""
        data = load_report()
        assert _has_discrepancy(data, "a819497684894126", "a819497684894999"), \
            "Missing: Joe PET accession number mismatch"

    def test_subject_reference_discrepancy_detected(self):
        """Joe CT report references Patient/ravi-siim instead of Patient/joe-siim"""
        data = load_report()
        assert _has_discrepancy(data, "ravi-siim", "joe-siim"), \
            "Missing: DiagnosticReport subject reference mismatch"

    def test_kim_prefix_suffix_discrepancy_detected(self):
        """Kim's PN prefix/suffix swap: Jr. and Dr. appear in wrong fields"""
        data = load_report()
        assert _has_discrepancy(data, "Jr.", "Dr."), \
            "Missing: Kim prefix/suffix discrepancy"

    def test_kim_body_site_discrepancy_detected(self):
        """Kim MR bodySite: 39607008 (Lung) in FHIR vs 69536005 (Head) in DICOM"""
        data = load_report()
        assert _has_discrepancy(data, "39607008", "69536005"), \
            "Missing: Kim MR bodySite SNOMED code discrepancy"

    def test_kim_referrer_discrepancy_detected(self):
        """Kim MR referrer: dr-wong (FHIR) vs dr-smith (from DICOM ReferringPhysicianName)"""
        data = load_report()
        assert _has_discrepancy(data, "dr-wong", "dr-smith"), \
            "Missing: Kim MR referrer identity mismatch"

    def test_procedure_code_discrepancy_detected(self):
        """Kim MR procedureCode: 30799-1 CT Head (FHIR) vs 36801-9 MR Brain (DICOM)"""
        data = load_report()
        assert _has_discrepancy(data, "30799-1", "36801-9"), \
            "Missing: Kim MR procedure code (LOINC) discrepancy"


# -- Corrected Patient Resources -----------------------------------------------

class TestCorrectedPatients:
    def test_sally_given_name_corrected(self):
        data = load_corrected("Patient-sally-siim")
        given = data["name"][0]["given"][0]
        assert given == "Sally", f"Expected 'Sally', got '{given}'"

    def test_ravi_birthdate_corrected(self):
        data = load_corrected("Patient-ravi-siim")
        assert data["birthDate"] == "1940-01-01", \
            f"Expected '1940-01-01', got '{data['birthDate']}'"

    def test_joe_gender_corrected(self):
        data = load_corrected("Patient-joe-siim")
        assert data["gender"] == "male", \
            f"Expected 'male', got '{data['gender']}'"

    def test_kim_prefix_corrected(self):
        data = load_corrected("Patient-kim-siim")
        prefix = data["name"][0].get("prefix", [])
        assert prefix == ["Dr."], \
            f"Expected prefix ['Dr.'], got {prefix}"

    def test_kim_suffix_corrected(self):
        data = load_corrected("Patient-kim-siim")
        suffix = data["name"][0].get("suffix", [])
        assert suffix == ["Jr."], \
            f"Expected suffix ['Jr.'], got {suffix}"

    def test_kim_middle_name_in_given(self):
        data = load_corrected("Patient-kim-siim")
        given = data["name"][0]["given"]
        assert "Lee" in given, \
            f"Expected middle name 'Lee' in given names, got {given}"


# -- Corrected ImagingStudy Resources ------------------------------------------

class TestCorrectedImagingStudies:
    def test_sally_mammo_date_corrected(self):
        data = load_corrected("ImagingStudy-study-sally-mammo")
        assert data["started"] == "2008-04-12", \
            f"Expected '2008-04-12', got '{data['started']}'"

    def test_sally_mri_study_modality_corrected(self):
        data = load_corrected("ImagingStudy-study-sally-mri")
        codes = [m.get("code") for m in data.get("modality", [])]
        assert "MR" in codes, f"Expected 'MR' in study modality, got {codes}"
        assert "US" not in codes, f"'US' should not remain in study modality"

    def test_sally_mri_series_modality_corrected(self):
        data = load_corrected("ImagingStudy-study-sally-mri")
        for s in data.get("series", []):
            code = s.get("modality", {}).get("code", "")
            assert code == "MR", f"Expected series modality 'MR', got '{code}'"

    def test_ravi_ct_series_count_corrected(self):
        data = load_corrected("ImagingStudy-study-ravi-ct")
        assert len(data["series"]) == 2, \
            f"Expected 2 series, got {len(data['series'])}"

    def test_ravi_ct_counts_corrected(self):
        data = load_corrected("ImagingStudy-study-ravi-ct")
        assert data["numberOfSeries"] == 2, \
            f"Expected numberOfSeries=2, got {data['numberOfSeries']}"
        assert data["numberOfInstances"] == 2, \
            f"Expected numberOfInstances=2, got {data['numberOfInstances']}"

    def test_ravi_ct_has_coronal_series(self):
        data = load_corrected("ImagingStudy-study-ravi-ct")
        uids = [s.get("uid") for s in data["series"]]
        assert "1.2.826.0.1.3680043.8.499.4012345003.2" in uids, \
            "Missing Coronal Reformat series (UID ...4012345003.2)"

    def test_joe_pet_accession_corrected(self):
        data = load_corrected("ImagingStudy-study-joe-pet")
        for ident in data.get("identifier", []):
            codings = ident.get("type", {}).get("coding", [])
            if any(c.get("code") == "ACSN" for c in codings):
                assert ident["value"] == "a819497684894999", \
                    f"Expected ACSN 'a819497684894999', got '{ident['value']}'"
                return
        pytest.fail("No ACSN identifier found in corrected Joe PET study")

    def test_joe_pet_instance_count_corrected(self):
        data = load_corrected("ImagingStudy-study-joe-pet")
        assert data["numberOfInstances"] == 2, \
            f"Expected numberOfInstances=2, got {data['numberOfInstances']}"

    def test_joe_pet_series_modality_corrected(self):
        data = load_corrected("ImagingStudy-study-joe-pet")
        for s in data["series"]:
            if s.get("uid", "").endswith(".2") or "Attenuation" in s.get("description", ""):
                code = s.get("modality", {}).get("code", "")
                assert code == "CT", \
                    f"Expected CT for attenuation correction series, got '{code}'"
                return
        pytest.fail("Could not find CT attenuation correction series")

    def test_kim_mr_body_site_corrected(self):
        """Both series should have bodySite code 69536005 (Head), not 39607008 (Lung)."""
        data = load_corrected("ImagingStudy-study-kim-mr")
        for s in data["series"]:
            bs = s.get("bodySite", {})
            assert bs.get("code") == "69536005", \
                f"Expected bodySite '69536005' (Head structure), got '{bs.get('code')}' for series {s.get('uid')}"

    def test_kim_mr_referrer_corrected(self):
        """referrer should point to Practitioner/dr-smith (matching DICOM ReferringPhysicianName Smith^Jane)."""
        data = load_corrected("ImagingStudy-study-kim-mr")
        ref = data.get("referrer", {}).get("reference", "")
        assert ref == "Practitioner/dr-smith", \
            f"Expected 'Practitioner/dr-smith', got '{ref}'"

    def test_kim_mr_procedure_code_corrected(self):
        """procedureCode should use LOINC 36801-9 (MR Brain), not 30799-1 (CT Head)."""
        data = load_corrected("ImagingStudy-study-kim-mr")
        codes = data.get("procedureCode", [])
        assert len(codes) > 0, "No procedureCode found"
        code_val = codes[0]["coding"][0]["code"]
        assert code_val == "36801-9", \
            f"Expected LOINC '36801-9' (MR Brain), got '{code_val}'"
        sys_val = codes[0]["coding"][0].get("system", "")
        assert sys_val == "http://loinc.org", \
            f"Expected system 'http://loinc.org', got '{sys_val}'"


# -- Corrected DiagnosticReport ------------------------------------------------

class TestCorrectedReports:
    def test_joe_ct_report_subject_corrected(self):
        data = load_corrected("DiagnosticReport-report-joe-ct")
        ref = data["subject"]["reference"]
        assert ref == "Patient/joe-siim", \
            f"Expected 'Patient/joe-siim', got '{ref}'"


# -- Transaction Bundle --------------------------------------------------------

class TestTransactionBundle:
    def test_bundle_file_exists(self):
        assert os.path.isfile(BUNDLE_PATH), "transaction_bundle.json not found"

    def test_bundle_is_valid_transaction(self):
        bundle = load_bundle()
        assert bundle.get("resourceType") == "Bundle", \
            f"Expected resourceType 'Bundle', got '{bundle.get('resourceType')}'"
        assert bundle.get("type") == "transaction", \
            f"Expected type 'transaction', got '{bundle.get('type')}'"

    def test_bundle_has_sufficient_entries(self):
        bundle = load_bundle()
        entries = bundle.get("entry", [])
        assert len(entries) >= 8, \
            f"Expected >= 8 corrected resource entries, got {len(entries)}"

    def test_bundle_entries_have_put_requests(self):
        bundle = load_bundle()
        for i, entry in enumerate(bundle.get("entry", [])):
            req = entry.get("request", {})
            assert req.get("method") == "PUT", \
                f"Entry {i}: expected request.method 'PUT', got '{req.get('method')}'"

    def test_bundle_entry_urls_match_resources(self):
        bundle = load_bundle()
        for i, entry in enumerate(bundle.get("entry", [])):
            res = entry.get("resource", {})
            url = entry.get("request", {}).get("url", "")
            expected = f"{res.get('resourceType')}/{res.get('id')}"
            assert url == expected, \
                f"Entry {i}: expected url '{expected}', got '{url}'"
