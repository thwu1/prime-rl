
import subprocess
import json
import os
import tempfile
import pytest

VALIDATE_CMD = ["bash", "/app/validate.sh"]
PROFILE_ADT = "/app/profile/"
PROFILE_ACK = "/app/profile_ack/"
MESSAGES_ADT = "/app/messages"
MESSAGES_ACK = "/app/messages_ack"


def run_validator(profile_dir, msg_path):
    """Run the validator and return (exit_code, parsed_json_or_None)."""
    result = subprocess.run(
        VALIDATE_CMD + [profile_dir, msg_path],
        capture_output=True, text=True, timeout=60
    )
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        data = None
    return result.returncode, data


def run_adt(msg_file):
    return run_validator(PROFILE_ADT, os.path.join(MESSAGES_ADT, msg_file))


def run_ack(msg_file):
    return run_validator(PROFILE_ACK, os.path.join(MESSAGES_ACK, msg_file))


def has_error_with(data, category=None, path_contains=None):
    """Check if any error matches the given criteria."""
    for err in data.get("errors", []):
        cat_match = category is None or err.get("category") == category
        path_match = path_contains is None or path_contains in err.get("path", "")
        if cat_match and path_match:
            return True
    return False


# ── ADT Profile: Output Format ──────────────────────────────────────


class TestOutputFormat:
    """Validates that the validator produces well-formed JSON with correct schema."""

    def test_valid_message_json_keys(self):
        rc, data = run_adt("msg_valid.hl7")
        assert data is not None, "Validator must produce valid JSON on stdout"
        assert "valid" in data, "JSON must contain 'valid' key"
        assert "errors" in data, "JSON must contain 'errors' key"
        assert "warnings" in data, "JSON must contain 'warnings' key"
        assert isinstance(data["errors"], list), "'errors' must be a list"
        assert isinstance(data["warnings"], list), "'warnings' must be a list"

    def test_error_entry_schema(self):
        rc, data = run_adt("msg_missing_evn.hl7")
        assert data is not None, "Must produce valid JSON for invalid messages"
        assert len(data["errors"]) > 0, "Invalid message should have errors"
        err = data["errors"][0]
        assert "category" in err, "Each error must have 'category'"
        assert "path" in err, "Each error must have 'path'"
        assert "message" in err, "Each error must have 'message'"


# ── ADT Profile: Exit Codes ─────────────────────────────────────────


class TestExitCodes:
    def test_valid_message_exit_0(self):
        rc, _ = run_adt("msg_valid.hl7")
        assert rc == 0, f"Valid message should exit 0, got {rc}"

    def test_invalid_message_exit_1(self):
        rc, _ = run_adt("msg_missing_evn.hl7")
        assert rc == 1, f"Invalid message should exit 1, got {rc}"

    def test_constraint_violation_exit_1(self):
        rc, _ = run_adt("msg_wrong_trigger.hl7")
        assert rc == 1

    def test_multi_error_exit_1(self):
        rc, _ = run_adt("msg_multi_error.hl7")
        assert rc == 1


# ── ADT Profile: Valid Message ───────────────────────────────────────


class TestValidMessage:
    def test_valid_adt_message_passes(self):
        rc, data = run_adt("msg_valid.hl7")
        assert data is not None
        assert data["valid"] is True, f"Valid message should pass. Errors: {data.get('errors', [])}"
        assert len(data["errors"]) == 0, f"Valid message should have no errors. Got: {data['errors']}"


# ── ADT Profile: STRUCTURE category ────────────────────────────────


