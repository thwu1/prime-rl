
import pytest
import json
import subprocess
import os
import tempfile

ENGINE = "/app/fhir_engine.py"
BUNDLES_DIR = "/app/bundles"
SERVER_STATE_DIR = "/app/server_state"


def run_engine(bundle_name, server_state_dir=SERVER_STATE_DIR):
    """Run the FHIR transaction engine and return the parsed output."""
    input_file = os.path.join(BUNDLES_DIR, bundle_name)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        output_file = f.name

    try:
        result = subprocess.run(
            ["python3", ENGINE, input_file, server_state_dir, output_file],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Engine exited with code {result.returncode}: {result.stderr}"
        )
        with open(output_file) as f:
            return json.load(f)
    finally:
        if os.path.exists(output_file):
            os.unlink(output_file)


# ---------------------------------------------------------------------------
# 1. Basic transaction: single resource create
# ---------------------------------------------------------------------------
class TestBasicTransaction:
    def test_response_is_transaction_response_bundle(self):
        response = run_engine("basic_transaction.json")
        assert response["resourceType"] == "Bundle"
        assert response["type"] == "transaction-response"

    def test_single_entry_created(self):
        response = run_engine("basic_transaction.json")
        assert len(response["entry"]) == 1
        entry = response["entry"][0]
        assert "201" in entry["response"]["status"]

    def test_location_contains_resource_type(self):
        response = run_engine("basic_transaction.json")
        loc = response["entry"][0]["response"]["location"]
        assert loc.startswith("Observation/")

    def test_etag_weak_format(self):
        """FHIR R4 requires weak ETag validators: W/\"<version>\"."""
        response = run_engine("basic_transaction.json")
        etag = response["entry"][0]["response"]["etag"]
        assert etag.startswith('W/"') and etag.endswith('"'), (
            f"ETag '{etag}' must use weak validator format W/\"...\""
        )

    def test_created_resource_has_id(self):
        response = run_engine("basic_transaction.json")
        resource = response["entry"][0]["resource"]
        assert "id" in resource
        assert resource["resourceType"] == "Observation"


# ---------------------------------------------------------------------------
# 2. Reference resolution: urn:uuid references across entries
# ---------------------------------------------------------------------------
class TestReferenceResolution:
    def test_both_entries_created(self):
        response = run_engine("reference_resolution.json")
        assert len(response["entry"]) == 2
        for entry in response["entry"]:
            assert "201" in entry["response"]["status"]

    def test_observation_subject_resolved(self):
        response = run_engine("reference_resolution.json")
        obs = response["entry"][1]["resource"]
        ref = obs["subject"]["reference"]
        assert not ref.startswith("urn:uuid:"), (
            f"urn:uuid reference was not resolved: {ref}"
        )
        assert ref.startswith("Patient/")

    def test_resolved_reference_matches_created_patient(self):
        response = run_engine("reference_resolution.json")
        patient_loc = response["entry"][0]["response"]["location"]
        patient_ref = patient_loc.split("/_history")[0]

        obs = response["entry"][1]["resource"]
        assert obs["subject"]["reference"] == patient_ref


# ---------------------------------------------------------------------------
# 3. Array-based reference resolution
# ---------------------------------------------------------------------------
class TestArrayReferences:
    """References inside arrays (e.g. performer) must also be resolved."""

    def test_all_entries_created(self):
        response = run_engine("array_references.json")
        assert len(response["entry"]) == 3
        for entry in response["entry"]:
            assert "201" in entry["response"]["status"]

    def test_performer_reference_resolved(self):
        response = run_engine("array_references.json")
        obs = response["entry"][2]["resource"]
        performer_ref = obs["performer"][0]["reference"]
        assert not performer_ref.startswith("urn:uuid:"), (
            f"performer reference was not resolved: {performer_ref}"
        )
        assert performer_ref.startswith("Practitioner/")

    def test_performer_matches_created_practitioner(self):
        response = run_engine("array_references.json")
        pract_loc = response["entry"][1]["response"]["location"]
        pract_ref = pract_loc.split("/_history")[0]
        obs = response["entry"][2]["resource"]
        assert obs["performer"][0]["reference"] == pract_ref

    def test_subject_still_resolved(self):
        response = run_engine("array_references.json")
        obs = response["entry"][2]["resource"]
        subject_ref = obs["subject"]["reference"]
        assert subject_ref.startswith("Patient/")


