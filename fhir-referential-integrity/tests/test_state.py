
import json
import hmac
import hashlib
import os
import re
import subprocess
import pytest
from datetime import datetime, timedelta, date

BUNDLE_PATH = "/app/data/bundle.json"
OUTPUT_PATH = "/app/output/anonymized.json"
CONFIG_PATH = "/app/config.json"
VALIDATE_SCRIPT = "/app/validate.sh"
PHI_SCAN_PATH = "/app/output/phi_scan.json"

CRYPTO_KEY = "hipaa-safe-harbor-2024"
DATE_SHIFT_KEY = "date-shift-key-2024"
DATE_SHIFT_RANGE = 50
REFERENCE_DATE = date(2024, 6, 1)

ORIGINAL_IDS = [
    "pat-001", "pat-002", "pat-003",
    "pract-001", "pract-002",
    "org-001", "org-002",
    "enc-001", "enc-002", "enc-003",
    "obs-001", "obs-002", "obs-003",
    "claim-001", "cov-001",
    "cond-001", "med-001", "allergy-001",
]

RESTRICTED_ZIPS = {
    "036", "059", "063", "102", "203", "556", "692",
    "790", "821", "823", "830", "831", "878", "879",
    "884", "890", "893",
}

PHI_PATIENT_NAMES = [
    "Smith", "Doe", "Johnson", "John", "Jane", "Robert",
    "Michael", "Elizabeth", "Mary", "Johnny", "Lee",
]

PHI_PRACTITIONER_NAMES = ["Williams", "Anderson", "Alice", "Bob"]


def compute_hash(key, value):
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def compute_date_offset(resource_id):
    h = hmac.new(
        DATE_SHIFT_KEY.encode(), resource_id.encode(), hashlib.sha256
    ).digest()
    n = int.from_bytes(h[:4], byteorder="big")
    return (n % (2 * DATE_SHIFT_RANGE + 1)) - DATE_SHIFT_RANGE


def get_resources(bundle):
    return [e["resource"] for e in bundle["entry"]]


def find_resource(resources, resource_type, hashed_id):
    for r in resources:
        if r["resourceType"] == resource_type and r["id"] == hashed_id:
            return r
    return None


def collect_references(obj, refs=None):
    if refs is None:
        refs = []
    if isinstance(obj, dict):
        if "reference" in obj and isinstance(obj["reference"], str):
            refs.append(obj)
        for v in obj.values():
            collect_references(v, refs)
    elif isinstance(obj, list):
        for item in obj:
            collect_references(item, refs)
    return refs


def collect_all_strings(obj, strings=None):
    if strings is None:
        strings = []
    if isinstance(obj, str):
        strings.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_all_strings(v, strings)
    elif isinstance(obj, list):
        for item in obj:
            collect_all_strings(item, strings)
    return strings


