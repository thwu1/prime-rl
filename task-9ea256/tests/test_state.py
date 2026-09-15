"""
Tests for HL7 v2 → FHIR R4 interoperability pipeline.

Validates the complete pipeline: HL7 v2 conversion to FHIR R4 Transaction Bundles,
resource extraction and consolidation, ConceptMap-based terminology migration, and
structured pipeline report generation.
"""

import json
import os
import subprocess
import sys
import glob as globmod

import pytest
import jsonschema

OUTPUT_DIR = "/app/output"
BUNDLES_DIR = "/app/output/bundles"
REPORT_PATH = "/app/output/pipeline_report.json"
SCHEMA_PATH = "/app/report_schema.json"


@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Run the full pipeline before any tests execute."""
    assert os.path.exists("/app/pipeline.sh"), (
        "pipeline.sh not found at /app/pipeline.sh"
    )
    result = subprocess.run(
        ["bash", "/app/pipeline.sh"],
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"Pipeline failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_bundles():
    """Load all FHIR Bundles from the bundles directory, keyed by filename stem."""
    bundles = {}
    for path in sorted(globmod.glob(os.path.join(BUNDLES_DIR, "*.json"))):
        with open(path) as f:
            b = json.load(f)
        name = os.path.splitext(os.path.basename(path))[0]
        bundles[name] = b
    return bundles


def load_ndjson(filename):
    """Load resources from an NDJSON file, keyed by resource id."""
    resources = {}
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                resources[r["id"]] = r
    return resources


def find_bundle_resources(bundle, resource_type):
    """Find all resources of a given type in a Bundle."""
    return [
        e["resource"]
        for e in bundle.get("entry", [])
        if e["resource"]["resourceType"] == resource_type
    ]


def get_codes_by_system(resource, element_path, system_uri):
    """Extract codes from a specific system within a CodeableConcept."""
    obj = resource
    for part in element_path.split("."):
        obj = obj[part]
    return {
        c["code"]
        for c in obj.get("coding", [])
        if c.get("system") == system_uri
    }


def get_all_systems(resource, element_path):
    """Get all system URIs from a CodeableConcept's codings."""
    obj = resource
    for part in element_path.split("."):
        obj = obj[part]
    return {c.get("system") for c in obj.get("coding", [])}


def find_resources_with_code(resources, system_uri, code):
    """Find all resources that have a specific code in their code.coding."""
    result = []
    for rid, r in resources.items():
        for coding in r.get("code", {}).get("coding", []):
            if coding.get("system") == system_uri and coding.get("code") == code:
                result.append(r)
                break
    return result


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ICD9 = "http://hl7.org/fhir/sid/icd-9-cm"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
SNOMED = "http://snomed.info/sct"
LOCAL_LAB = "http://hospital.example.org/lab-codes"
LOINC = "http://loinc.org"
LOCAL_ALLERGY = "http://hospital.example.org/allergy-codes"


# ================================================================
# Phase 1: HL7 v2 → FHIR R4 Bundle Tests
# ================================================================

class TestBundleGeneration:
    @pytest.fixture
    def bundles(self):
        return load_bundles()

    def test_three_bundles_generated(self, bundles):
        assert len(bundles) == 3

    def test_bundle_type_is_transaction(self, bundles):
        for name, b in bundles.items():
            assert b["resourceType"] == "Bundle", f"{name}: not a Bundle"
            assert b["type"] == "transaction", f"{name}: not transaction"

    def test_entries_have_required_fields(self, bundles):
        for name, b in bundles.items():
            for i, entry in enumerate(b.get("entry", [])):
                assert "fullUrl" in entry, f"{name}[{i}]: missing fullUrl"
                assert "resource" in entry, f"{name}[{i}]: missing resource"
                assert "request" in entry, f"{name}[{i}]: missing request"
                assert entry["request"]["method"] == "POST"


