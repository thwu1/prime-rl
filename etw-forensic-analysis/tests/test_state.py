
"""
Tests for ETW SecurityTrace forensic dump analysis and detection engineering.
Verifies /app/findings.json correctness, comparative technique evaluation,
and YARA detection rule validity.
"""

import json
import os
import subprocess
import pytest


FINDINGS_PATH = "/app/findings.json"
YARA_RULE_PATH = "/app/detect_bypass.yar"
ATTACK_DUMP_PATH = "/app/etw_dump.bin"
CLEAN_DUMP_PATH = "/app/etw_clean.bin"


@pytest.fixture
def findings():
    assert os.path.exists(FINDINGS_PATH), (
        f"findings.json not found at {FINDINGS_PATH}"
    )
    with open(FINDINGS_PATH) as f:
        data = json.load(f)
    return data


def _get_anomalous_session(findings, logger_id):
    """Helper to find the anomalous session with the expected logger ID."""
    sessions = findings.get("anomalous_sessions", [])
    for s in sessions:
        lid = s.get("logger_id")
        if lid == logger_id:
            return s
    return None


def _get_technique_entry(findings, logger_id):
    """Helper to find technique analysis entry for a given logger ID."""
    entries = findings.get("technique_analysis", [])
    for e in entries:
        if e.get("logger_id") == logger_id:
            return e
    return None


def _parse_hex(val):
    """Parse a hex value from either int or string representation."""
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        return int(val, 16) if val.startswith("0x") or val.startswith("0X") else int(val)
    return None


# == Structure & Schema =====================================================