@pytest.fixture(scope="module")
def original():
    with open(BUNDLE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def output():
    assert os.path.exists(OUTPUT_PATH), (
        f"Output file {OUTPUT_PATH} not found. "
        "The anonymization script must write its output here."
    )
    with open(OUTPUT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def out_resources(output):
    return get_resources(output)


@pytest.fixture(scope="module")
def config():
    assert os.path.exists(CONFIG_PATH), (
        f"Configuration file {CONFIG_PATH} not found. "
        "A FHIRPath anonymization configuration must be written here."
    )
    with open(CONFIG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def phi_scan():
    """Run validate.sh if needed, then load the PHI scan report."""
    if os.path.exists(VALIDATE_SCRIPT) and not os.path.exists(PHI_SCAN_PATH):
        subprocess.run(["bash", VALIDATE_SCRIPT], check=False, timeout=60)
    assert os.path.exists(PHI_SCAN_PATH), (
        f"PHI scan report not found at {PHI_SCAN_PATH}. "
        "validate.sh must produce this file."
    )
    with open(PHI_SCAN_PATH) as f:
        return json.load(f)


# ── FHIRPath Configuration Tests ───────────────────────────────────────────


class TestFHIRPathConfig:
    def test_config_valid_json(self, config):
        assert isinstance(config, dict)

    def test_fhir_version_r4(self, config):
        assert config.get("fhirVersion") == "R4"

    def test_has_fhirpath_rules(self, config):
        assert "fhirPathRules" in config
        assert isinstance(config["fhirPathRules"], list)
        assert len(config["fhirPathRules"]) >= 8, (
            "Expected at least 8 FHIRPath rules covering major PHI types"
        )

    def test_has_resource_id_cryptohash(self, config):
        """Resource.id must be targeted with cryptoHash."""
        rules = config["fhirPathRules"]
        id_hash_rules = [
            r for r in rules
            if "Resource.id" in r.get("path", "")
            and r.get("method", "").lower() == "cryptohash"
        ]
        assert len(id_hash_rules) > 0, (
            "Missing cryptoHash rule for Resource.id"
        )

    def test_has_reference_cryptohash(self, config):
        """References must be hashed for referential integrity."""
        rules = config["fhirPathRules"]
        ref_rules = [
            r for r in rules
            if "Reference" in r.get("path", "")
            and "reference" in r.get("path", "")
            and r.get("method", "").lower() == "cryptohash"
        ]
        assert len(ref_rules) > 0, (
            "Missing cryptoHash rule for Reference.reference"
        )

    def test_has_humanname_rule(self, config):
        rules_text = json.dumps(config["fhirPathRules"]).lower()
        assert "humanname" in rules_text, (
            "Missing rule targeting HumanName data type"
        )

    def test_has_contactpoint_rule(self, config):
        rules_text = json.dumps(config["fhirPathRules"]).lower()
        assert "contactpoint" in rules_text or "telecom" in rules_text, (
            "Missing rule targeting ContactPoint/telecom"
        )

    def test_has_address_rule(self, config):
        rules_text = json.dumps(config["fhirPathRules"]).lower()
        assert "address" in rules_text, (
            "Missing rule targeting Address data type"
        )

    def test_has_narrative_rule(self, config):
        rules_text = json.dumps(config["fhirPathRules"]).lower()
        assert "narrative" in rules_text or "resource.text" in rules_text, (
            "Missing rule for Narrative/Resource.text removal"
        )

    def test_has_date_shift_rules(self, config):
        rules = config["fhirPathRules"]
        dateshift_rules = [
            r for r in rules
            if r.get("method", "").lower() in ("dateshift", "dateshiftmethod")
        ]
        assert len(dateshift_rules) > 0, (
            "Missing dateShift rules for temporal types"
        )

    def test_has_identifier_hash_rule(self, config):
        rules_text = json.dumps(config["fhirPathRules"]).lower()
        assert "identifier" in rules_text, (
            "Missing rule targeting Identifier values"
        )

    def test_has_parameters_section(self, config):
        assert "parameters" in config
        params = config["parameters"]
        assert "cryptoHashKey" in params, "Missing cryptoHashKey in parameters"
        assert "dateShiftKey" in params, "Missing dateShiftKey in parameters"

    def test_keep_rules_precede_catchall(self, config):
        """Keep rules for preserved fields must appear before catch-all redact rules."""
        rules = config["fhirPathRules"]
        paths = [r.get("path", "") for r in rules]
        methods = [r.get("method", "") for r in rules]

        # Find indices of keep rules for address sub-fields
        keep_address_indices = [
            i for i, (p, m) in enumerate(zip(paths, methods))
            if m.lower() == "keep" and "address" in p.lower()
            and ("country" in p.lower() or "state" in p.lower())
        ]

        # Find indices of catch-all address redact
        catchall_addr_indices = [
            i for i, (p, m) in enumerate(zip(paths, methods))
            if m.lower() == "redact"
            and ("nodesByType" in p or "nodesByName" in p)
            and "Address" in p
            and "country" not in p.lower()
            and "state" not in p.lower()
        ]

        if keep_address_indices and catchall_addr_indices:
            assert min(keep_address_indices) < min(catchall_addr_indices), (
                "Keep rules for Address.state/country must appear "
                "before catch-all Address redact rule"
            )


# ── PHI Scanner Tests ──────────────────────────────────────────────────────


class TestPHIScanner:
    def test_validate_script_exists(self):
        assert os.path.exists(VALIDATE_SCRIPT), (
            f"Validation script not found at {VALIDATE_SCRIPT}"
        )

    def test_validate_script_uses_jq(self):
        with open(VALIDATE_SCRIPT) as f:
            content = f.read()
        assert "jq " in content or "jq\n" in content or "$(jq" in content, (
            "validate.sh must use jq for structural validation"
        )

    def test_validate_script_uses_openssl(self):
        with open(VALIDATE_SCRIPT) as f:
            content = f.read()
        assert "openssl" in content, (
            "validate.sh must use openssl for independent hash verification"
        )

    def test_phi_scan_report_exists(self, phi_scan):
        assert isinstance(phi_scan, dict)

    def test_phi_scan_ids_valid(self, phi_scan):
        assert phi_scan.get("ids_valid") is True, (
            "PHI scan reports invalid resource IDs"
        )

    def test_phi_scan_references_valid(self, phi_scan):
        assert phi_scan.get("references_valid") is True, (
            "PHI scan reports invalid references"
        )

    def test_phi_scan_names_clean(self, phi_scan):
        assert phi_scan.get("names_clean") is True, (
            "PHI scan detected residual patient/practitioner names"
        )

    def test_phi_scan_contacts_clean(self, phi_scan):
        assert phi_scan.get("contacts_clean") is True, (
            "PHI scan detected residual contact information"
        )

    def test_phi_scan_addresses_clean(self, phi_scan):
        assert phi_scan.get("addresses_clean") is True, (
            "PHI scan detected un-generalized postal codes"
        )

    def test_phi_scan_hash_verified(self, phi_scan):
        assert phi_scan.get("hash_verified") is True, (
            "PHI scan could not verify HMAC-SHA256 hash via openssl"
        )


# ── Output Structure Tests ─────────────────────────────────────────────────


class TestOutputStructure:
    def test_valid_json_bundle(self, output):
        assert isinstance(output, dict)
        assert output.get("resourceType") == "Bundle"

    def test_resource_count(self, original, output):
        assert len(output["entry"]) == len(original["entry"])

    def test_resource_types_preserved(self, original, output):
        orig_types = sorted(
            e["resource"]["resourceType"] for e in original["entry"]
        )
        out_types = sorted(
            e["resource"]["resourceType"] for e in output["entry"]
        )
        assert orig_types == out_types


# ── CryptoHash Tests ───────────────────────────────────────────────────────


class TestCryptoHash:
    def test_all_ids_are_64_char_hex(self, out_resources):
        for r in out_resources:
            rid = r["id"]
            assert len(rid) == 64, (
                f"{r['resourceType']} id length {len(rid)} != 64"
            )
            assert all(c in "0123456789abcdef" for c in rid), (
                f"{r['resourceType']} id is not lowercase hex: {rid[:20]}..."
            )

    @pytest.mark.parametrize("orig_id", ORIGINAL_IDS)
    def test_hash_matches_hmac_sha256(self, out_resources, orig_id):
        expected = compute_hash(CRYPTO_KEY, orig_id)
        matches = [r for r in out_resources if r["id"] == expected]
        assert len(matches) == 1, (
            f"No resource found with expected hash for '{orig_id}': "
            f"{expected[:24]}..."
        )

    def test_identifier_values_hashed(self, out_resources):
        for r in out_resources:
            if "identifier" not in r:
                continue
            for ident in r["identifier"]:
                if "value" not in ident:
                    continue
                val = ident["value"]
                assert len(val) == 64 and all(
                    c in "0123456789abcdef" for c in val
                ), (
                    f"Identifier value in {r['resourceType']}/{r['id'][:8]}... "
                    f"not properly hashed: {val[:20]}..."
                )

    def test_mrn_hash_correct(self, out_resources):
        expected_mrn = compute_hash(CRYPTO_KEY, "MRN-78429")
        pat_hash = compute_hash(CRYPTO_KEY, "pat-001")
        pat = find_resource(out_resources, "Patient", pat_hash)
        assert pat is not None
        id_values = [
            i["value"]
            for i in pat.get("identifier", [])
            if "system" in i and "mrn" in i["system"]
        ]
        assert expected_mrn in id_values, "MRN-78429 not correctly hashed"

    def test_ssn_hash_correct(self, out_resources):
        expected_ssn = compute_hash(CRYPTO_KEY, "999-34-5678")
        pat_hash = compute_hash(CRYPTO_KEY, "pat-001")
        pat = find_resource(out_resources, "Patient", pat_hash)
        assert pat is not None
        id_values = [
            i["value"]
            for i in pat.get("identifier", [])
            if "system" in i and "ssn" in i["system"]
        ]
        assert expected_ssn in id_values, "SSN not correctly hashed"

    def test_npi_hash_correct(self, out_resources):
        expected_npi = compute_hash(CRYPTO_KEY, "1234567890")
        pract_hash = compute_hash(CRYPTO_KEY, "pract-001")
        pract = find_resource(out_resources, "Practitioner", pract_hash)
        assert pract is not None
        id_values = [i["value"] for i in pract.get("identifier", [])]
        assert expected_npi in id_values, "NPI not correctly hashed"


# ── Referential Integrity Tests ────────────────────────────────────────────


class TestReferentialIntegrity:
    def test_all_references_hashed(self, out_resources):
        ref_pattern = re.compile(r"^([A-Z][a-zA-Z]+)/(.+)$")
        for r in out_resources:
            for ref_obj in collect_references(r):
                ref_str = ref_obj["reference"]
                m = ref_pattern.match(ref_str)
                assert m, f"Malformed reference: {ref_str}"
                ref_id = m.group(2)
                assert len(ref_id) == 64 and all(
                    c in "0123456789abcdef" for c in ref_id
                ), (
                    f"Un-hashed reference {ref_str} in "
                    f"{r['resourceType']}/{r['id'][:8]}..."
                )

    def test_all_references_resolve(self, out_resources):
        valid_refs = {
            f"{r['resourceType']}/{r['id']}" for r in out_resources
        }
        for r in out_resources:
            for ref_obj in collect_references(r):
                ref_str = ref_obj["reference"]
                assert ref_str in valid_refs, (
                    f"Broken reference {ref_str} in "
                    f"{r['resourceType']}/{r['id'][:8]}..."
                )

    def test_patient_ref_consistency(self, out_resources):
        pat1_ref = f"Patient/{compute_hash(CRYPTO_KEY, 'pat-001')}"

        enc1 = find_resource(
            out_resources, "Encounter", compute_hash(CRYPTO_KEY, "enc-001")
        )
        assert enc1["subject"]["reference"] == pat1_ref

        obs1 = find_resource(
            out_resources, "Observation", compute_hash(CRYPTO_KEY, "obs-001")
        )
        assert obs1["subject"]["reference"] == pat1_ref

        claim = find_resource(
            out_resources, "Claim", compute_hash(CRYPTO_KEY, "claim-001")
        )
        assert claim["patient"]["reference"] == pat1_ref

        cov = find_resource(
            out_resources, "Coverage", compute_hash(CRYPTO_KEY, "cov-001")
        )
        assert cov["beneficiary"]["reference"] == pat1_ref

        cond = find_resource(
            out_resources, "Condition", compute_hash(CRYPTO_KEY, "cond-001")
        )
        assert cond["subject"]["reference"] == pat1_ref

    def test_practitioner_ref_consistency(self, out_resources):
        pract1_ref = f"Practitioner/{compute_hash(CRYPTO_KEY, 'pract-001')}"

        enc1 = find_resource(
            out_resources, "Encounter", compute_hash(CRYPTO_KEY, "enc-001")
        )
        assert enc1["participant"][0]["individual"]["reference"] == pract1_ref

        enc3 = find_resource(
            out_resources, "Encounter", compute_hash(CRYPTO_KEY, "enc-003")
        )
        assert enc3["participant"][0]["individual"]["reference"] == pract1_ref

        claim = find_resource(
            out_resources, "Claim", compute_hash(CRYPTO_KEY, "claim-001")
        )
        assert claim["careTeam"][0]["provider"]["reference"] == pract1_ref

        allergy = find_resource(
            out_resources,
            "AllergyIntolerance",
            compute_hash(CRYPTO_KEY, "allergy-001"),
        )
        assert allergy["recorder"]["reference"] == pract1_ref

    def test_organization_ref_consistency(self, out_resources):
        org1_ref = f"Organization/{compute_hash(CRYPTO_KEY, 'org-001')}"

        pat1 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-001")
        )
        assert pat1["managingOrganization"]["reference"] == org1_ref

        enc1 = find_resource(
            out_resources, "Encounter", compute_hash(CRYPTO_KEY, "enc-001")
        )
        assert enc1["serviceProvider"]["reference"] == org1_ref

    def test_reference_display_removed(self, out_resources):
        for r in out_resources:
            for ref_obj in collect_references(r):
                assert "display" not in ref_obj, (
                    f"Reference display not removed in "
                    f"{r['resourceType']}/{r['id'][:8]}...: "
                    f"{ref_obj}"
                )


# ── PHI Removal Tests ─────────────────────────────────────────────────────


class TestPHIRemoval:
    def test_no_patient_names(self, output):
        all_strings = collect_all_strings(output)
        for name in PHI_PATIENT_NAMES:
            for s in all_strings:
                if any(
                    skip in s
                    for skip in ("http", "urn:", "hl7", "snomed", "loinc")
                ):
                    continue
                assert name.lower() not in s.lower(), (
                    f"PHI patient name '{name}' found in output string: '{s}'"
                )

    def test_no_practitioner_names(self, output):
        all_strings = collect_all_strings(output)
        for name in PHI_PRACTITIONER_NAMES:
            for s in all_strings:
                if any(
                    skip in s
                    for skip in ("http", "urn:", "hl7", "snomed", "loinc")
                ):
                    continue
                assert name.lower() not in s.lower(), (
                    f"PHI practitioner name '{name}' found: '{s}'"
                )

    def test_no_phone_numbers(self, output):
        all_strings = collect_all_strings(output)
        phone_re = re.compile(r"\(\d{3}\)\s*\d{3}-\d{4}")
        for s in all_strings:
            assert not phone_re.search(s), (
                f"Phone number found in output: '{s}'"
            )

    def test_no_email_addresses(self, output):
        all_strings = collect_all_strings(output)
        for s in all_strings:
            assert "john.smith@email.com" not in s.lower()

    def test_no_ssn_plaintext(self, output):
        all_strings = collect_all_strings(output)
        for s in all_strings:
            assert "999-34-5678" not in s

    def test_no_street_addresses(self, output):
        all_strings = collect_all_strings(output)
        streets = [
            "123 Main Street", "456 Oak Avenue", "789 Pine Road",
            "11811 NE 1st Street", "456 Market Street", "Apt 4B",
        ]
        for street in streets:
            for s in all_strings:
                assert street.lower() not in s.lower(), (
                    f"Street address '{street}' found in output: '{s}'"
                )

    def test_text_narratives_removed(self, out_resources):
        for r in out_resources:
            if "text" in r and isinstance(r["text"], dict):
                assert "div" not in r["text"], (
                    f"Narrative text not removed from "
                    f"{r['resourceType']}/{r['id'][:8]}..."
                )

    def test_contact_name_redacted(self, out_resources):
        pat1 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-001")
        )
        assert pat1 is not None
        if "contact" in pat1:
            for contact in pat1["contact"]:
                if "name" in contact:
                    name = contact["name"]
                    assert "family" not in name, "Contact family not redacted"
                    assert "given" not in name, "Contact given not redacted"

    def test_contact_telecom_redacted(self, out_resources):
        pat1 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-001")
        )
        assert pat1 is not None
        if "contact" in pat1:
            for contact in pat1["contact"]:
                if "telecom" in contact:
                    for tc in contact["telecom"]:
                        assert "value" not in tc, (
                            "Contact telecom value not redacted"
                        )