class TestStructureValidation:
    def test_missing_required_segment_evn(self):
        """EVN is Usage=R in the profile but missing from the message."""
        rc, data = run_adt("msg_missing_evn.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="STRUCTURE", path_contains="EVN"), \
            f"Should report STRUCTURE error for missing EVN. Errors: {data['errors']}"

    def test_group_structure_valid(self):
        """INSURANCE group with IN1 should be accepted."""
        rc, data = run_adt("msg_group_valid.hl7")
        assert data is not None
        assert data["valid"] is True, f"Group message should be valid. Errors: {data.get('errors', [])}"


# ── ADT Profile: CONSTRAINT category ──────────────────────────────


class TestConstraintValidation:
    def test_wrong_trigger_event(self):
        """MSH.9.2 value doesn't match the profile's constraint assertion."""
        rc, data = run_adt("msg_wrong_trigger.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="CONSTRAINT"), \
            f"Should report CONSTRAINT error. Errors: {data['errors']}"

    def test_wrong_version(self):
        """Version ID doesn't match the datatype-level constraint."""
        rc, data = run_adt("msg_wrong_version.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="CONSTRAINT"), \
            f"Should report CONSTRAINT error for wrong version. Errors: {data['errors']}"


# ── ADT Profile: VALUESET category ───────────────────────────────


class TestValueSetValidation:
    def test_invalid_patient_class(self):
        """PV1.2 contains a value not in the bound value set."""
        rc, data = run_adt("msg_bad_valueset.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="VALUESET", path_contains="PV1"), \
            f"Should report VALUESET error for PV1. Errors: {data['errors']}"

    def test_valid_processing_id_no_valueset_error(self):
        """Valid processing ID should not trigger VALUESET error."""
        rc, data = run_adt("msg_valid.hl7")
        assert data is not None
        valueset_errors_msh11 = [
            e for e in data.get("errors", [])
            if e.get("category") == "VALUESET" and "MSH" in e.get("path", "") and "11" in e.get("path", "")
        ]
        assert len(valueset_errors_msh11) == 0, \
            f"Valid processing ID should not trigger VALUESET error. Got: {valueset_errors_msh11}"

    def test_multi_error_invalid_processing_id(self):
        """msg_multi_error has an invalid processing ID code."""
        rc, data = run_adt("msg_multi_error.hl7")
        assert data is not None
        has_proc_id_error = any(
            e.get("category") == "VALUESET" and "MSH" in e.get("path", "")
            for e in data.get("errors", [])
        )
        assert has_proc_id_error, \
            f"Invalid processing ID should trigger VALUESET error. Errors: {data['errors']}"


# ── ADT Profile: USAGE category ─────────────────────────────────


class TestUsageValidation:
    def test_missing_required_fields(self):
        """Segment has Required fields that are empty."""
        rc, data = run_adt("msg_missing_req_field.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="USAGE", path_contains="PV1"), \
            f"Should report USAGE error for PV1 missing required fields. Errors: {data['errors']}"

    def test_x_usage_field_present(self):
        """A field marked Usage=X has a value when it should be empty."""
        rc, data = run_adt("msg_x_usage.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="USAGE", path_contains="MSH"), \
            f"Should report USAGE error for MSH X-usage field. Errors: {data['errors']}"

    def test_predicate_conditional_usage(self):
        """OBX predicate: when OBX.5 is valued, OBX.2 becomes required. OBX.2 is empty."""
        rc, data = run_adt("msg_obx_predicate.hl7")
        assert data is not None
        assert data["valid"] is False
        has_obx_error = any(
            e.get("category") == "USAGE" and "OBX" in e.get("path", "")
            for e in data.get("errors", [])
        )
        assert has_obx_error, \
            f"OBX.2 should be required by predicate. Errors: {data['errors']}"


# ── ADT Profile: LENGTH category ────────────────────────────────


class TestLengthValidation:
    def test_field_exceeds_max_length(self):
        """MSH.10 value exceeds MaxLength defined in the profile."""
        rc, data = run_adt("msg_length_violation.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="LENGTH", path_contains="MSH.10"), \
            f"Should report LENGTH error for MSH.10. Errors: {data['errors']}"


# ── ADT Profile: SCHEMATRON category ────────────────────────────


class TestSchematronValidation:
    def test_inpatient_without_location(self):
        """PV1.2='I' but PV1.3 empty triggers Schematron cross-field rule."""
        rc, data = run_adt("msg_sch_inpatient_no_loc.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="SCHEMATRON", path_contains="PV1"), \
            f"Should report SCHEMATRON error for PV1. Errors: {data['errors']}"

    def test_missing_assigning_authority(self):
        """PID.3 has ID but no assigning authority triggers Schematron rule."""
        rc, data = run_adt("msg_sch_no_authority.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="SCHEMATRON", path_contains="PID"), \
            f"Should report SCHEMATRON error for PID. Errors: {data['errors']}"

    def test_valid_message_no_schematron_errors(self):
        """Valid message should not trigger any Schematron errors."""
        rc, data = run_adt("msg_valid.hl7")
        assert data is not None
        sch_errors = [e for e in data.get("errors", []) if e.get("category") == "SCHEMATRON"]
        assert len(sch_errors) == 0, f"Valid message should have no SCHEMATRON errors. Got: {sch_errors}"


# ── ADT Profile: Multiple Errors ────────────────────────────────


class TestMultipleErrors:
    def test_multi_error_count(self):
        """Message with many issues should report multiple errors."""
        rc, data = run_adt("msg_multi_error.hl7")
        assert data is not None
        assert data["valid"] is False
        assert len(data["errors"]) >= 4, \
            f"Multi-error message should have >=4 errors. Got {len(data['errors'])}: {data['errors']}"

    def test_multi_error_has_multiple_categories(self):
        """Multiple distinct error categories should be present."""
        rc, data = run_adt("msg_multi_error.hl7")
        assert data is not None
        categories = set(e.get("category") for e in data.get("errors", []))
        assert len(categories) >= 2, \
            f"Should have >=2 different error categories. Got: {categories}"


# ── ADT Profile: Edge Cases ─────────────────────────────────────


class TestEdgeCases:
    def test_nonexistent_file(self):
        """Validator should not crash on nonexistent message file."""
        result = subprocess.run(
            VALIDATE_CMD + [PROFILE_ADT, "/app/messages/nonexistent.hl7"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode != 0

    def test_empty_message(self):
        """Validator should handle empty input gracefully."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.hl7', delete=False) as f:
            f.write("")
            tmp_path = f.name
        try:
            result = subprocess.run(
                VALIDATE_CMD + [PROFILE_ADT, tmp_path],
                capture_output=True, text=True, timeout=60
            )
            assert result.returncode != 0
        finally:
            os.unlink(tmp_path)

    def test_msg_with_repetitions(self):
        """Message with field repetitions should be handled correctly."""
        msg = (
            "MSH|^~\\&|RADIS|HOSP_A|PACS|HOSP_B|20240315143022||ADT^A01^ADT_A01|CTRL_REP|P|2.5.1|||AL|NE\n"
            "EVN||20240315143022||||20240315143022\n"
            "PID|||MRN001^^^HOSP_A~MRN002^^^HOSP_B||SMITH^JOHN||19650315|M\n"
            "PV1||I|W4^402^1||||1234^DOC^JANE|||MED\n"
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.hl7', delete=False) as f:
            f.write(msg)
            tmp_path = f.name
        try:
            result = subprocess.run(
                VALIDATE_CMD + [PROFILE_ADT, tmp_path],
                capture_output=True, text=True, timeout=60
            )
            try:
                data = json.loads(result.stdout)
            except (json.JSONDecodeError, ValueError):
                data = None
            assert data is not None, "Should produce valid JSON for message with repetitions"
            assert data["valid"] is True, f"Message with repetitions should be valid. Errors: {data.get('errors', [])}"
        finally:
            os.unlink(tmp_path)


# ── ACK Profile: Valid Message ───────────────────────────────────


class TestACKValidMessage:
    def test_valid_ack_passes(self):
        """A conformant ACK message against the ACK profile should pass."""
        rc, data = run_ack("msg_ack_valid.hl7")
        assert data is not None
        assert data["valid"] is True, f"Valid ACK should pass. Errors: {data.get('errors', [])}"
        assert rc == 0

    def test_ack_with_err_segment(self):
        """ACK with optional ERR segment (all required ERR fields present) should pass."""
        rc, data = run_ack("msg_ack_with_err.hl7")
        assert data is not None
        assert data["valid"] is True, f"ACK with valid ERR should pass. Errors: {data.get('errors', [])}"
        assert rc == 0


# ── ACK Profile: STRUCTURE category ────────────────────────────


class TestACKStructure:
    def test_missing_required_msa(self):
        """MSA is Required but missing from the ACK message."""
        rc, data = run_ack("msg_ack_missing_msa.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="STRUCTURE", path_contains="MSA"), \
            f"Should report STRUCTURE error for missing MSA. Errors: {data['errors']}"


# ── ACK Profile: VALUESET category ──────────────────────────────


class TestACKValueSets:
    def test_bad_acknowledgment_code(self):
        """MSA.1 contains a code not in the bound value set."""
        rc, data = run_ack("msg_ack_bad_ack_code.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="VALUESET"), \
            f"Should report VALUESET error for bad ack code. Errors: {data['errors']}"

    def test_bad_err_severity(self):
        """ERR.4 contains a severity code not in the bound value set."""
        rc, data = run_ack("msg_ack_bad_severity.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="VALUESET", path_contains="ERR"), \
            f"Should report VALUESET error for ERR severity. Errors: {data['errors']}"


# ── ACK Profile: CONSTRAINT category ────────────────────────────


class TestACKConstraints:
    def test_wrong_message_type(self):
        """MSH.9.1 doesn't match the ACK profile's message-level constraint."""
        rc, data = run_ack("msg_ack_wrong_type.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="CONSTRAINT"), \
            f"Should report CONSTRAINT error for wrong message type. Errors: {data['errors']}"


# ── ACK Profile: SCHEMATRON category ────────────────────────────


class TestACKSchematron:
    def test_error_ack_without_err_segment(self):
        """MSA.1='AE' but no ERR segment triggers Schematron cross-segment rule."""
        rc, data = run_ack("msg_ack_sch_no_err.hl7")
        assert data is not None
        assert data["valid"] is False
        assert has_error_with(data, category="SCHEMATRON", path_contains="ERR"), \
            f"Should report SCHEMATRON error for missing ERR. Errors: {data['errors']}"

    def test_error_ack_with_err_no_schematron_error(self):
        """MSA.1='AE' with ERR segment present should not trigger Schematron error."""
        rc, data = run_ack("msg_ack_with_err.hl7")
        assert data is not None
        sch_errors = [e for e in data.get("errors", []) if e.get("category") == "SCHEMATRON"]
        assert len(sch_errors) == 0, f"ACK with ERR should have no SCHEMATRON errors. Got: {sch_errors}"


# ── Cross-profile: Generality ───────────────────────────────────


class TestCrossProfileGenerality:
    def test_adt_message_against_ack_profile_fails(self):
        """An ADT message validated against the ACK profile should fail
        (wrong structure, wrong message type constraint)."""
        rc, data = run_validator(PROFILE_ACK, os.path.join(MESSAGES_ADT, "msg_valid.hl7"))
        assert data is not None
        assert data["valid"] is False, \
            "ADT message against ACK profile should not pass"
        assert len(data["errors"]) > 0
