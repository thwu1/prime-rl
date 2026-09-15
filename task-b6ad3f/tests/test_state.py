
import json
import os
import glob
import subprocess
import pytest

OUTPUT_DIR = "/app/output"
RESPONSE_BUNDLE_PATH = os.path.join(OUTPUT_DIR, "response_bundle.json")
OUTPUT_STATE_DIR = os.path.join(OUTPUT_DIR, "server_state")
REPORT_PATH = "/app/conformance_report.json"


def find_all_values(obj, key_name):
    """Recursively find all values for a given key name in nested dicts/lists."""
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key_name:
                results.append(v)
            results.extend(find_all_values(v, key_name))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(find_all_values(item, key_name))
    return results


def find_all_references(obj):
    """Find all FHIR reference string values in a resource."""
    return find_all_values(obj, "reference")


# ---- Fixtures ----

@pytest.fixture(scope="session")
def response_bundle():
    assert os.path.exists(RESPONSE_BUNDLE_PATH), (
        f"Response bundle not found at {RESPONSE_BUNDLE_PATH}"
    )
    with open(RESPONSE_BUNDLE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def output_state():
    """Load all FHIR resources from the output server state directory."""
    assert os.path.isdir(OUTPUT_STATE_DIR), (
        f"Output state directory not found at {OUTPUT_STATE_DIR}"
    )
    resources = {}
    for filepath in glob.glob(os.path.join(OUTPUT_STATE_DIR, "*.json")):
        with open(filepath) as f:
            r = json.load(f)
            key = f"{r['resourceType']}/{r['id']}"
            resources[key] = r
    return resources


@pytest.fixture(scope="session")
def conformance_report():
    assert os.path.exists(REPORT_PATH), (
        f"Conformance report not found at {REPORT_PATH}"
    )
    with open(REPORT_PATH) as f:
        return json.load(f)


# ===========================================================================
# Conformance Report Tests — Structure
# ===========================================================================

class TestConformanceReportStructure:
    def test_report_has_all_processors(self, conformance_report):
        assert "processor_a" in conformance_report
        assert "processor_b" in conformance_report
        assert "processor_c" in conformance_report

    def test_processor_a_has_violations_list(self, conformance_report):
        assert isinstance(conformance_report["processor_a"]["violations"], list)

    def test_processor_b_has_violations_list(self, conformance_report):
        assert isinstance(conformance_report["processor_b"]["violations"], list)

    def test_processor_c_has_violations_list(self, conformance_report):
        assert isinstance(conformance_report["processor_c"]["violations"], list)

    def test_violation_entries_have_required_fields(self, conformance_report):
        for proc_key in ("processor_a", "processor_b", "processor_c"):
            for v in conformance_report[proc_key]["violations"]:
                assert "category" in v, f"Missing category in {proc_key} violation"
                assert "description" in v, f"Missing description in {proc_key} violation"
                assert "severity" in v, f"Missing severity in {proc_key} violation"
                assert v["severity"] in ("error", "warning"), (
                    f"Invalid severity '{v['severity']}' in {proc_key}"
                )

    def test_violation_descriptions_are_substantive(self, conformance_report):
        for proc_key in ("processor_a", "processor_b", "processor_c"):
            for v in conformance_report[proc_key]["violations"]:
                assert len(v["description"]) >= 30, (
                    f"Violation description too short in {proc_key}: '{v['description']}'"
                )

    def test_conformance_scores_are_valid(self, conformance_report):
        for proc_key in ("processor_a", "processor_b", "processor_c"):
            score = conformance_report[proc_key]["conformance_score"]
            assert isinstance(score, (int, float)), f"Score must be numeric in {proc_key}"
            assert 0 <= score <= 100, f"Score out of range in {proc_key}: {score}"

    def test_comparative_analysis_structure(self, conformance_report):
        ca = conformance_report.get("comparative_analysis", {})
        assert "superior_implementation" in ca
        assert "architectural_strengths" in ca
        assert "recommendation" in ca
        assert isinstance(ca["recommendation"], str)
        assert len(ca["recommendation"]) >= 30


# ===========================================================================
# Conformance Report Tests — Accuracy
# ===========================================================================

class TestConformanceReportAccuracy:
    def test_processor_a_minimum_violation_count(self, conformance_report):
        violations = conformance_report["processor_a"]["violations"]
        assert len(violations) >= 3, (
            f"processor_a should have at least 3 conformance violations, found {len(violations)}"
        )

    def test_processor_b_has_violations(self, conformance_report):
        violations = conformance_report["processor_b"]["violations"]
        assert len(violations) >= 2, (
            "processor_b should have at least 2 conformance violations"
        )

    def test_processor_c_has_violations(self, conformance_report):
        violations = conformance_report["processor_c"]["violations"]
        assert len(violations) >= 1, (
            "processor_c should have at least 1 conformance violation"
        )

    def test_processor_a_violation_categories(self, conformance_report):
        categories = {v["category"] for v in conformance_report["processor_a"]["violations"]}
        assert "reference_resolution" in categories, (
            "processor_a violations should include reference_resolution"
        )
        assert "status_codes" in categories, (
            "processor_a violations should include status_codes"
        )
        assert "versioning" in categories, (
            "processor_a violations should include versioning"
        )

    def test_processor_b_has_reference_resolution_violation(self, conformance_report):
        categories = {v["category"] for v in conformance_report["processor_b"]["violations"]}
        assert "reference_resolution" in categories, (
            "processor_b violations should include reference_resolution"
        )

    def test_processor_c_has_reference_or_conditional_violation(self, conformance_report):
        """Processor C should have violations related to conditional create mapping or conditional references."""
        categories = {v["category"] for v in conformance_report["processor_c"]["violations"]}
        has_relevant = (
            "reference_resolution" in categories
            or "conditional_create" in categories
            or "conditional_reference" in categories
        )
        assert has_relevant, (
            f"processor_c should have reference_resolution, conditional_create, or "
            f"conditional_reference violation, found categories: {categories}"
        )

    def test_processor_c_scores_highest(self, conformance_report):
        a_score = conformance_report["processor_a"]["conformance_score"]
        b_score = conformance_report["processor_b"]["conformance_score"]
        c_score = conformance_report["processor_c"]["conformance_score"]
        assert c_score > a_score, (
            f"processor_c ({c_score}) should score higher than processor_a ({a_score})"
        )
        assert c_score > b_score, (
            f"processor_c ({c_score}) should score higher than processor_b ({b_score})"
        )

    def test_superior_implementation_is_c(self, conformance_report):
        assert conformance_report["comparative_analysis"]["superior_implementation"] == "processor_c"

    def test_all_have_architectural_strengths(self, conformance_report):
        strengths = conformance_report["comparative_analysis"]["architectural_strengths"]
        for proc in ("processor_a", "processor_b", "processor_c"):
            assert len(strengths.get(proc, [])) >= 1, (
                f"{proc} should have at least one architectural strength identified"
            )


# ===========================================================================
# Reference Processor Output: Response Bundle Structure
# ===========================================================================

class TestResponseBundleStructure:
    def test_bundle_resource_type(self, response_bundle):
        assert response_bundle["resourceType"] == "Bundle"

    def test_bundle_type_is_transaction_response(self, response_bundle):
        assert response_bundle["type"] == "transaction-response"

    def test_entry_count_matches_request(self, response_bundle):
        assert len(response_bundle["entry"]) == 11

    def test_delete_entry_status(self, response_bundle):
        """DELETE operations must return 204 No Content."""
        entry = response_bundle["entry"][0]
        status = entry["response"]["status"]
        assert "204" in status, (
            f"DELETE response should be 204, got {status}"
        )

    def test_post_entries_status_201(self, response_bundle):
        """Normal POST entries should return 201 Created."""
        post_indices = [1, 2, 3, 5, 6, 7, 8, 10]
        for idx in post_indices:
            entry = response_bundle["entry"][idx]
            assert "201" in entry["response"]["status"], (
                f"Entry {idx} should have 201 status, got {entry['response']['status']}"
            )

    def test_put_entry_status_200(self, response_bundle):
        entry = response_bundle["entry"][4]
        assert "200" in entry["response"]["status"]

    def test_conditional_create_match_status_200(self, response_bundle):
        """Conditional create with matching existing resource should return 200 OK."""
        entry = response_bundle["entry"][9]
        status = entry["response"]["status"]
        assert "200" in status, (
            f"Conditional create with match (entry 9) should return 200, got {status}"
        )

    def test_post_entries_have_location(self, response_bundle):
        post_indices = [1, 2, 3, 5, 6, 7, 8, 10]
        for idx in post_indices:
            entry = response_bundle["entry"][idx]
            assert "location" in entry["response"], (
                f"Entry {idx} POST response should have location header"
            )


# ===========================================================================
# Reference Processor Output: Server State Mutations
# ===========================================================================

class TestServerStateMutations:
    def test_obs001_is_deleted(self, output_state):
        assert "Observation/obs-001" not in output_state

    def test_original_patient_001_preserved(self, output_state):
        assert "Patient/pat-001" in output_state

    def test_practitioner_preserved(self, output_state):
        assert "Practitioner/pract-001" in output_state

    def test_original_encounter_preserved(self, output_state):
        assert "Encounter/enc-001" in output_state

    def test_original_condition_preserved(self, output_state):
        assert "Condition/cond-001" in output_state

    def test_pat002_updated_phone(self, output_state):
        pat = output_state["Patient/pat-002"]
        telecoms = pat.get("telecom", [])
        phone_values = [
            t.get("value") for t in telecoms if t.get("system") == "phone"
        ]
        assert "555-9999" in phone_values

    def test_pat002_has_email(self, output_state):
        pat = output_state["Patient/pat-002"]
        telecoms = pat.get("telecom", [])
        systems = [t.get("system") for t in telecoms]
        assert "email" in systems

    def test_pat002_version_incremented(self, output_state):
        pat = output_state["Patient/pat-002"]
        version = int(pat.get("meta", {}).get("versionId", "0"))
        assert version >= 2, (
            f"pat-002 versionId should be >= 2 after update, got {version}"
        )


# ===========================================================================
# Reference Processor Output: New Resources Created
# ===========================================================================

class TestNewResources:
    def test_new_patient_brown_exists(self, output_state):
        browns = [
            r for r in output_state.values()
            if r.get("resourceType") == "Patient"
            and any(n.get("family") == "Brown" for n in r.get("name", []))
        ]
        assert len(browns) == 1
        brown = browns[0]
        assert brown.get("gender") == "male"
        assert brown.get("birthDate") == "1978-11-03"

    def test_new_encounter_exists(self, output_state):
        encounters = [
            r for r in output_state.values()
            if r.get("resourceType") == "Encounter"
            and r.get("status") == "in-progress"
        ]
        assert len(encounters) == 1

    def test_body_weight_observation_exists(self, output_state):
        obs = [
            r for r in output_state.values()
            if r.get("resourceType") == "Observation"
            and any(
                c.get("code") == "29463-7"
                for c in r.get("code", {}).get("coding", [])
            )
        ]
        assert len(obs) == 1

    def test_glucose_observation_exists(self, output_state):
        obs = [
            r for r in output_state.values()
            if r.get("resourceType") == "Observation"
            and any(
                c.get("code") == "2339-0"
                for c in r.get("code", {}).get("coding", [])
            )
        ]
        assert len(obs) == 1

    def test_hba1c_observation_exists(self, output_state):
        obs = [
            r for r in output_state.values()
            if r.get("resourceType") == "Observation"
            and any(
                c.get("code") == "4548-4"
                for c in r.get("code", {}).get("coding", [])
            )
        ]
        assert len(obs) == 1

    def test_medication_request_exists(self, output_state):
        medrqs = [
            r for r in output_state.values()
            if r.get("resourceType") == "MedicationRequest"
        ]
        assert len(medrqs) >= 1

    def test_diabetes_condition_exists(self, output_state):
        conds = [
            r for r in output_state.values()
            if r.get("resourceType") == "Condition"
            and any(
                c.get("code") == "44054006"
                for c in r.get("code", {}).get("coding", [])
            )
        ]
        assert len(conds) == 1

    def test_service_request_exists(self, output_state):
        srs = [
            r for r in output_state.values()
            if r.get("resourceType") == "ServiceRequest"
        ]
        assert len(srs) == 1

    def test_new_resources_have_meta(self, output_state):
        """All newly created or updated resources must have meta.versionId and meta.lastUpdated."""
        preserved_keys = {
            "Patient/pat-001", "Practitioner/pract-001",
            "Encounter/enc-001", "Condition/cond-001",
            "AllergyIntolerance/allergy-001",
        }
        for key, r in output_state.items():
            if key not in preserved_keys:
                meta = r.get("meta", {})
                assert "versionId" in meta, f"{key} missing meta.versionId"
                assert "lastUpdated" in meta, f"{key} missing meta.lastUpdated"


# ===========================================================================
# Reference Processor Output: Conditional Create
# ===========================================================================

class TestConditionalCreate:
    def test_no_duplicate_allergy_intolerance(self, output_state):
        """ifNoneExist with matching resource should NOT create a duplicate."""
        allergies = [
            r for r in output_state.values()
            if r.get("resourceType") == "AllergyIntolerance"
        ]
        assert len(allergies) == 1, (
            f"Expected exactly 1 AllergyIntolerance (existing should not be duplicated), "
            f"found {len(allergies)}"
        )

    def test_existing_allergy_preserved(self, output_state):
        """The pre-existing AllergyIntolerance/allergy-001 should be preserved unchanged."""
        assert "AllergyIntolerance/allergy-001" in output_state
        allergy = output_state["AllergyIntolerance/allergy-001"]
        codings = allergy.get("code", {}).get("coding", [])
        assert any(c.get("code") == "91936005" for c in codings)


# ===========================================================================
# Reference Processor Output: Conditional Reference Resolution
# ===========================================================================

class TestConditionalReferenceResolution:
    def test_service_request_subject_resolved(self, output_state):
        """Conditional reference Patient?identifier=... should resolve to Patient/pat-001."""
        srs = [
            r for r in output_state.values()
            if r.get("resourceType") == "ServiceRequest"
        ]
        assert len(srs) == 1
        sr = srs[0]
        subj = sr.get("subject", {}).get("reference", "")
        assert subj == "Patient/pat-001", (
            f"ServiceRequest subject should resolve to Patient/pat-001, got '{subj}'"
        )

    def test_service_request_supporting_info_resolved(self, output_state):
        """supportingInfo urn:uuid:new-allergy-1 should resolve to existing AllergyIntolerance/allergy-001
        via the conditional create mapping chain."""
        srs = [
            r for r in output_state.values()
            if r.get("resourceType") == "ServiceRequest"
        ]
        sr = srs[0]
        supporting = sr.get("supportingInfo", [])
        assert len(supporting) >= 1, "ServiceRequest should have supportingInfo"
        ref = supporting[0].get("reference", "")
        assert ref == "AllergyIntolerance/allergy-001", (
            f"supportingInfo should resolve to AllergyIntolerance/allergy-001 "
            f"(via conditional create urn:uuid mapping), got '{ref}'"
        )

    def test_service_request_no_conditional_refs_remain(self, output_state):
        """No conditional references (Type?search=value) should remain in ServiceRequest."""
        srs = [
            r for r in output_state.values()
            if r.get("resourceType") == "ServiceRequest"
        ]
        sr = srs[0]
        refs = find_all_references(sr)
        for ref in refs:
            assert "?" not in ref or ref.startswith("http"), (
                f"Unresolved conditional reference in ServiceRequest: '{ref}'"
            )


# ===========================================================================
# Reference Processor Output: Reference Resolution
# ===========================================================================

class TestReferenceResolution:
    def test_no_urn_uuid_in_output_state(self, output_state):
        """No urn:uuid: references should remain in any output resource."""
        for key, resource in output_state.items():
            refs = find_all_references(resource)
            for ref in refs:
                assert not ref.startswith("urn:uuid:"), (
                    f"Unresolved reference '{ref}' found in {key}"
                )

    def test_no_urn_uuid_in_any_field(self, output_state):
        """Check for urn:uuid: strings in ANY string value."""
        def check_strings(obj, path=""):
            if isinstance(obj, str):
                assert not obj.startswith("urn:uuid:"), (
                    f"Unresolved urn:uuid at {path}: {obj}"
                )
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    check_strings(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    check_strings(item, f"{path}[{i}]")

        for key, resource in output_state.items():
            check_strings(resource, key)

    def test_new_encounter_subject_points_to_brown(self, output_state):
        encounters = [
            r for r in output_state.values()
            if r.get("resourceType") == "Encounter"
            and r.get("status") == "in-progress"
        ]
        enc = encounters[0]
        subject_ref = enc.get("subject", {}).get("reference", "")
        assert subject_ref.startswith("Patient/")
        assert subject_ref in output_state
        patient = output_state[subject_ref]
        assert any(n.get("family") == "Brown" for n in patient.get("name", []))

    def test_body_weight_obs_references(self, output_state):
        obs = [
            r for r in output_state.values()
            if r.get("resourceType") == "Observation"
            and any(
                c.get("code") == "29463-7"
                for c in r.get("code", {}).get("coding", [])
            )
        ][0]
        subj = obs.get("subject", {}).get("reference", "")
        assert subj in output_state
        assert any(
            n.get("family") == "Brown"
            for n in output_state[subj].get("name", [])
        )
        enc_ref = obs.get("encounter", {}).get("reference", "")
        assert enc_ref in output_state
        assert output_state[enc_ref].get("status") == "in-progress"

    def test_extension_valueReference_resolved(self, output_state):
        """The valueReference inside the extension on the diabetes Condition must be resolved."""
        conds = [
            r for r in output_state.values()
            if r.get("resourceType") == "Condition"
            and any(
                c.get("code") == "44054006"
                for c in r.get("code", {}).get("coding", [])
            )
        ]
        cond = conds[0]
        exts = cond.get("extension", [])
        diag_ext = [
            e for e in exts
            if e.get("url") == "http://example.org/fhir/StructureDefinition/diagnosing-encounter"
        ]
        assert len(diag_ext) == 1
        ext_ref = diag_ext[0].get("valueReference", {}).get("reference", "")
        assert ext_ref.startswith("Encounter/"), (
            f"Extension reference not resolved: {ext_ref}"
        )
        assert ext_ref in output_state
        assert output_state[ext_ref].get("status") == "in-progress"

    def test_glucose_hasMember_points_to_hba1c(self, output_state):
        glucose = [
            r for r in output_state.values()
            if r.get("resourceType") == "Observation"
            and any(
                c.get("code") == "2339-0"
                for c in r.get("code", {}).get("coding", [])
            )
        ][0]
        hba1c = [
            r for r in output_state.values()
            if r.get("resourceType") == "Observation"
            and any(
                c.get("code") == "4548-4"
                for c in r.get("code", {}).get("coding", [])
            )
        ][0]

        members = glucose.get("hasMember", [])
        assert len(members) >= 1
        member_ref = members[0].get("reference", "")
        expected = f"Observation/{hba1c['id']}"
        assert member_ref == expected, (
            f"glucose.hasMember should point to HbA1c: expected {expected}, got {member_ref}"
        )

    def test_hba1c_derivedFrom_points_to_glucose(self, output_state):
        glucose = [
            r for r in output_state.values()
            if r.get("resourceType") == "Observation"
            and any(
                c.get("code") == "2339-0"
                for c in r.get("code", {}).get("coding", [])
            )
        ][0]
        hba1c = [
            r for r in output_state.values()
            if r.get("resourceType") == "Observation"
            and any(
                c.get("code") == "4548-4"
                for c in r.get("code", {}).get("coding", [])
            )
        ][0]

        derived = hba1c.get("derivedFrom", [])
        assert len(derived) >= 1
        derived_ref = derived[0].get("reference", "")
        expected = f"Observation/{glucose['id']}"
        assert derived_ref == expected, (
            f"hba1c.derivedFrom should point to glucose: expected {expected}, got {derived_ref}"
        )

    def test_all_internal_references_valid(self, output_state):
        """Every internal reference (ResourceType/id) must point to an existing resource."""
        for key, resource in output_state.items():
            refs = find_all_references(resource)
            for ref in refs:
                if "/" in ref and not ref.startswith("http"):
                    assert ref in output_state, (
                        f"Broken reference '{ref}' in resource {key}"
                    )

    def test_medrq_subject_is_brown(self, output_state):
        medrqs = [
            r for r in output_state.values()
            if r.get("resourceType") == "MedicationRequest"
        ]
        assert len(medrqs) >= 1
        medrq = medrqs[0]
        subj = medrq.get("subject", {}).get("reference", "")
        assert subj in output_state
        assert any(
            n.get("family") == "Brown"
            for n in output_state[subj].get("name", [])
        )

    def test_medrq_requester_is_practitioner(self, output_state):
        medrqs = [
            r for r in output_state.values()
            if r.get("resourceType") == "MedicationRequest"
        ]
        medrq = medrqs[0]
        req = medrq.get("requester", {}).get("reference", "")
        assert req == "Practitioner/pract-001"

    def test_medrq_encounter_is_new_encounter(self, output_state):
        """MedicationRequest encounter reference should point to the new in-progress encounter."""
        medrqs = [
            r for r in output_state.values()
            if r.get("resourceType") == "MedicationRequest"
        ]
        medrq = medrqs[0]
        enc_ref = medrq.get("encounter", {}).get("reference", "")
        assert enc_ref in output_state, f"MedicationRequest encounter ref broken: {enc_ref}"
        assert output_state[enc_ref].get("status") == "in-progress"


# ===========================================================================
# Validation Pipeline Tests — jq-based shell scripts
# ===========================================================================

class TestValidationPipeline:
    SCRIPTS = [
        "/app/validation/check_references.sh",
        "/app/validation/check_status_codes.sh",
        "/app/validation/check_versioning.sh",
        "/app/validation/diff_processors.sh",
    ]

    def test_all_scripts_exist_and_executable(self):
        for script in self.SCRIPTS:
            assert os.path.isfile(script), f"Missing validation script: {script}"
            assert os.access(script, os.X_OK), f"Script not executable: {script}"

    def test_check_references_detects_violations_in_a(self):
        """Processor A has unresolved urn:uuid references due to its implementation approach."""
        result = subprocess.run(
            ["/app/validation/check_references.sh", "/app/output_a"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode != 0, (
            f"check_references should detect violations in output_a, "
            f"but exited 0. stdout: {result.stdout[:200]}"
        )
        output = json.loads(result.stdout)
        assert output["status"] == "fail"
        assert output["issue_count"] > 0

    def test_check_references_detects_violations_in_b(self):
        """Processor B has unresolved references from its implementation approach."""
        result = subprocess.run(
            ["/app/validation/check_references.sh", "/app/output_b"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode != 0
        output = json.loads(result.stdout)
        assert output["status"] == "fail"
        assert output["issue_count"] > 0

    def test_check_references_passes_for_reference(self):
        """The correct reference processor should have no unresolved references."""
        result = subprocess.run(
            ["/app/validation/check_references.sh", "/app/output"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"check_references should pass for reference output, "
            f"but exited {result.returncode}. stdout: {result.stdout[:500]}"
        )
        output = json.loads(result.stdout)
        assert output["status"] == "pass"

    def test_check_status_codes_detects_violations_in_a(self):
        """Processor A returns wrong status code for DELETE operations."""
        result = subprocess.run(
            ["/app/validation/check_status_codes.sh", "/app/output_a"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode != 0
        output = json.loads(result.stdout)
        assert output["status"] == "fail"
        methods = [issue.get("method") for issue in output.get("issues", [])]
        assert "DELETE" in methods, (
            f"Should detect DELETE status code violation, found methods: {methods}"
        )

    def test_check_status_codes_passes_for_reference(self):
        """The reference processor should pass all status code checks."""
        result = subprocess.run(
            ["/app/validation/check_status_codes.sh", "/app/output"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"check_status_codes should pass for reference output, "
            f"but exited {result.returncode}. stdout: {result.stdout[:500]}"
        )

    def test_check_versioning_detects_violations_in_a(self):
        """Processor A has versioning violations for PUT operations."""
        result = subprocess.run(
            ["/app/validation/check_versioning.sh", "/app/output_a", "/app/data/server_state"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode != 0
        output = json.loads(result.stdout)
        assert output["issue_count"] > 0

    def test_check_versioning_detects_violations_in_b(self):
        """Processor B has versioning violations for PUT operations."""
        result = subprocess.run(
            ["/app/validation/check_versioning.sh", "/app/output_b", "/app/data/server_state"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode != 0
        output = json.loads(result.stdout)
        assert output["issue_count"] > 0

    def test_check_versioning_passes_for_reference(self):
        """The reference processor should have correct versioning."""
        result = subprocess.run(
            ["/app/validation/check_versioning.sh", "/app/output", "/app/data/server_state"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"check_versioning should pass for reference output, "
            f"but exited {result.returncode}. stdout: {result.stdout[:500]}"
        )

    def test_diff_processors_produces_valid_json(self):
        """diff_processors.sh must output valid JSON with all three processor keys."""
        result = subprocess.run(
            ["/app/validation/diff_processors.sh"],
            capture_output=True, text=True, timeout=60
        )
        output = json.loads(result.stdout)
        assert "processor_a" in output
        assert "processor_b" in output
        assert "processor_c" in output

    def test_diff_processors_shows_unresolved_references(self):
        """At least one processor should have unresolved urn:uuid references."""
        result = subprocess.run(
            ["/app/validation/diff_processors.sh"],
            capture_output=True, text=True, timeout=60
        )
        output = json.loads(result.stdout)
        urns = [
            output[p]["unresolved_urn_uuids"]
            for p in ("processor_a", "processor_b", "processor_c")
        ]
        assert any(u > 0 for u in urns), (
            f"At least one processor should have unresolved urn:uuid refs, got: {urns}"
        )