# ── DateShift Tests ────────────────────────────────────────────────────────


class TestDateShift:
    def test_patient_birthdate_shifted(self, out_resources):
        pat1 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-001")
        )
        assert pat1 is not None
        assert "birthDate" in pat1, "pat-001 birthDate missing"
        assert pat1["birthDate"] != "1985-03-15", (
            "pat-001 birthDate not shifted"
        )

    def test_birthdate_shift_deterministic(self, out_resources):
        pat1 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-001")
        )
        assert pat1 is not None and "birthDate" in pat1
        offset = compute_date_offset("pat-001")
        orig = date(1985, 3, 15)
        expected = (orig + timedelta(days=offset)).isoformat()
        assert pat1["birthDate"] == expected, (
            f"Expected {expected}, got {pat1['birthDate']}"
        )

    def test_birthdate_shift_within_range(self, out_resources):
        pat2 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-002")
        )
        assert pat2 is not None and "birthDate" in pat2
        orig = date(1990, 7, 22)
        shifted = datetime.strptime(pat2["birthDate"], "%Y-%m-%d").date()
        delta = (shifted - orig).days
        assert -50 <= delta <= 50, f"Date shift {delta} out of range"

    def test_encounter_dates_shifted_consistently(self, out_resources):
        enc1 = find_resource(
            out_resources, "Encounter", compute_hash(CRYPTO_KEY, "enc-001")
        )
        assert enc1 is not None
        orig_start = date(2024, 1, 15)
        orig_end = date(2024, 1, 15)
        shifted_start = datetime.strptime(
            enc1["period"]["start"][:10], "%Y-%m-%d"
        ).date()
        shifted_end = datetime.strptime(
            enc1["period"]["end"][:10], "%Y-%m-%d"
        ).date()
        delta_start = (shifted_start - orig_start).days
        delta_end = (shifted_end - orig_end).days
        assert delta_start == delta_end, (
            f"Inconsistent shift in enc-001: start={delta_start}, "
            f"end={delta_end}"
        )

    def test_encounter_date_shift_deterministic(self, out_resources):
        enc1 = find_resource(
            out_resources, "Encounter", compute_hash(CRYPTO_KEY, "enc-001")
        )
        assert enc1 is not None
        offset = compute_date_offset("enc-001")
        orig = date(2024, 1, 15)
        expected_date = (orig + timedelta(days=offset)).isoformat()
        assert enc1["period"]["start"].startswith(expected_date), (
            f"Expected start date {expected_date}, "
            f"got {enc1['period']['start'][:10]}"
        )

    def test_observation_datetime_shifted(self, out_resources):
        obs1 = find_resource(
            out_resources, "Observation", compute_hash(CRYPTO_KEY, "obs-001")
        )
        assert obs1 is not None
        assert obs1.get("effectiveDateTime", "") != "2024-01-15T10:15:00Z"

    def test_elderly_birthdate_redacted(self, out_resources):
        """Patient born 1932-11-08 is >89 years old: birthDate must be redacted."""
        pat3 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-003")
        )
        assert pat3 is not None
        assert "birthDate" not in pat3 or pat3.get("birthDate") is None, (
            f"Elderly patient birthDate should be redacted, "
            f"got: {pat3.get('birthDate')}"
        )

    def test_elderly_other_dates_still_shifted(self, out_resources):
        enc3 = find_resource(
            out_resources, "Encounter", compute_hash(CRYPTO_KEY, "enc-003")
        )
        assert enc3 is not None
        assert enc3["period"]["start"][:10] != "2024-03-05"

    def test_claim_dates_shifted(self, out_resources):
        claim = find_resource(
            out_resources, "Claim", compute_hash(CRYPTO_KEY, "claim-001")
        )
        assert claim is not None
        offset = compute_date_offset("claim-001")
        orig_created = date(2024, 1, 20)
        expected_created = (orig_created + timedelta(days=offset)).isoformat()
        assert claim["created"] == expected_created
        orig_serviced = date(2024, 1, 15)
        expected_serviced = (orig_serviced + timedelta(days=offset)).isoformat()
        assert claim["item"][0]["servicedDate"] == expected_serviced

    def test_coverage_period_shifted(self, out_resources):
        cov = find_resource(
            out_resources, "Coverage", compute_hash(CRYPTO_KEY, "cov-001")
        )
        assert cov is not None
        assert cov["period"]["start"] != "2023-01-01"
        assert cov["period"]["end"] != "2024-12-31"