class TestHL7PatientConversion:
    @pytest.fixture
    def bundles(self):
        return load_bundles()

    def test_patient_smith_demographics(self, bundles):
        """CTRL0001: SMITH, JOHN WILLIAM, male, 1975-06-22"""
        b = bundles.get("CTRL0001")
        assert b is not None, "Bundle CTRL0001 not found"
        patients = find_bundle_resources(b, "Patient")
        assert len(patients) == 1
        p = patients[0]
        assert p["name"][0]["family"] == "SMITH"
        assert "JOHN" in p["name"][0]["given"]
        assert p["gender"] == "male"
        assert p["birthDate"] == "1975-06-22"

    def test_patient_obrien_demographics(self, bundles):
        """CTRL0002: O'BRIEN, CONNOR SEAN, female, 2000-11-30"""
        b = bundles.get("CTRL0002")
        assert b is not None, "Bundle CTRL0002 not found"
        patients = find_bundle_resources(b, "Patient")
        assert len(patients) == 1
        p = patients[0]
        assert p["name"][0]["family"] == "O'BRIEN"
        assert p["gender"] == "female"
        assert p["birthDate"] == "2000-11-30"

    def test_email_telecom(self, bundles):
        """CTRL0002: email contactpoint from XTN with Internet equipment."""
        b = bundles["CTRL0002"]
        patients = find_bundle_resources(b, "Patient")
        telecoms = patients[0].get("telecom", [])
        emails = [t for t in telecoms if t.get("system") == "email"]
        assert len(emails) >= 1
        assert emails[0]["value"] == "cobrien@email.com"

    def test_escape_handling_address(self, bundles):
        r"""CTRL0003: \T\ escape in PID.11 must resolve to '&' in address."""
        b = bundles["CTRL0003"]
        patients = find_bundle_resources(b, "Patient")
        addr = patients[0]["address"][0]
        assert "&" in addr["line"][0]


class TestHL7EncounterConversion:
    @pytest.fixture
    def bundles(self):
        return load_bundles()

    def test_inpatient_class(self, bundles):
        """CTRL0001: PV1.2=I → class code IMP"""
        encs = find_bundle_resources(bundles["CTRL0001"], "Encounter")
        assert len(encs) == 1
        assert encs[0]["class"]["code"] == "IMP"

    def test_emergency_class(self, bundles):
        """CTRL0002: PV1.2=E → class code EMER"""
        encs = find_bundle_resources(bundles["CTRL0002"], "Encounter")
        assert len(encs) == 1
        assert encs[0]["class"]["code"] == "EMER"

    def test_encounter_period_start(self, bundles):
        """CTRL0001: PV1.44=20240115080000 → period.start"""
        encs = find_bundle_resources(bundles["CTRL0001"], "Encounter")
        assert "period" in encs[0]
        assert encs[0]["period"]["start"] == "2024-01-15T08:00:00"


class TestHL7SegmentConversion:
    @pytest.fixture
    def bundles(self):
        return load_bundles()

    def test_ctrl0001_condition_count(self, bundles):
        """patient_admit: 2 DG1 segments → 2 Conditions"""
        conditions = find_bundle_resources(bundles["CTRL0001"], "Condition")
        assert len(conditions) == 2

    def test_ctrl0001_condition_icd9_codes(self, bundles):
        """Conditions from CTRL0001 have ICD-9-CM codes 401.1 and 486"""
        conditions = find_bundle_resources(bundles["CTRL0001"], "Condition")
        codes = set()
        for c in conditions:
            for coding in c.get("code", {}).get("coding", []):
                codes.add(coding["code"])
        assert "401.1" in codes
        assert "486" in codes

    def test_ctrl0001_related_person(self, bundles):
        """patient_admit: 1 NK1 → 1 RelatedPerson (SMITH MARY)"""
        rps = find_bundle_resources(bundles["CTRL0001"], "RelatedPerson")
        assert len(rps) == 1
        assert rps[0]["name"][0]["family"] == "SMITH"

    def test_ctrl0002_multiple_nk1(self, bundles):
        """emergency_visit: 2 NK1 → 2 RelatedPersons"""
        rps = find_bundle_resources(bundles["CTRL0002"], "RelatedPerson")
        assert len(rps) == 2

    def test_ctrl0002_allergy_count(self, bundles):
        """emergency_visit: 3 AL1 → 3 AllergyIntolerances"""
        ais = find_bundle_resources(bundles["CTRL0002"], "AllergyIntolerance")
        assert len(ais) == 3

    def test_ctrl0001_coverage(self, bundles):
        """patient_admit: 1 IN1 → 1 Coverage"""
        covs = find_bundle_resources(bundles["CTRL0001"], "Coverage")
        assert len(covs) == 1

    def test_ctrl0003_condition_codes(self, bundles):
        """escape_handling: 2 DG1 with ICD-9 codes 428.0 and 272.4"""
        conditions = find_bundle_resources(bundles["CTRL0003"], "Condition")
        assert len(conditions) == 2
        codes = set()
        for c in conditions:
            for coding in c.get("code", {}).get("coding", []):
                codes.add(coding["code"])
        assert "428.0" in codes
        assert "272.4" in codes