class TestFindingsStructure:
    def test_findings_file_exists(self):
        assert os.path.exists(FINDINGS_PATH), "findings.json missing"

    def test_findings_is_valid_json(self):
        with open(FINDINGS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_anomalous_sessions(self, findings):
        assert "anomalous_sessions" in findings
        assert isinstance(findings["anomalous_sessions"], list)

    def test_has_security_trace_bit(self, findings):
        bit = findings.get(
            "security_trace_bit_position",
            findings.get("security_trace_bit", None),
        )
        assert bit is not None, "findings must contain 'security_trace_bit_position'"

    def test_has_security_trace_mask(self, findings):
        mask = findings.get(
            "security_trace_mask_hex",
            findings.get("security_trace_mask", None),
        )
        assert mask is not None, "findings must contain 'security_trace_mask_hex'"

    def test_has_technique_analysis(self, findings):
        assert "technique_analysis" in findings, (
            "findings must contain 'technique_analysis'"
        )
        assert isinstance(findings["technique_analysis"], list)


# == Anomalous Session Count ================================================

class TestAnomalousSessionCount:
    def test_exactly_two_anomalous_sessions(self, findings):
        sessions = findings["anomalous_sessions"]
        assert len(sessions) == 2, (
            f"Should find exactly 2 anomalous sessions, found {len(sessions)}"
        )

    def test_only_expected_sessions_flagged(self, findings):
        sessions = findings["anomalous_sessions"]
        flagged_ids = {s.get("logger_id") for s in sessions}
        assert flagged_ids == {12, 14}, (
            f"Expected anomalous sessions 12 and 14, got {flagged_ids}"
        )


# == Session 12: Union Overlap Bypass =======================================

class TestSession12Identification:
    def test_correct_logger_id(self, findings):
        target = _get_anomalous_session(findings, 12)
        assert target is not None, (
            "Anomalous session with logger_id=12 not found"
        )

    def test_correct_logger_name(self, findings):
        target = _get_anomalous_session(findings, 12)
        assert target is not None
        name = target.get("logger_name", "")
        assert "ThreatIntelConsumer" in name, (
            f"Expected name containing 'ThreatIntelConsumer', got '{name}'"
        )

    def test_correct_flags(self, findings):
        target = _get_anomalous_session(findings, 12)
        assert target is not None
        flags_raw = target.get("flags_hex", target.get("flags", None))
        assert flags_raw is not None
        flags_val = _parse_hex(flags_raw)
        assert flags_val == 0x4008, (
            f"Expected flags=0x4008, got 0x{flags_val:X}"
        )

    def test_consumer_pid(self, findings):
        target = _get_anomalous_session(findings, 12)
        assert target is not None
        consumers = target.get("consumers", [])
        pids = [c.get("pid") for c in consumers]
        assert 5932 in pids, f"Expected consumer PID 5932, found {pids}"

    def test_consumer_process_name(self, findings):
        target = _get_anomalous_session(findings, 12)
        assert target is not None
        consumers = target.get("consumers", [])
        consumer = next((c for c in consumers if c.get("pid") == 5932), None)
        assert consumer is not None
        pname = consumer.get("process_name", "")
        assert "ThreatIntel" in pname, (
            f"Expected process name containing 'ThreatIntel', got '{pname}'"
        )

    def test_consumer_not_protected(self, findings):
        target = _get_anomalous_session(findings, 12)
        assert target is not None
        consumers = target.get("consumers", [])
        consumer = next((c for c in consumers if c.get("pid") == 5932), None)
        assert consumer is not None
        prot_raw = consumer.get(
            "protection_level_hex",
            consumer.get("protection_level", None),
        )
        assert prot_raw is not None
        prot_val = _parse_hex(prot_raw)
        assert prot_val == 0x00, (
            f"Expected protection_level=0x00, got 0x{prot_val:X}"
        )

    def test_threat_intelligence_guid(self, findings):
        target = _get_anomalous_session(findings, 12)
        assert target is not None
        providers = target.get("providers", [])
        ti_guid_fragment = "f4e1897c"
        found = any(ti_guid_fragment in str(p).lower() for p in providers)
        assert found, (
            "Microsoft-Windows-Threat-Intelligence GUID "
            "(f4e1897c-bb5d-5668-f1d8-040f4d8dd344) not in providers: "
            f"{providers}"
        )


# == Session 14: DKOM Bypass ================================================

class TestSession14Identification:
    def test_correct_logger_id(self, findings):
        target = _get_anomalous_session(findings, 14)
        assert target is not None, (
            "Anomalous session with logger_id=14 not found"
        )

    def test_correct_logger_name(self, findings):
        target = _get_anomalous_session(findings, 14)
        assert target is not None
        name = target.get("logger_name", "")
        assert "SecurityAuditConsumer" in name, (
            f"Expected name containing 'SecurityAuditConsumer', got '{name}'"
        )

    def test_correct_flags(self, findings):
        target = _get_anomalous_session(findings, 14)
        assert target is not None
        flags_raw = target.get("flags_hex", target.get("flags", None))
        assert flags_raw is not None
        flags_val = _parse_hex(flags_raw)
        assert flags_val == 0x4008, (
            f"Expected flags=0x4008, got 0x{flags_val:X}"
        )

    def test_consumer_pid(self, findings):
        target = _get_anomalous_session(findings, 14)
        assert target is not None
        consumers = target.get("consumers", [])
        pids = [c.get("pid") for c in consumers]
        assert 6844 in pids, f"Expected consumer PID 6844, found {pids}"

    def test_consumer_process_name(self, findings):
        target = _get_anomalous_session(findings, 14)
        assert target is not None
        consumers = target.get("consumers", [])
        consumer = next((c for c in consumers if c.get("pid") == 6844), None)
        assert consumer is not None
        pname = consumer.get("process_name", "")
        assert "AuditCapture" in pname, (
            f"Expected process name containing 'AuditCapture', got '{pname}'"
        )

    def test_consumer_not_protected(self, findings):
        target = _get_anomalous_session(findings, 14)
        assert target is not None
        consumers = target.get("consumers", [])
        consumer = next((c for c in consumers if c.get("pid") == 6844), None)
        assert consumer is not None
        prot_raw = consumer.get(
            "protection_level_hex",
            consumer.get("protection_level", None),
        )
        assert prot_raw is not None
        prot_val = _parse_hex(prot_raw)
        assert prot_val == 0x00, (
            f"Expected protection_level=0x00, got 0x{prot_val:X}"
        )

    def test_kernel_audit_api_guid(self, findings):
        target = _get_anomalous_session(findings, 14)
        assert target is not None
        providers = target.get("providers", [])
        audit_guid_fragment = "e02a841c"
        found = any(audit_guid_fragment in str(p).lower() for p in providers)
        assert found, (
            "Microsoft-Windows-Kernel-Audit-API-Calls GUID "
            "(e02a841c-75a3-4fa7-afc8-ae09cf9b7f23) not in providers: "
            f"{providers}"
        )


# == SecurityTrace Metadata =================================================

class TestSecurityTraceMetadata:
    def test_security_trace_bit_is_14(self, findings):
        bit = findings.get(
            "security_trace_bit_position",
            findings.get("security_trace_bit", None),
        )
        assert bit == 14, f"SecurityTrace bit position should be 14, got {bit}"

    def test_security_trace_mask_is_0x4000(self, findings):
        mask_raw = findings.get(
            "security_trace_mask_hex",
            findings.get("security_trace_mask", None),
        )
        mask_val = _parse_hex(mask_raw)
        assert mask_val == 0x4000, (
            f"SecurityTrace mask should be 0x4000, got 0x{mask_val:X}"
        )


# == No False Positives =====================================================

class TestNoFalsePositives:
    def test_defender_api_logger_not_flagged(self, findings):
        """DefenderApiLogger (id=4) has SecurityTrace but legit AM-PPL consumer."""
        target = _get_anomalous_session(findings, 4)
        assert target is None, (
            "DefenderApiLogger (id=4) has AM-PPL consumer, should NOT be anomalous"
        )

    def test_defender_audit_logger_not_flagged(self, findings):
        """DefenderAuditLogger (id=5) has SecurityTrace but legit AM-PPL consumer."""
        target = _get_anomalous_session(findings, 5)
        assert target is None, (
            "DefenderAuditLogger (id=5) has AM-PPL consumer, should NOT be anomalous"
        )

    def test_eventlog_security_not_flagged(self, findings):
        """EventLog-Security (id=3) has SecurityTrace but legit LSA-PPL consumer."""
        target = _get_anomalous_session(findings, 3)
        assert target is None, (
            "EventLog-Security (id=3) has LSA-PPL consumer (0x41), should NOT be anomalous"
        )

    def test_non_security_trace_sessions_not_flagged(self, findings):
        """Sessions without SecurityTrace should never appear."""
        sessions = findings["anomalous_sessions"]
        non_sectrace_ids = {2, 6, 7, 8, 9, 10, 11, 13}
        for s in sessions:
            lid = s.get("logger_id")
            assert lid not in non_sectrace_ids, (
                f"Session id={lid} does not have SecurityTrace, should not be anomalous"
            )


# == Comparative Technique Analysis =========================================

class TestComparativeTechniqueAnalysis:
    def test_technique_analysis_present(self, findings):
        assert "technique_analysis" in findings
        assert isinstance(findings["technique_analysis"], list)

    def test_technique_analysis_count(self, findings):
        entries = findings["technique_analysis"]
        assert len(entries) == 2, (
            f"Expected 2 technique analysis entries (one per anomalous session), "
            f"got {len(entries)}"
        )

    def test_session_12_technique_is_union_overlap(self, findings):
        """Session 12 forensic evidence (LogBuffersLost == Flags == 0x4008)
        uniquely matches the LogBuffersLost union overlap technique."""
        entry = _get_technique_entry(findings, 12)
        assert entry is not None, (
            "technique_analysis entry for logger_id=12 not found"
        )
        method = entry.get("identified_technique", "").lower().replace("-", "_").replace(" ", "_")
        valid_indicators = ["log_buffers", "union_overlap", "logbufferslost", "union"]
        assert any(ind in method for ind in valid_indicators), (
            f"Expected LogBuffersLost union overlap for session 12, got '{method}'"
        )

    def test_session_14_technique_is_dkom(self, findings):
        """Session 14 forensic evidence (LogBuffersLost=7, normal; Flags=0x4008,
        modified independently) uniquely matches the DKOM technique."""
        entry = _get_technique_entry(findings, 14)
        assert entry is not None, (
            "technique_analysis entry for logger_id=14 not found"
        )
        method = entry.get("identified_technique", "").lower().replace("-", "_").replace(" ", "_")
        valid_indicators = ["dkom", "direct_kernel", "kernel_object"]
        assert any(ind in method for ind in valid_indicators), (
            f"Expected direct kernel object modification for session 14, got '{method}'"
        )

    def test_session_12_ruling_out_has_three_entries(self, findings):
        entry = _get_technique_entry(findings, 12)
        assert entry is not None
        ruling_out = entry.get("ruling_out", {})
        assert isinstance(ruling_out, dict)
        assert len(ruling_out) == 3, (
            f"Session 12 ruling_out should exclude exactly 3 techniques, "
            f"got {len(ruling_out)}: {list(ruling_out.keys())}"
        )

    def test_session_14_ruling_out_has_three_entries(self, findings):
        entry = _get_technique_entry(findings, 14)
        assert entry is not None
        ruling_out = entry.get("ruling_out", {})
        assert isinstance(ruling_out, dict)
        assert len(ruling_out) == 3, (
            f"Session 14 ruling_out should exclude exactly 3 techniques, "
            f"got {len(ruling_out)}: {list(ruling_out.keys())}"
        )

    def test_session_12_ruling_out_substantive(self, findings):
        """Each ruling-out reason must be a substantive evidence-based explanation."""
        entry = _get_technique_entry(findings, 12)
        assert entry is not None
        for tech_name, reason in entry.get("ruling_out", {}).items():
            assert isinstance(reason, str) and len(reason) >= 20, (
                f"Ruling out '{tech_name}' for session 12 must be a substantive "
                f"explanation (>=20 chars), got: '{reason}'"
            )

    def test_session_14_ruling_out_substantive(self, findings):
        """Each ruling-out reason must be a substantive evidence-based explanation."""
        entry = _get_technique_entry(findings, 14)
        assert entry is not None
        for tech_name, reason in entry.get("ruling_out", {}).items():
            assert isinstance(reason, str) and len(reason) >= 20, (
                f"Ruling out '{tech_name}' for session 14 must be a substantive "
                f"explanation (>=20 chars), got: '{reason}'"
            )

    def test_session_12_severity_is_critical(self, findings):
        entry = _get_technique_entry(findings, 12)
        assert entry is not None
        severity = entry.get("severity", "").lower()
        assert severity == "critical", (
            f"Session 12 severity should be 'critical', got '{severity}'"
        )

    def test_session_14_severity_is_critical(self, findings):
        entry = _get_technique_entry(findings, 14)
        assert entry is not None
        severity = entry.get("severity", "").lower()
        assert severity == "critical", (
            f"Session 14 severity should be 'critical', got '{severity}'"
        )

    def test_identified_techniques_are_distinct(self, findings):
        """The two anomalous sessions must use different bypass techniques."""
        entries = findings.get("technique_analysis", [])
        assert len(entries) == 2
        t1 = entries[0].get("identified_technique", "").lower()
        t2 = entries[1].get("identified_technique", "").lower()
        assert t1 != t2, (
            f"Both sessions classified as '{t1}' — different techniques expected"
        )


# == YARA Detection Rule ====================================================

class TestYaraDetectionRule:
    def test_yara_rule_file_exists(self):
        assert os.path.exists(YARA_RULE_PATH), (
            f"YARA rule not found at {YARA_RULE_PATH}"
        )

    def test_yara_rule_compiles(self):
        """Verify YARA rule has valid syntax."""
        result = subprocess.run(
            ["yara", YARA_RULE_PATH, "/dev/null"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"YARA rule failed to compile: {result.stderr}"
        )

    def test_yara_matches_attack_dump(self):
        """YARA rule must detect the bypass pattern in the attack dump."""
        result = subprocess.run(
            ["yara", YARA_RULE_PATH, ATTACK_DUMP_PATH],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"YARA error: {result.stderr}"
        assert result.stdout.strip() != "", (
            "YARA rule should match the attack dump but produced no output"
        )

    def test_yara_no_false_positive_on_clean(self):
        """YARA rule must NOT match the clean reference dump."""
        result = subprocess.run(
            ["yara", YARA_RULE_PATH, CLEAN_DUMP_PATH],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"YARA error: {result.stderr}"
        assert result.stdout.strip() == "", (
            f"YARA rule falsely matched clean dump: {result.stdout.strip()}"
        )

    def test_yara_rule_has_metadata(self):
        """YARA rule should include descriptive metadata."""
        with open(YARA_RULE_PATH) as f:
            content = f.read()
        assert "meta" in content.lower(), (
            "YARA rule should include a meta section"
        )
        assert "description" in content.lower(), (
            "YARA rule should include a description in its metadata"
        )