# ── Postal Code Tests ─────────────────────────────────────────────────────


class TestPostalCodes:
    def test_normal_zip_generalized(self, out_resources):
        """98004 (prefix 980, not restricted) -> 98000."""
        pat1 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-001")
        )
        assert pat1 is not None
        addrs = pat1.get("address", [])
        assert len(addrs) > 0
        assert addrs[0].get("postalCode") == "98000"

    def test_restricted_zip_zeroed(self, out_resources):
        """05901 (prefix 059, restricted) -> 00000."""
        pat3 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-003")
        )
        assert pat3 is not None
        addrs = pat3.get("address", [])
        assert len(addrs) > 0
        assert addrs[0].get("postalCode") == "00000"

    def test_state_preserved(self, out_resources):
        pat1 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-001")
        )
        assert pat1 is not None
        assert pat1["address"][0].get("state") == "WA"

    def test_country_preserved(self, out_resources):
        pat1 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-001")
        )
        assert pat1 is not None
        assert pat1["address"][0].get("country") == "US"

    def test_city_redacted(self, out_resources):
        pat1 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-001")
        )
        assert pat1 is not None
        addr = pat1["address"][0]
        assert "city" not in addr or addr.get("city") is None

    def test_street_redacted(self, out_resources):
        pat1 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-001")
        )
        assert pat1 is not None
        addr = pat1["address"][0]
        assert "line" not in addr or addr.get("line") in (None, [])

    def test_org_address_processed(self, out_resources):
        org1 = find_resource(
            out_resources, "Organization", compute_hash(CRYPTO_KEY, "org-001")
        )
        assert org1 is not None
        addrs = org1.get("address", [])
        assert len(addrs) > 0
        assert addrs[0].get("postalCode") == "98000"
        assert "line" not in addrs[0] or addrs[0].get("line") in (None, [])