# ================================================================
# Phase 2: Consolidated NDJSON / Output Files
# ================================================================

class TestOutputFiles:
    def test_condition_output_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "Condition.ndjson"))

    def test_observation_output_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "Observation.ndjson"))

    def test_allergy_output_exists(self):
        assert os.path.exists(
            os.path.join(OUTPUT_DIR, "AllergyIntolerance.ndjson")
        )

    def test_migrated_condition_count(self):
        """11 total: 6 from bulk export + 5 extracted from HL7 bundles"""
        resources = load_ndjson("Condition.ndjson")
        assert len(resources) == 11


# ================================================================
# Phase 3: Terminology Migration — Conditions
# ================================================================

class TestConditionBasicTranslations:
    @pytest.fixture
    def conditions(self):
        return load_ndjson("Condition.ndjson")

    def test_cond001_translated_to_i10(self, conditions):
        codes = get_codes_by_system(conditions["cond-001"], "code", ICD10)
        assert "I10" in codes

    def test_cond001_source_preserved(self, conditions):
        codes = get_codes_by_system(conditions["cond-001"], "code", ICD9)
        assert "401.1" in codes

    def test_cond002_translated_to_e11_9(self, conditions):
        codes = get_codes_by_system(conditions["cond-002"], "code", ICD10)
        assert "E11.9" in codes

    def test_cond002_snomed_untouched(self, conditions):
        """Pre-existing SNOMED coding (non-targeted) must be preserved."""
        codes = get_codes_by_system(conditions["cond-002"], "code", SNOMED)
        assert "44054006" in codes

    def test_cond004_translated_to_i50_9(self, conditions):
        codes = get_codes_by_system(conditions["cond-004"], "code", ICD10)
        assert "I50.9" in codes


class TestConditionOneToMany:
    @pytest.fixture
    def conditions(self):
        return load_ndjson("Condition.ndjson")

    def test_cond003_has_j18_9(self, conditions):
        """ICD-9 486 maps to J18.9 (equivalent)."""
        codes = get_codes_by_system(conditions["cond-003"], "code", ICD10)
        assert "J18.9" in codes

    def test_cond003_has_j18_8(self, conditions):
        """ICD-9 486 also maps to J18.8 (narrower)."""
        codes = get_codes_by_system(conditions["cond-003"], "code", ICD10)
        assert "J18.8" in codes

    def test_cond005_has_j45_909(self, conditions):
        """ICD-9 493.90 maps to J45.909 (equivalent)."""
        codes = get_codes_by_system(conditions["cond-005"], "code", ICD10)
        assert "J45.909" in codes

    def test_cond005_has_j45_20(self, conditions):
        codes = get_codes_by_system(conditions["cond-005"], "code", ICD10)
        assert "J45.20" in codes

    def test_cond005_has_j45_30(self, conditions):
        codes = get_codes_by_system(conditions["cond-005"], "code", ICD10)
        assert "J45.30" in codes


class TestConditionUnmapped:
    @pytest.fixture
    def conditions(self):
        return load_ndjson("Condition.ndjson")

    def test_cond006_no_icd10_added(self, conditions):
        """999.99 has no mapping; unmapped mode 'provided' → no ICD-10."""
        codes = get_codes_by_system(conditions["cond-006"], "code", ICD10)
        assert len(codes) == 0

    def test_cond006_icd9_retained(self, conditions):
        codes = get_codes_by_system(conditions["cond-006"], "code", ICD9)
        assert "999.99" in codes


class TestHL7DerivedConditionMigration:
    """Integration tests: HL7 v2 → FHIR → extract → migrate."""

    @pytest.fixture
    def conditions(self):
        return load_ndjson("Condition.ndjson")

    def test_hl7_272_4_translated_to_e78_5(self, conditions):
        """272.4 exists only in HL7 input; must appear as E78.5 after migration."""
        matches = find_resources_with_code(conditions, ICD10, "E78.5")
        assert len(matches) >= 1, "No Condition with ICD-10 E78.5 found"

    def test_hl7_272_4_source_preserved(self, conditions):
        """preserve_source_coding=true: ICD-9 272.4 must remain."""
        matches = find_resources_with_code(conditions, ICD9, "272.4")
        assert len(matches) >= 1, "ICD-9 272.4 source coding not preserved"

    def test_hl7_401_1_also_translated(self, conditions):
        """HL7-derived 401.1 should also have I10 translation."""
        matches = find_resources_with_code(conditions, ICD10, "I10")
        # At least 2: one from bulk cond-001, one from HL7 CTRL0001
        assert len(matches) >= 2


