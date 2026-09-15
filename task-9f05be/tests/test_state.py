
"""
Tests for the FHIR R4 De-identification Pipeline.
Verifies NDJSON processing, contained resources, referential integrity,
HIPAA edge cases, Bundle processing, and cryptographic verification manifest.
"""

import pytest
import json
import hmac
import hashlib
import os
from datetime import date, timedelta


CONFIG_PATH = "/app/config.json"
OUTPUT_DIR = "/app/output"


def hmac_sha256(value: str, key: str) -> str:
    return hmac.new(key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_dateshift_offset(resource_id: str, shift_key: str) -> int:
    combined = resource_id + shift_key
    h = hashlib.sha256(combined.encode("utf-8")).digest()
    uint32 = int.from_bytes(h[:4], byteorder="little", signed=False)
    return (uint32 % 101) - 50


def shift_date(date_str: str, offset: int) -> str:
    d = date.fromisoformat(date_str)
    return (d + timedelta(days=offset)).isoformat()


def shift_datetime_str(dt_str: str, offset: int) -> str:
    date_part = dt_str[:10]
    if dt_str.endswith("Z"):
        tz_part = "Z"
    else:
        tz_part = dt_str[-6:]
    d = date.fromisoformat(date_part)
    shifted = (d + timedelta(days=offset)).isoformat()
    return shifted + "T00:00:00" + tz_part


def hash_reference(ref: str, key: str) -> str:
    if not ref:
        return ref
    if ref == "#":
        return "#"
    if ref.startswith("#"):
        return "#" + hmac_sha256(ref[1:], key)
    if ref.startswith("urn:"):
        idx = ref.index(":", 4)
        return ref[:idx + 1] + hmac_sha256(ref[idx + 1:], key)
    slash = ref.rfind("/")
    if slash >= 0:
        return ref[:slash + 1] + hmac_sha256(ref[slash + 1:], key)
    return hmac_sha256(ref, key)


@pytest.fixture(scope="session")
def config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def hash_key(config):
    return config["parameters"]["cryptoHashKey"]


@pytest.fixture(scope="session")
def shift_key(config):
    return config["parameters"]["dateShiftKey"]


@pytest.fixture(scope="session")
def ndjson_resources():
    path = os.path.join(OUTPUT_DIR, "export.ndjson")
    assert os.path.exists(path), f"NDJSON output not found: {path}"
    resources = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                resources.append(json.loads(line))
    return resources


def load_output(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    assert os.path.exists(path), f"Output file not found: {path}"
    with open(path) as f:
        return json.load(f)


# =============================================================================
# NDJSON structure tests
# =============================================================================

class TestNDJSONStructure:
    def test_line_count(self, ndjson_resources):
        assert len(ndjson_resources) == 4, (
            f"NDJSON should have 4 lines, got {len(ndjson_resources)}"
        )

    def test_resource_types_preserved(self, ndjson_resources):
        types = [r["resourceType"] for r in ndjson_resources]
        assert types == ["Patient", "Observation", "Encounter", "Condition"]

    def test_resource_order_preserved(self, ndjson_resources):
        assert ndjson_resources[0]["resourceType"] == "Patient"
        assert ndjson_resources[3]["resourceType"] == "Condition"


# =============================================================================
# NDJSON Patient tests
# =============================================================================

class TestNDJSONPatient:
    def test_id_hashed(self, ndjson_resources, hash_key):
        patient = ndjson_resources[0]
        expected = hmac_sha256("pat-100", hash_key)
        assert patient["id"] == expected

    def test_name_redacted_use_kept(self, ndjson_resources):
        patient = ndjson_resources[0]
        assert "name" in patient
        name = patient["name"][0]
        assert name.get("use") == "official"
        assert "family" not in name
        assert "given" not in name

    def test_gender_preserved(self, ndjson_resources):
        assert ndjson_resources[0]["gender"] == "male"

    def test_birthdate_shifted(self, ndjson_resources, shift_key):
        patient = ndjson_resources[0]
        offset = compute_dateshift_offset("pat-100", shift_key)
        expected = shift_date("1985-06-15", offset)
        assert patient["birthDate"] == expected

    def test_telecom_removed(self, ndjson_resources):
        assert "telecom" not in ndjson_resources[0]

    def test_address_redacted_state_country_kept(self, ndjson_resources):
        patient = ndjson_resources[0]
        assert "address" in patient
        addr = patient["address"][0]
        assert addr.get("state") == "WA"
        assert addr.get("country") == "US"
        assert "line" not in addr
        assert "city" not in addr
        assert "postalCode" not in addr

    def test_identifier_removed(self, ndjson_resources):
        assert "identifier" not in ndjson_resources[0]

    def test_text_removed(self, ndjson_resources):
        assert "text" not in ndjson_resources[0]

    def test_managing_org_reference_hashed(self, ndjson_resources, hash_key):
        patient = ndjson_resources[0]
        ref = patient["managingOrganization"]["reference"]
        expected = "Organization/" + hmac_sha256("org-100", hash_key)
        assert ref == expected

    def test_contact_name_redacted_use_kept(self, ndjson_resources):
        patient = ndjson_resources[0]
        assert "contact" in patient
        contact = patient["contact"][0]
        if "name" in contact:
            name = contact["name"]
            if isinstance(name, dict):
                assert name.get("use") == "usual"
                assert "family" not in name
                assert "given" not in name

    def test_contact_telecom_removed(self, ndjson_resources):
        patient = ndjson_resources[0]
        contacts = patient.get("contact", [])
        if contacts:
            assert "telecom" not in contacts[0]


# =============================================================================
# NDJSON Observation tests
# =============================================================================

class TestNDJSONObservation:
    def test_id_hashed(self, ndjson_resources, hash_key):
        obs = ndjson_resources[1]
        expected = hmac_sha256("obs-100", hash_key)
        assert obs["id"] == expected

    def test_subject_reference_hashed(self, ndjson_resources, hash_key):
        obs = ndjson_resources[1]
        ref = obs["subject"]["reference"]
        expected = "Patient/" + hmac_sha256("pat-100", hash_key)
        assert ref == expected

    def test_effective_datetime_shifted(self, ndjson_resources, shift_key):
        obs = ndjson_resources[1]
        offset = compute_dateshift_offset("obs-100", shift_key)
        expected = shift_datetime_str("2023-11-20T14:30:00+00:00", offset)
        assert obs["effectiveDateTime"] == expected

    def test_datetime_time_zeroed(self, ndjson_resources):
        obs = ndjson_resources[1]
        assert "T00:00:00" in obs["effectiveDateTime"]

    def test_datetime_timezone_preserved(self, ndjson_resources):
        obs = ndjson_resources[1]
        assert obs["effectiveDateTime"].endswith("+00:00")

    def test_value_quantity_preserved(self, ndjson_resources):
        obs = ndjson_resources[1]
        assert obs["valueQuantity"]["value"] == 175.5

    def test_status_preserved(self, ndjson_resources):
        assert ndjson_resources[1]["status"] == "final"

    def test_code_preserved(self, ndjson_resources):
        obs = ndjson_resources[1]
        assert obs["code"]["coding"][0]["code"] == "8302-2"


# =============================================================================
# NDJSON Encounter tests
# =============================================================================

class TestNDJSONEncounter:
    def test_id_hashed(self, ndjson_resources, hash_key):
        enc = ndjson_resources[2]
        expected = hmac_sha256("enc-100", hash_key)
        assert enc["id"] == expected

    def test_subject_reference_hashed(self, ndjson_resources, hash_key):
        enc = ndjson_resources[2]
        ref = enc["subject"]["reference"]
        expected = "Patient/" + hmac_sha256("pat-100", hash_key)
        assert ref == expected

    def test_period_start_shifted(self, ndjson_resources, shift_key):
        enc = ndjson_resources[2]
        offset = compute_dateshift_offset("enc-100", shift_key)
        expected = shift_datetime_str("2023-11-20T08:00:00+00:00", offset)
        assert enc["period"]["start"] == expected

    def test_period_end_shifted(self, ndjson_resources, shift_key):
        enc = ndjson_resources[2]
        offset = compute_dateshift_offset("enc-100", shift_key)
        expected = shift_datetime_str("2023-11-20T17:00:00+00:00", offset)
        assert enc["period"]["end"] == expected

    def test_period_time_zeroed(self, ndjson_resources):
        enc = ndjson_resources[2]
        assert "T00:00:00" in enc["period"]["start"]
        assert "T00:00:00" in enc["period"]["end"]

    def test_participant_reference_hashed(self, ndjson_resources, hash_key):
        enc = ndjson_resources[2]
        ref = enc["participant"][0]["individual"]["reference"]
        expected = "Practitioner/" + hmac_sha256("pract-100", hash_key)
        assert ref == expected

    def test_status_preserved(self, ndjson_resources):
        assert ndjson_resources[2]["status"] == "finished"

    def test_class_preserved(self, ndjson_resources):
        enc = ndjson_resources[2]
        assert enc["class"]["code"] == "AMB"


# =============================================================================
# NDJSON Condition tests
# =============================================================================

class TestNDJSONCondition:
    def test_id_hashed(self, ndjson_resources, hash_key):
        cond = ndjson_resources[3]
        expected = hmac_sha256("cond-100", hash_key)
        assert cond["id"] == expected

    def test_subject_reference_hashed(self, ndjson_resources, hash_key):
        cond = ndjson_resources[3]
        ref = cond["subject"]["reference"]
        expected = "Patient/" + hmac_sha256("pat-100", hash_key)
        assert ref == expected

    def test_onset_datetime_shifted(self, ndjson_resources, shift_key):
        cond = ndjson_resources[3]
        offset = compute_dateshift_offset("cond-100", shift_key)
        expected = shift_datetime_str("2020-03-15T00:00:00Z", offset)
        assert cond["onsetDateTime"] == expected

    def test_onset_timezone_preserved(self, ndjson_resources):
        cond = ndjson_resources[3]
        assert cond["onsetDateTime"].endswith("Z")

    def test_recorder_reference_hashed(self, ndjson_resources, hash_key):
        cond = ndjson_resources[3]
        ref = cond["recorder"]["reference"]
        expected = "Practitioner/" + hmac_sha256("pract-100", hash_key)
        assert ref == expected

    def test_clinical_status_preserved(self, ndjson_resources):
        cond = ndjson_resources[3]
        assert cond["clinicalStatus"]["coding"][0]["code"] == "active"

    def test_code_preserved(self, ndjson_resources):
        cond = ndjson_resources[3]
        assert cond["code"]["coding"][0]["code"] == "73211009"


# =============================================================================
# Cross-resource referential integrity
# =============================================================================

class TestReferentialIntegrity:
    def test_patient_id_matches_observation_subject(self, ndjson_resources):
        patient_id = ndjson_resources[0]["id"]
        obs_ref = ndjson_resources[1]["subject"]["reference"]
        assert obs_ref == f"Patient/{patient_id}"

    def test_patient_id_matches_encounter_subject(self, ndjson_resources):
        patient_id = ndjson_resources[0]["id"]
        enc_ref = ndjson_resources[2]["subject"]["reference"]
        assert enc_ref == f"Patient/{patient_id}"

    def test_patient_id_matches_condition_subject(self, ndjson_resources):
        patient_id = ndjson_resources[0]["id"]
        cond_ref = ndjson_resources[3]["subject"]["reference"]
        assert cond_ref == f"Patient/{patient_id}"

    def test_encounter_and_condition_practitioner_match(self, ndjson_resources):
        enc_ref = ndjson_resources[2]["participant"][0]["individual"]["reference"]
        cond_ref = ndjson_resources[3]["recorder"]["reference"]
        assert enc_ref == cond_ref, (
            "Same Practitioner ID should produce same hash across resources"
        )


# =============================================================================
# Contained resource tests
# =============================================================================

class TestContainedResources:
    def test_patient_id_hashed(self, hash_key):
        patient = load_output("patient-contained.json")
        expected = hmac_sha256("pat-200", hash_key)
        assert patient["id"] == expected

    def test_patient_name_redacted_use_kept(self):
        patient = load_output("patient-contained.json")
        assert "name" in patient
        name = patient["name"][0]
        assert name.get("use") == "official"
        assert "family" not in name

    def test_patient_gender_preserved(self):
        patient = load_output("patient-contained.json")
        assert patient["gender"] == "female"

    def test_patient_birthdate_shifted(self, shift_key):
        patient = load_output("patient-contained.json")
        offset = compute_dateshift_offset("pat-200", shift_key)
        expected = shift_date("1978-11-03", offset)
        assert patient["birthDate"] == expected

    def test_patient_telecom_removed(self):
        patient = load_output("patient-contained.json")
        assert "telecom" not in patient

    def test_patient_address_redacted_state_country_kept(self):
        patient = load_output("patient-contained.json")
        assert "address" in patient
        addr = patient["address"][0]
        assert addr.get("state") == "OR"
        assert addr.get("country") == "US"
        assert "line" not in addr
        assert "city" not in addr

    def test_contained_practitioner_id_hashed(self, hash_key):
        patient = load_output("patient-contained.json")
        assert "contained" in patient
        pract = [c for c in patient["contained"]
                 if c["resourceType"] == "Practitioner"][0]
        expected = hmac_sha256("pract-inline", hash_key)
        assert pract["id"] == expected

    def test_contained_practitioner_name_redacted(self):
        patient = load_output("patient-contained.json")
        pract = [c for c in patient["contained"]
                 if c["resourceType"] == "Practitioner"][0]
        if "name" in pract:
            name = pract["name"][0] if isinstance(pract["name"], list) else pract["name"]
            assert name.get("use") == "official"
            assert "family" not in name

    def test_contained_organization_id_hashed(self, hash_key):
        patient = load_output("patient-contained.json")
        org = [c for c in patient["contained"]
               if c["resourceType"] == "Organization"][0]
        expected = hmac_sha256("org-inline", hash_key)
        assert org["id"] == expected

    def test_contained_organization_name_preserved(self):
        patient = load_output("patient-contained.json")
        org = [c for c in patient["contained"]
               if c["resourceType"] == "Organization"][0]
        assert org.get("name") == "City Hospital", (
            "Organization.name (string type) should be preserved — "
            "no nodesByType rule matches plain strings"
        )

    def test_contained_organization_identifier_preserved(self):
        patient = load_output("patient-contained.json")
        org = [c for c in patient["contained"]
               if c["resourceType"] == "Organization"][0]
        assert "identifier" in org, (
            "Organization.identifier must be kept per 'Organization.identifier' keep rule, "
            "which takes precedence over nodesByType('Identifier') redact"
        )
        assert org["identifier"][0]["value"] == "ORG-67890"

    def test_contained_organization_address_redacted_state_kept(self):
        patient = load_output("patient-contained.json")
        org = [c for c in patient["contained"]
               if c["resourceType"] == "Organization"][0]
        assert "address" in org
        addr = org["address"][0]
        assert addr.get("state") == "OR"
        assert addr.get("country") == "US"
        assert "line" not in addr
        assert "city" not in addr

    def test_general_practitioner_fragment_reference(self, hash_key):
        patient = load_output("patient-contained.json")
        ref = patient["generalPractitioner"][0]["reference"]
        expected = "#" + hmac_sha256("pract-inline", hash_key)
        assert ref == expected, (
            "Fragment reference #pract-inline should hash to # + hmac(pract-inline)"
        )

    def test_managing_org_fragment_reference(self, hash_key):
        patient = load_output("patient-contained.json")
        ref = patient["managingOrganization"]["reference"]
        expected = "#" + hmac_sha256("org-inline", hash_key)
        assert ref == expected

    def test_fragment_reference_matches_contained_id(self, hash_key):
        patient = load_output("patient-contained.json")
        pract = [c for c in patient["contained"]
                 if c["resourceType"] == "Practitioner"][0]
        gp_ref = patient["generalPractitioner"][0]["reference"]
        assert gp_ref == "#" + pract["id"], (
            "Fragment reference hash must match contained resource's hashed ID"
        )


# =============================================================================
# Elderly patient (age > 89) tests
# =============================================================================

class TestElderlyPatient:
    def test_birthdate_fully_redacted(self):
        patient = load_output("elderly-patient.json")
        assert "birthDate" not in patient, (
            "Patient born 1920 (age > 89) must have birthDate fully redacted"
        )

    def test_id_hashed(self, hash_key):
        patient = load_output("elderly-patient.json")
        expected = hmac_sha256("pat-300", hash_key)
        assert patient["id"] == expected

    def test_gender_preserved(self):
        patient = load_output("elderly-patient.json")
        assert patient["gender"] == "male"

    def test_name_redacted_use_kept(self):
        patient = load_output("elderly-patient.json")
        assert "name" in patient
        assert patient["name"][0].get("use") == "official"
        assert "family" not in patient["name"][0]

    def test_address_state_kept(self):
        patient = load_output("elderly-patient.json")
        assert "address" in patient
        assert patient["address"][0].get("state") == "CA"


# =============================================================================
# Partial date tests
# =============================================================================

class TestPartialDate:
    def test_partial_date_reduced_to_year(self):
        patient = load_output("partial-date-patient.json")
        assert patient["birthDate"] == "2015", (
            "Partial date '2015-02' should be reduced to '2015' "
            "when enablePartialDatesForRedact is true"
        )

    def test_id_hashed(self, hash_key):
        patient = load_output("partial-date-patient.json")
        expected = hmac_sha256("pat-400", hash_key)
        assert patient["id"] == expected

    def test_gender_preserved(self):
        patient = load_output("partial-date-patient.json")
        assert patient["gender"] == "female"


# =============================================================================
# Bundle processing tests
# =============================================================================

class TestBundleProcessing:
    def test_bundle_output_exists(self):
        path = os.path.join(OUTPUT_DIR, "bundle.json")
        assert os.path.exists(path), "bundle.json output not found"

    def test_resource_type_preserved(self):
        bundle = load_output("bundle.json")
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "collection"

    def test_entry_count_preserved(self):
        bundle = load_output("bundle.json")
        assert len(bundle["entry"]) == 2

    def test_fullurl_redacted(self):
        bundle = load_output("bundle.json")
        for i, entry in enumerate(bundle["entry"]):
            assert "fullUrl" not in entry, (
                f"Bundle.entry[{i}].fullUrl should be redacted"
            )

    def test_patient_entry_id_hashed(self, hash_key):
        bundle = load_output("bundle.json")
        patient = bundle["entry"][0]["resource"]
        expected = hmac_sha256("patient-001", hash_key)
        assert patient["id"] == expected

    def test_patient_entry_name_redacted_use_kept(self):
        bundle = load_output("bundle.json")
        patient = bundle["entry"][0]["resource"]
        assert "name" in patient
        name = patient["name"][0]
        assert name.get("use") == "official"
        assert "family" not in name
        assert "given" not in name

    def test_patient_entry_gender_preserved(self):
        bundle = load_output("bundle.json")
        patient = bundle["entry"][0]["resource"]
        assert patient["gender"] == "female"

    def test_patient_entry_telecom_removed(self):
        bundle = load_output("bundle.json")
        patient = bundle["entry"][0]["resource"]
        assert "telecom" not in patient

    def test_patient_entry_address_redacted_state_kept(self):
        bundle = load_output("bundle.json")
        patient = bundle["entry"][0]["resource"]
        assert "address" in patient
        addr = patient["address"][0]
        assert addr.get("state") == "OR"
        assert addr.get("country") == "US"
        assert "line" not in addr
        assert "city" not in addr

    def test_patient_entry_birthdate_shifted(self, shift_key):
        bundle = load_output("bundle.json")
        patient = bundle["entry"][0]["resource"]
        offset = compute_dateshift_offset("patient-001", shift_key)
        expected = shift_date("1990-03-25", offset)
        assert patient["birthDate"] == expected

    def test_observation_entry_id_hashed(self, hash_key):
        bundle = load_output("bundle.json")
        obs = bundle["entry"][1]["resource"]
        expected = hmac_sha256("obs-bundle-001", hash_key)
        assert obs["id"] == expected

    def test_observation_entry_subject_hashed(self, hash_key):
        bundle = load_output("bundle.json")
        obs = bundle["entry"][1]["resource"]
        ref = obs["subject"]["reference"]
        expected = "Patient/" + hmac_sha256("patient-001", hash_key)
        assert ref == expected

    def test_observation_entry_datetime_shifted(self, shift_key):
        bundle = load_output("bundle.json")
        obs = bundle["entry"][1]["resource"]
        offset = compute_dateshift_offset("obs-bundle-001", shift_key)
        expected = shift_datetime_str("2024-01-10T09:00:00-05:00", offset)
        assert obs["effectiveDateTime"] == expected

    def test_observation_entry_time_zeroed(self):
        bundle = load_output("bundle.json")
        obs = bundle["entry"][1]["resource"]
        assert "T00:00:00" in obs["effectiveDateTime"]

    def test_observation_entry_timezone_preserved(self):
        bundle = load_output("bundle.json")
        obs = bundle["entry"][1]["resource"]
        assert obs["effectiveDateTime"].endswith("-05:00")

    def test_observation_entry_value_preserved(self):
        bundle = load_output("bundle.json")
        obs = bundle["entry"][1]["resource"]
        assert obs["valueQuantity"]["value"] == 68.2

    def test_observation_entry_status_preserved(self):
        bundle = load_output("bundle.json")
        obs = bundle["entry"][1]["resource"]
        assert obs["status"] == "final"

    def test_cross_entry_referential_integrity(self):
        bundle = load_output("bundle.json")
        patient_id = bundle["entry"][0]["resource"]["id"]
        obs_ref = bundle["entry"][1]["resource"]["subject"]["reference"]
        assert obs_ref == f"Patient/{patient_id}", (
            "Observation subject reference must match Patient id within same Bundle"
        )


# =============================================================================
# Crypto manifest tests
# =============================================================================

class TestCryptoManifest:
    def test_manifest_exists(self):
        path = os.path.join(OUTPUT_DIR, "crypto_manifest.json")
        assert os.path.exists(path), "crypto_manifest.json not found"

    def test_manifest_has_verifications(self):
        manifest = load_output("crypto_manifest.json")
        assert "verifications" in manifest
        assert len(manifest["verifications"]) > 0

    def test_manifest_covers_all_resources(self):
        manifest = load_output("crypto_manifest.json")
        entries = manifest["verifications"]
        original_ids = {e["original_id"] for e in entries}
        required_ids = {
            "pat-100", "obs-100", "enc-100", "cond-100",
            "pat-200", "pract-inline", "org-inline",
            "pat-300", "pat-400",
            "patient-001", "obs-bundle-001",
        }
        for rid in required_ids:
            assert rid in original_ids, (
                f"Manifest missing entry for resource ID '{rid}'"
            )

    def test_manifest_hashes_correct(self, hash_key):
        manifest = load_output("crypto_manifest.json")
        for entry in manifest["verifications"]:
            expected = hmac_sha256(entry["original_id"], hash_key)
            assert entry["hashed_id"] == expected, (
                f"Hash mismatch for {entry['original_id']}: "
                f"expected {expected}, got {entry['hashed_id']}"
            )

    def test_manifest_openssl_verified(self, hash_key):
        manifest = load_output("crypto_manifest.json")
        for entry in manifest["verifications"]:
            assert entry.get("openssl_output") == entry["hashed_id"], (
                f"openssl verification mismatch for {entry['original_id']}"
            )
            assert entry.get("verified") is True, (
                f"Entry for {entry['original_id']} not marked as verified"
            )

    def test_manifest_entries_have_required_fields(self):
        manifest = load_output("crypto_manifest.json")
        required_fields = {
            "source_file", "resource_type", "original_id",
            "hashed_id", "openssl_output", "verified"
        }
        for entry in manifest["verifications"]:
            for field in required_fields:
                assert field in entry, (
                    f"Manifest entry missing field '{field}': {entry}"
                )