# ── Security Labels Tests ─────────────────────────────────────────────────


class TestSecurityLabels:
    def test_each_resource_has_labels(self, out_resources):
        for r in out_resources:
            assert "meta" in r, (
                f"No meta in {r['resourceType']}/{r['id'][:8]}..."
            )
            assert "security" in r["meta"], (
                f"No security labels in {r['resourceType']}/{r['id'][:8]}..."
            )
            codes = {s["code"] for s in r["meta"]["security"]}
            assert "REDACTED" in codes, (
                f"REDACTED label missing in "
                f"{r['resourceType']}/{r['id'][:8]}..."
            )
            assert "CRYPTOHASH" in codes, (
                f"CRYPTOHASH label missing in "
                f"{r['resourceType']}/{r['id'][:8]}..."
            )


# ── Preserved Fields Tests ────────────────────────────────────────────────


class TestPreservedFields:
    def test_gender_preserved(self, out_resources):
        pat1 = find_resource(
            out_resources, "Patient", compute_hash(CRYPTO_KEY, "pat-001")
        )
        assert pat1 is not None
        assert pat1.get("gender") == "male"

    def test_observation_value_preserved(self, out_resources):
        obs1 = find_resource(
            out_resources, "Observation", compute_hash(CRYPTO_KEY, "obs-001")
        )
        assert obs1 is not None
        assert obs1.get("valueQuantity", {}).get("value") == 5.5

    def test_claim_amount_preserved(self, out_resources):
        claim = find_resource(
            out_resources, "Claim", compute_hash(CRYPTO_KEY, "claim-001")
        )
        assert claim is not None
        assert claim["item"][0]["unitPrice"]["value"] == 150.00

    def test_org_name_preserved(self, out_resources):
        org1 = find_resource(
            out_resources, "Organization", compute_hash(CRYPTO_KEY, "org-001")
        )
        assert org1 is not None
        assert org1.get("name") == "Bellevue General Hospital"

    def test_clinical_text_preserved(self, out_resources):
        cond = find_resource(
            out_resources, "Condition", compute_hash(CRYPTO_KEY, "cond-001")
        )
        assert cond is not None
        assert cond.get("code", {}).get("text") == "Type 2 Diabetes"

    def test_medication_text_preserved(self, out_resources):
        med = find_resource(
            out_resources,
            "MedicationRequest",
            compute_hash(CRYPTO_KEY, "med-001"),
        )
        assert med is not None
        assert (
            med.get("medicationCodeableConcept", {}).get("text")
            == "Metformin 500mg tablet"
        )

    def test_encounter_status_preserved(self, out_resources):
        enc1 = find_resource(
            out_resources, "Encounter", compute_hash(CRYPTO_KEY, "enc-001")
        )
        assert enc1 is not None
        assert enc1.get("status") == "finished"

    def test_bp_components_preserved(self, out_resources):
        obs2 = find_resource(
            out_resources, "Observation", compute_hash(CRYPTO_KEY, "obs-002")
        )
        assert obs2 is not None
        assert len(obs2.get("component", [])) == 2
        systolic = obs2["component"][0]["valueQuantity"]["value"]
        diastolic = obs2["component"][1]["valueQuantity"]["value"]
        assert systolic == 120
        assert diastolic == 80