# ================================================================
# Phase 3: Terminology Migration — Observations
# ================================================================

class TestObservationTranslations:
    @pytest.fixture
    def observations(self):
        return load_ndjson("Observation.ndjson")

    def test_resource_count(self, observations):
        assert len(observations) == 5

    def test_obs001_has_loinc(self, observations):
        codes = get_codes_by_system(observations["obs-001"], "code", LOINC)
        assert "1558-6" in codes

    def test_obs001_local_removed(self, observations):
        """preserve_source_coding=false: local code must be removed."""
        systems = get_all_systems(observations["obs-001"], "code")
        assert LOCAL_LAB not in systems

    def test_obs002_has_loinc(self, observations):
        codes = get_codes_by_system(observations["obs-002"], "code", LOINC)
        assert "4548-4" in codes

    def test_obs001_value_unchanged(self, observations):
        """Non-code data must pass through unmodified."""
        assert observations["obs-001"]["valueQuantity"]["value"] == 105

    def test_obs005_unmapped_fixed(self, observations):
        """PLATELET has no mapping; unmapped mode 'fixed' → code UNMAPPED."""
        codes = get_codes_by_system(observations["obs-005"], "code", LOINC)
        assert "UNMAPPED" in codes

    def test_obs005_local_removed(self, observations):
        systems = get_all_systems(observations["obs-005"], "code")
        assert LOCAL_LAB not in systems


# ================================================================
# Phase 3: Terminology Migration — AllergyIntolerance
# ================================================================

class TestAllergyTranslations:
    @pytest.fixture
    def allergies(self):
        return load_ndjson("AllergyIntolerance.ndjson")

    def test_resource_count(self, allergies):
        assert len(allergies) == 4

    def test_ai001_snomed_added(self, allergies):
        codes = get_codes_by_system(allergies["ai-001"], "code", SNOMED)
        assert "91936005" in codes

    def test_ai001_local_preserved(self, allergies):
        codes = get_codes_by_system(allergies["ai-001"], "code", LOCAL_ALLERGY)
        assert "PEN-ALLG" in codes

    def test_ai003_other_fields_unchanged(self, allergies):
        """Non-code fields must pass through."""
        assert allergies["ai-003"]["criticality"] == "low"
        assert allergies["ai-003"]["recordedDate"] == "2021-11-08"

    def test_ai004_unmapped_no_snomed(self, allergies):
        """CONTRAST-ALLG has no mapping; unmapped 'provided' → no SNOMED."""
        codes = get_codes_by_system(allergies["ai-004"], "code", SNOMED)
        assert len(codes) == 0

    def test_ai004_local_retained(self, allergies):
        codes = get_codes_by_system(allergies["ai-004"], "code", LOCAL_ALLERGY)
        assert "CONTRAST-ALLG" in codes


# ================================================================
# Phase 4: Pipeline Report
# ================================================================

class TestPipelineReport:
    @pytest.fixture
    def report(self):
        with open(REPORT_PATH) as f:
            return json.load(f)

    @pytest.fixture
    def schema(self):
        with open(SCHEMA_PATH) as f:
            return json.load(f)

    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH)

    def test_report_conforms_to_schema(self, report, schema):
        """Pipeline report must validate against /app/report_schema.json."""
        jsonschema.validate(instance=report, schema=schema)

    def test_conversion_message_count(self, report):
        assert report["conversion"]["messages_processed"] == 3

    def test_conversion_bundles_listed(self, report):
        bundle_ids = {
            b["message_control_id"] for b in report["conversion"]["bundles"]
        }
        assert "CTRL0001" in bundle_ids
        assert "CTRL0002" in bundle_ids
        assert "CTRL0003" in bundle_ids

    def test_summary_hl7_count(self, report):
        assert report["summary"]["hl7_messages_converted"] == 3

    def test_translations_have_required_fields(self, report):
        """Each translation entry must have the schema-required fields."""
        required = {
            "resource_id", "resource_type", "source_system",
            "source_code", "target_system", "target_code", "equivalence",
        }
        for t in report["migration"]["translations"]:
            assert required.issubset(t.keys()), f"Missing keys in {t}"

    def test_report_documents_unmapped(self, report):
        """Report must list unmapped codes with required fields."""
        unmapped_codes = {
            u["source_code"] for u in report["migration"]["unmapped_codes"]
        }
        assert "999.99" in unmapped_codes
        assert "PLATELET" in unmapped_codes
