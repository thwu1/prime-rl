
import json
import os
import subprocess
import tempfile
import pytest

VALIDATOR = "/app/hl7v2_validator.py"
PROFILE = "/app/profiles/oru_r01_profile.xml"


def run_validator(message_file):
    """Run the validator and return parsed JSON output."""
    result = subprocess.run(
        ["python3", VALIDATOR, PROFILE, message_file],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"Validator crashed: {result.stderr}"
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"Validator output is not valid JSON: {result.stdout[:500]}")


def write_msg(content):
    """Write message content to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".er7")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


class TestOutputStructure:
    """Verify the JSON output has the required structure."""

    def test_output_has_required_keys(self):
        report = run_validator("/app/messages/valid_minimal.er7")
        assert "valid" in report
        assert "counts" in report
        assert "issues" in report
        for key in ["usage", "cardinality", "length", "invalid_lines",
                     "unexpected_segments", "extra", "unescaped_separators"]:
            assert key in report["counts"], f"Missing count key: {key}"

    def test_issues_have_required_fields(self):
        report = run_validator("/app/messages/usage_violations.er7")
        assert len(report["issues"]) > 0
        for issue in report["issues"]:
            assert "category" in issue
            assert "severity" in issue
            assert "path" in issue
            assert "description" in issue
            assert issue["severity"] in ("error", "warning")


class TestValidMessage:
    """A minimally valid message should produce zero issues."""

    def test_valid_minimal(self):
        report = run_validator("/app/messages/valid_minimal.er7")
        assert report["valid"] is True
        assert sum(report["counts"].values()) == 0
        assert len(report["issues"]) == 0


class TestUsageViolations:
    """Test detection of R-missing, X-present, and W-present usage violations."""

    def test_usage_violations_message(self):
        report = run_validator("/app/messages/usage_violations.er7")
        assert report["valid"] is False
        usage_issues = [i for i in report["issues"] if i["category"] == "usage"]
        assert len(usage_issues) >= 4

    def test_sft_w_usage_is_warning(self):
        """SFT segment has W usage - presence should be a warning."""
        report = run_validator("/app/messages/usage_violations.er7")
        sft_issues = [i for i in report["issues"]
                      if i["category"] == "usage" and "SFT" in i["path"]]
        assert len(sft_issues) >= 1
        for issue in sft_issues:
            assert issue["severity"] == "warning"

    def test_uac_x_usage_is_error(self):
        """UAC segment has X usage - presence should be an error."""
        report = run_validator("/app/messages/usage_violations.er7")
        uac_issues = [i for i in report["issues"]
                      if i["category"] == "usage" and "UAC" in i["path"]]
        assert len(uac_issues) >= 1
        for issue in uac_issues:
            assert issue["severity"] == "error"

    def test_r_missing_set_id_pid(self):
        """PID-1 (Set ID) is R-usage and missing (empty) in the message."""
        report = run_validator("/app/messages/usage_violations.er7")
        pid1_issues = [i for i in report["issues"]
                       if i["category"] == "usage" and "PID" in i["path"]
                       and "1" in i["path"] and "missing" in i["description"].lower()]
        assert len(pid1_issues) >= 1

    def test_x_usage_alternate_patient_id(self):
        """PID-4 (Alternate Patient ID) is X-usage and present."""
        report = run_validator("/app/messages/usage_violations.er7")
        pid4_issues = [i for i in report["issues"]
                       if i["category"] == "usage" and "PID" in i["path"]
                       and "4" in i["path"]]
        assert len(pid4_issues) >= 1

    def test_synthesized_r_missing_field(self):
        """Synthesize a message where a required field is missing."""
        # PID-5 (Patient Name) is R-usage, omit it
        msg = write_msg(
            "MSH|^~\\&|SendApp^SA1^ISO|SendFac^SF1^ISO|||20240115120000||"
            "ORU^R01^ORU_R01|MSGX1|P|2.5.1\n"
            "PID|01||PAT001^^^Auth&1.2.3&ISO\n"
            "OBR|01||FIL001|CBC^Complete Blood Count^LN\n"
            "OBX|01|NM|WBC^White Blood Cell^LN||7.5|10*3/uL\n"
        )
        try:
            report = run_validator(msg)
            usage_issues = [i for i in report["issues"]
                            if i["category"] == "usage" and "PID" in i["path"]
                            and "5" in i["path"]]
            assert len(usage_issues) >= 1
            assert any("missing" in i["description"].lower() for i in usage_issues)
        finally:
            os.unlink(msg)


class TestCardinalityViolations:
    """Test min/max cardinality checks for groups and field repetitions."""

    def test_patient_group_max_exceeded(self):
        """Profile allows max 2 PATIENT groups, message has 3."""
        report = run_validator("/app/messages/cardinality_errors.er7")
        card_issues = [i for i in report["issues"]
                       if i["category"] == "cardinality"]
        assert len(card_issues) >= 1

    def test_patient_group_cardinality_path(self):
        """Cardinality error for PATIENT group should reference PATIENT."""
        report = run_validator("/app/messages/cardinality_errors.er7")
        patient_card = [i for i in report["issues"]
                        if i["category"] == "cardinality"
                        and "PATIENT" in i["path"]]
        assert len(patient_card) >= 1

    def test_field_repetition_max_exceeded(self):
        """PID-3 allows max 3 repetitions, first PATIENT has 4."""
        report = run_validator("/app/messages/cardinality_errors.er7")
        pid3_card = [i for i in report["issues"]
                     if i["category"] == "cardinality"
                     and "PID" in i["path"] and "3" in i["path"]]
        assert len(pid3_card) >= 1

    def test_synthesized_field_min_cardinality(self):
        """OBX is R min=1 in OBSERVATION group. Omitting it should trigger error."""
        msg = write_msg(
            "MSH|^~\\&|SendApp^SA1^ISO|SendFac^SF1^ISO|||20240115120000||"
            "ORU^R01^ORU_R01|MSGX2|P|2.5.1\n"
            "PID|01||PAT001^^^Auth&1.2.3&ISO||Doe^John\n"
            "OBR|01||FIL001|CBC^Complete Blood Count^LN\n"
        )
        try:
            report = run_validator(msg)
            # OBX is R min=1, should be missing
            obx_issues = [i for i in report["issues"]
                          if ("OBX" in i.get("path", "") or "OBX" in i.get("description", ""))
                          and (i["category"] == "usage" or i["category"] == "cardinality")]
            assert len(obx_issues) >= 1
        finally:
            os.unlink(msg)


class TestLengthViolations:
    """Test min/max length checking with escape sequence resolution."""

    def test_pid_set_id_too_short(self):
        """PID-1 MinLength=2, value '1' has length 1."""
        report = run_validator("/app/messages/length_errors.er7")
        len_issues = [i for i in report["issues"]
                      if i["category"] == "length" and "PID" in i["path"]
                      and "1" in i["path"]]
        assert len(len_issues) >= 1

    def test_escape_sequence_length_calculation(self):
        """\\F\\ resolves to one character. '|1' = 2 chars, within MinLength=2."""
        report = run_validator("/app/messages/escape_length.er7")
        # PID-1 value is \F\1 which resolves to "|1" = 2 chars, within [2,4]
        len_issues = [i for i in report["issues"]
                      if i["category"] == "length" and "PID" in i["path"]
                      and "1" in i["path"]]
        # Should NOT have a length error for PID-1 since resolved length is 2
        assert len(len_issues) == 0

    def test_synthesized_length_too_long(self):
        """PID-1 MaxLength=4, provide value '12345' (length 5)."""
        msg = write_msg(
            "MSH|^~\\&|SendApp^SA1^ISO|SendFac^SF1^ISO|||20240115120000||"
            "ORU^R01^ORU_R01|MSGX3|P|2.5.1\n"
            "PID|12345||PAT001^^^Auth&1.2.3&ISO||Doe^John\n"
            "OBR|01||FIL001|CBC^Complete Blood Count^LN\n"
            "OBX|01|NM|WBC^White Blood Cell^LN||7.5|10*3/uL\n"
        )
        try:
            report = run_validator(msg)
            len_issues = [i for i in report["issues"]
                          if i["category"] == "length" and "PID" in i["path"]
                          and "1" in i["path"]]
            assert len(len_issues) >= 1
        finally:
            os.unlink(msg)


class TestInvalidLines:
    """Test detection of lines that are not valid segments."""

    def test_invalid_lines_detected(self):
        report = run_validator("/app/messages/invalid_lines.er7")
        assert report["counts"]["invalid_lines"] == 3

    def test_invalid_lines_category(self):
        report = run_validator("/app/messages/invalid_lines.er7")
        inv_issues = [i for i in report["issues"]
                      if i["category"] == "invalid_lines"]
        assert len(inv_issues) == 3
        # All should be errors
        for issue in inv_issues:
            assert issue["severity"] == "error"


class TestUnexpectedSegments:
    """Test detection of syntactically valid but profile-undefined segments."""

    def test_unexpected_segment_detected(self):
        report = run_validator("/app/messages/unexpected_segment.er7")
        assert report["counts"]["unexpected_segments"] >= 1

    def test_unexpected_segment_is_pdq(self):
        report = run_validator("/app/messages/unexpected_segment.er7")
        unexp_issues = [i for i in report["issues"]
                        if i["category"] == "unexpected_segments"]
        assert len(unexp_issues) >= 1
        assert any("PDQ" in i["description"] or "PDQ" in i["path"]
                    for i in unexp_issues)


class TestExtraElements:
    """Test detection of fields/components beyond what the profile defines."""

    def test_extra_component_in_xpn(self):
        """XPN has 7 components in profile. Message has Degree (W-usage, position 6)
        plus Name Type Code (position 7) — those are defined. But the 'L' at position 7
        is within bounds. The extra_components message has PhD at position 6 (W-usage,
        so should trigger W-usage warning)."""
        report = run_validator("/app/messages/extra_components.er7")
        # The XPN Degree component (position 6) is W-usage, present = warning
        w_issues = [i for i in report["issues"]
                    if i["category"] == "usage" and i["severity"] == "warning"
                    and "PID" in i["path"] and "5" in i["path"]]
        assert len(w_issues) >= 1


class TestUnescapedSeparators:
    """Test detection of raw separator characters in primitive values."""

    def test_unescaped_subcomponent_separator(self):
        """XPN Given Name 'Jo&hn' contains raw & (subcomponent separator)."""
        report = run_validator("/app/messages/unescaped_separators.er7")
        assert report["counts"]["unescaped_separators"] >= 1

    def test_synthesized_unescaped_component_sep(self):
        """Test raw ^ in a primitive string field."""
        msg = write_msg(
            "MSH|^~\\&|SendApp^SA1^ISO|SendFac^SF1^ISO|||20240115120000||"
            "ORU^R01^ORU_R01|MSGX5|P|2.5.1\n"
            "PID|01||PAT001^^^Auth&1.2.3&ISO||Doe^John\n"
            "OBR|01||FIL001|CBC^Complete Blood Count^LN\n"
            "OBX|01|NM|WBC^White Blood Cell^LN||7^5|10*3/uL\n"
        )
        try:
            report = run_validator(msg)
            # OBX-5 value is "7^5" — the ^ is a component separator inside
            # what should be a primitive ST field. But OBX-5 is ST type,
            # so any ^ inside it is an unescaped component separator.
            # However, this is ambiguous since CWE fields legitimately use ^.
            # The validator should detect unescaped seps in ST-typed fields.
            unesc = [i for i in report["issues"]
                     if i["category"] == "unescaped_separators"
                     and "OBX" in i["path"]]
            assert len(unesc) >= 1
        finally:
            os.unlink(msg)


class TestComplexScenario:
    """Test a complex message with multiple validation issues simultaneously."""

    def test_multi_issue_message(self):
        """A single message that triggers usage, cardinality, length, and
        unexpected segment issues all at once."""
        msg = write_msg(
            "MSH|^~\\&|SendApp^SA1^ISO|SendFac^SF1^ISO|||20240115120000||"
            "ORU^R01^ORU_R01|MSGMULTI|P|2.5.1\n"
            "SFT|VendorOrg|ProductName\n"
            "PID|1||PAT001~PAT002~PAT003~PAT004||Doe^John\n"
            "OBR|01||FIL001|CBC^Complete Blood Count^LN\n"
            "OBX|01|NM|WBC^White Blood Cell^LN||7.5|10*3/uL\n"
            "ZZZ|custom\n"
        )
        try:
            report = run_validator(msg)
            assert report["valid"] is False
            # SFT W-usage present => warning
            assert report["counts"]["usage"] >= 1
            # PID-3 has 4 reps, max 3 => cardinality
            assert report["counts"]["cardinality"] >= 1
            # PID-1 value '1' length=1, min=2 => length
            assert report["counts"]["length"] >= 1
            # ZZZ not in profile => unexpected
            assert report["counts"]["unexpected_segments"] >= 1
            # Total issues >= 4
            assert len(report["issues"]) >= 4
        finally:
            os.unlink(msg)

    def test_nested_group_validation(self):
        """Verify the validator correctly handles nested groups (VISIT inside PATIENT)."""
        msg = write_msg(
            "MSH|^~\\&|SendApp^SA1^ISO|SendFac^SF1^ISO|||20240115120000||"
            "ORU^R01^ORU_R01|MSGNEST|P|2.5.1\n"
            "PID|01||PAT001^^^Auth&1.2.3&ISO||Doe^John\n"
            "PV1|01|I\n"
            "PV2|SomeLocation\n"
            "OBR|01||FIL001|CBC^Complete Blood Count^LN\n"
            "OBX|01|NM|WBC^White Blood Cell^LN||7.5|10*3/uL\n"
        )
        try:
            report = run_validator(msg)
            # This should be a valid message with VISIT group populated
            assert report["valid"] is True
        finally:
            os.unlink(msg)

    def test_multiple_observation_groups(self):
        """Multiple OBR/OBX sets within one PATIENT group should be valid."""
        msg = write_msg(
            "MSH|^~\\&|SendApp^SA1^ISO|SendFac^SF1^ISO|||20240115120000||"
            "ORU^R01^ORU_R01|MSGMOBS|P|2.5.1\n"
            "PID|01||PAT001^^^Auth&1.2.3&ISO||Doe^John\n"
            "OBR|01||FIL001|CBC^Complete Blood Count^LN\n"
            "OBX|01|NM|WBC^White Blood Cell^LN||7.5|10*3/uL\n"
            "OBR|02||FIL002|BMP^Basic Metabolic Panel^LN\n"
            "OBX|01|NM|GLU^Glucose^LN||95|mg/dL\n"
        )
        try:
            report = run_validator(msg)
            assert report["valid"] is True
        finally:
            os.unlink(msg)