# ---------------------------------------------------------------------------
# 4. Processing order: DELETE -> POST -> PUT -> GET
# ---------------------------------------------------------------------------
class TestProcessingOrder:
    """Input order: GET(0), PUT(1), POST(2), DELETE(3).
    Processing must follow FHIR order: DELETE -> POST -> PUT -> GET.
    Responses are returned in the *original* input order."""

    def test_response_has_four_entries(self):
        response = run_engine("processing_order.json")
        assert len(response["entry"]) == 4

    def test_get_returns_updated_patient(self):
        """GET (entry 0) must see the Patient as modified by the PUT (entry 1).
        This proves PUT was processed before GET."""
        response = run_engine("processing_order.json")
        get_entry = response["entry"][0]
        assert "200" in get_entry["response"]["status"]
        patient = get_entry["resource"]
        assert "Michael" in patient["name"][0]["given"], (
            "GET did not return the updated Patient — processing order may be wrong"
        )

    def test_delete_succeeds(self):
        response = run_engine("processing_order.json")
        del_entry = response["entry"][3]
        status = del_entry["response"]["status"]
        assert "204" in status or "200" in status

    def test_post_creates_condition(self):
        response = run_engine("processing_order.json")
        post_entry = response["entry"][2]
        assert "201" in post_entry["response"]["status"]
        assert post_entry["response"]["location"].startswith("Condition/")

    def test_put_updates_patient(self):
        response = run_engine("processing_order.json")
        put_entry = response["entry"][1]
        assert "200" in put_entry["response"]["status"]


# ---------------------------------------------------------------------------
# 5. Conditional operations: ifNoneExist and ifMatch
# ---------------------------------------------------------------------------
class TestConditionalOperations:
    def test_conditional_create_match_returns_200(self):
        """ifNoneExist matches existing patient-1 -> 200, no new resource."""
        response = run_engine("conditional_operations.json")
        assert response["resourceType"] == "Bundle"
        entry = response["entry"][0]
        assert "200" in entry["response"]["status"]

    def test_conditional_create_match_references_existing(self):
        response = run_engine("conditional_operations.json")
        loc = response["entry"][0]["response"]["location"]
        assert "patient-1" in loc

    def test_conditional_create_no_match_returns_201(self):
        """ifNoneExist does not match -> new resource created with 201."""
        response = run_engine("conditional_operations.json")
        entry = response["entry"][1]
        assert "201" in entry["response"]["status"]

    def test_versioned_update_succeeds(self):
        """PUT with ifMatch W/\"1\" on patient-1 (version 1) -> 200."""
        response = run_engine("conditional_operations.json")
        entry = response["entry"][2]
        assert "200" in entry["response"]["status"]

    def test_versioned_update_increments_version(self):
        response = run_engine("conditional_operations.json")
        entry = response["entry"][2]
        assert entry["response"]["etag"] == 'W/"2"'


# ---------------------------------------------------------------------------
# 6. Atomicity: error in one entry rolls back entire transaction
# ---------------------------------------------------------------------------
class TestAtomicity:
    def test_returns_operation_outcome(self):
        """A GET targeting a nonexistent resource fails the entire transaction."""
        response = run_engine("atomicity_failure.json")
        assert response["resourceType"] == "OperationOutcome"

    def test_error_severity(self):
        response = run_engine("atomicity_failure.json")
        assert response["issue"][0]["severity"] == "error"


# ---------------------------------------------------------------------------
# 7. Complex references: Patient -> Encounter -> Observations chain
# ---------------------------------------------------------------------------
class TestComplexReferences:
    def test_all_four_created(self):
        response = run_engine("complex_references.json")
        assert response["resourceType"] == "Bundle"
        assert len(response["entry"]) == 4
        for entry in response["entry"]:
            assert "201" in entry["response"]["status"]

    def test_encounter_references_created_patient(self):
        response = run_engine("complex_references.json")
        patient_ref = response["entry"][0]["response"]["location"].split("/_history")[0]
        encounter = response["entry"][1]["resource"]
        assert encounter["subject"]["reference"] == patient_ref

    def test_observations_reference_patient_and_encounter(self):
        response = run_engine("complex_references.json")
        patient_ref = response["entry"][0]["response"]["location"].split("/_history")[0]
        encounter_ref = response["entry"][1]["response"]["location"].split("/_history")[0]

        for idx in [2, 3]:
            obs = response["entry"][idx]["resource"]
            assert obs["subject"]["reference"] == patient_ref, (
                f"Observation entry {idx}: subject not resolved to created Patient"
            )
            assert obs["encounter"]["reference"] == encounter_ref, (
                f"Observation entry {idx}: encounter not resolved to created Encounter"
            )

    def test_no_unresolved_urn_uuids(self):
        response = run_engine("complex_references.json")
        serialized = json.dumps(response)
        assert "urn:uuid:" not in serialized, (
            "Unresolved urn:uuid references remain in the response"
        )


# ---------------------------------------------------------------------------
# 8. Version conflict: ifMatch with wrong version
# ---------------------------------------------------------------------------
class TestVersionConflict:
    def test_wrong_version_fails_transaction(self):
        """PUT with ifMatch W/\"999\" on patient-1 (version 1) must fail."""
        response = run_engine("version_conflict.json")
        assert response["resourceType"] == "OperationOutcome"

    def test_error_mentions_version_or_conflict(self):
        response = run_engine("version_conflict.json")
        diag = response["issue"][0].get("diagnostics", "").lower()
        assert "version" in diag or "conflict" in diag or "match" in diag


# ---------------------------------------------------------------------------
# 9. Conformance validator: FHIRPath-based output validation
# ---------------------------------------------------------------------------
class TestConformanceValidator:
    VALIDATOR = "/app/validate_output.py"

    def test_validator_script_exists(self):
        assert os.path.exists(self.VALIDATOR), (
            "/app/validate_output.py not found"
        )

    def test_validator_uses_fhirpath(self):
        """The validator must use a FHIRPath library for evaluation."""
        with open(self.VALIDATOR) as f:
            source = f.read()
        assert "fhirpath" in source.lower(), (
            "Validator must use a FHIRPath evaluation library (e.g. fhirpathpy)"
        )

    def test_accepts_valid_bundle(self):
        valid = {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": [
                {
                    "response": {
                        "status": "201 Created",
                        "location": "Patient/p1/_history/1",
                        "etag": 'W/"1"',
                    },
                    "resource": {
                        "resourceType": "Patient",
                        "id": "p1",
                    },
                }
            ],
        }
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            json.dump(valid, f)
            tmpfile = f.name
        try:
            result = subprocess.run(
                ["python3", self.VALIDATOR, tmpfile],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, (
                f"Validator rejected valid bundle: {result.stdout}{result.stderr}"
            )
        finally:
            os.unlink(tmpfile)

    def test_rejects_wrong_bundle_type(self):
        invalid = {
            "resourceType": "Bundle",
            "type": "searchset",
            "entry": [],
        }
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            json.dump(invalid, f)
            tmpfile = f.name
        try:
            result = subprocess.run(
                ["python3", self.VALIDATOR, tmpfile],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 1, (
                "Validator should reject non-transaction-response bundle"
            )
        finally:
            os.unlink(tmpfile)

    def test_rejects_bad_etag_format(self):
        invalid = {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": [
                {
                    "response": {
                        "status": "201 Created",
                        "etag": '"1"',
                    },
                }
            ],
        }
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            json.dump(invalid, f)
            tmpfile = f.name
        try:
            result = subprocess.run(
                ["python3", self.VALIDATOR, tmpfile],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 1, (
                "Validator should reject bundles with non-weak ETags"
            )
        finally:
            os.unlink(tmpfile)

    def test_rejects_unresolved_urn_uuid(self):
        invalid = {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": [
                {
                    "response": {"status": "201 Created", "etag": 'W/"1"'},
                    "resource": {
                        "resourceType": "Observation",
                        "id": "o1",
                        "subject": {
                            "reference": "urn:uuid:unresolved-ref"
                        },
                    },
                }
            ],
        }
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            json.dump(invalid, f)
            tmpfile = f.name
        try:
            result = subprocess.run(
                ["python3", self.VALIDATOR, tmpfile],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 1, (
                "Validator should reject bundles with unresolved urn:uuid references"
            )
        finally:
            os.unlink(tmpfile)
