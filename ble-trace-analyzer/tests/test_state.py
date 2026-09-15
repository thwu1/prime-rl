
import json
import os
import pytest


RESULTS_DIR = "/app/results"

# Known encryption parameters (must match gen_traces.py)
LTK_HEX = '4C68384139F574D836BCF34E9DFB01BF'
T01_SKDS_HEX = 'FEDCBA9876543210'
T01_SKDM_HEX = 'DEADBEEFCAFEBABE'
T05_SKDS_HEX = 'FEDCBA9876543210'
T05_SKDM_HEX = 'DEADBEEFCAFEBABE'


def load_result(trace_name):
    path = os.path.join(RESULTS_DIR, f"{trace_name}.json")
    assert os.path.exists(path), f"Result file not found: {path}"
    with open(path) as f:
        return json.load(f)


def compute_expected_sk(ltk_hex, skds_hex, skdm_hex):
    """Independently compute expected session key using AES-128-ECB."""
    from Crypto.Cipher import AES
    ltk = bytes.fromhex(ltk_hex)
    skd = bytes.fromhex(skds_hex) + bytes.fromhex(skdm_hex)
    cipher = AES.new(ltk, AES.MODE_ECB)
    return cipher.encrypt(skd).hex()


# =========================================================================
# Per-trace violation tests
# =========================================================================

class TestTrace01Clean:
    """Trace 01: Normal connection with successful encryption - no violations."""

    def test_result_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "trace_01.json"))

    def test_total_packets(self):
        result = load_result("trace_01")
        assert result["total_packets"] == 11, \
            f"Expected 11 packets, got {result['total_packets']}"

    def test_no_violations(self):
        result = load_result("trace_01")
        assert len(result["violations"]) == 0, \
            f"Expected 0 violations, got {len(result['violations'])}: {result['violations']}"


class TestTrace02OutOfOrder:
    """Trace 02: LL_START_ENC_REQ arrives before LL_ENC_RSP."""

    def test_result_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "trace_02.json"))

    def test_total_packets(self):
        result = load_result("trace_02")
        assert result["total_packets"] == 5

    def test_violation_count(self):
        result = load_result("trace_02")
        assert len(result["violations"]) == 1

    def test_violation_type(self):
        result = load_result("trace_02")
        assert result["violations"][0]["type"] == "OUT_OF_ORDER"

    def test_violation_packet_index(self):
        result = load_result("trace_02")
        assert result["violations"][0]["packet_index"] == 3


class TestTrace03Timeout:
    """Trace 03: Encryption procedure exceeds 40-second timeout."""

    def test_result_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "trace_03.json"))

    def test_total_packets(self):
        result = load_result("trace_03")
        assert result["total_packets"] == 7

    def test_violation_count(self):
        result = load_result("trace_03")
        assert len(result["violations"]) == 1

    def test_violation_type(self):
        result = load_result("trace_03")
        assert result["violations"][0]["type"] == "ENCRYPTION_TIMEOUT"

    def test_violation_packet_index(self):
        result = load_result("trace_03")
        assert result["violations"][0]["packet_index"] == 6


class TestTrace04MultiViolation:
    """Trace 04: Multiple violations."""

    def test_result_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "trace_04.json"))

    def test_total_packets(self):
        result = load_result("trace_04")
        assert result["total_packets"] == 14

    def test_violation_count(self):
        result = load_result("trace_04")
        assert len(result["violations"]) == 3, \
            f"Expected 3, got {len(result['violations'])}: {[v['type'] for v in result['violations']]}"

    def test_has_wrong_initiator(self):
        result = load_result("trace_04")
        types = [v["type"] for v in result["violations"]]
        assert "WRONG_INITIATOR" in types

    def test_has_duplicate_pdu(self):
        result = load_result("trace_04")
        types = [v["type"] for v in result["violations"]]
        assert "DUPLICATE_PDU" in types

    def test_has_termination_during_encryption(self):
        result = load_result("trace_04")
        types = [v["type"] for v in result["violations"]]
        assert "TERMINATION_DURING_ENCRYPTION" in types

    def test_wrong_initiator_packet_index(self):
        result = load_result("trace_04")
        vi = {v["type"]: v["packet_index"] for v in result["violations"]}
        assert vi["WRONG_INITIATOR"] == 2

    def test_duplicate_pdu_packet_index(self):
        result = load_result("trace_04")
        vi = {v["type"]: v["packet_index"] for v in result["violations"]}
        assert vi["DUPLICATE_PDU"] == 8

    def test_termination_packet_index(self):
        result = load_result("trace_04")
        vi = {v["type"]: v["packet_index"] for v in result["violations"]}
        assert vi["TERMINATION_DURING_ENCRYPTION"] == 13


class TestTrace05Clean:
    """Trace 05: Normal encryption (same SKD as trace 01) - no violations."""

    def test_result_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "trace_05.json"))

    def test_total_packets(self):
        result = load_result("trace_05")
        assert result["total_packets"] == 11

    def test_no_violations(self):
        result = load_result("trace_05")
        assert len(result["violations"]) == 0, \
            f"Expected 0 violations, got {len(result['violations'])}"


# =========================================================================
# Output format tests
# =========================================================================

class TestOutputFormat:
    """Verify all result files have required fields."""

    @pytest.mark.parametrize("trace", [
        "trace_01", "trace_02", "trace_03", "trace_04", "trace_05"
    ])
    def test_required_fields(self, trace):
        result = load_result(trace)
        assert "trace_file" in result
        assert "total_packets" in result
        assert "violations" in result
        assert isinstance(result["violations"], list)

    @pytest.mark.parametrize("trace", [
        "trace_01", "trace_02", "trace_03", "trace_04", "trace_05"
    ])
    def test_violation_fields(self, trace):
        result = load_result(trace)
        for v in result["violations"]:
            assert "type" in v, f"Missing 'type': {v}"
            assert "packet_index" in v, f"Missing 'packet_index': {v}"
            assert "description" in v, f"Missing 'description': {v}"
            assert isinstance(v["packet_index"], int)

    @pytest.mark.parametrize("trace", [
        "trace_01", "trace_02", "trace_03", "trace_04", "trace_05"
    ])
    def test_violations_ordered_by_index(self, trace):
        result = load_result(trace)
        indices = [v["packet_index"] for v in result["violations"]]
        assert indices == sorted(indices)


# =========================================================================
# Session key derivation tests
# =========================================================================

class TestSessionKeys:
    """Verify session key derivation via AES-128-ECB."""

    def test_file_exists(self):
        path = os.path.join(RESULTS_DIR, "session_keys.json")
        assert os.path.exists(path), "session_keys.json not found"

    def test_has_trace_01(self):
        with open(os.path.join(RESULTS_DIR, "session_keys.json")) as f:
            sk = json.load(f)
        assert "trace_01" in sk, f"trace_01 missing from session_keys: {list(sk.keys())}"

    def test_has_trace_05(self):
        with open(os.path.join(RESULTS_DIR, "session_keys.json")) as f:
            sk = json.load(f)
        assert "trace_05" in sk, f"trace_05 missing from session_keys: {list(sk.keys())}"

    def test_trace_02_not_present(self):
        with open(os.path.join(RESULTS_DIR, "session_keys.json")) as f:
            sk = json.load(f)
        assert "trace_02" not in sk, \
            "trace_02 should not have a session key (encryption failed)"

    def test_trace_01_key_correct(self):
        expected = compute_expected_sk(LTK_HEX, T01_SKDS_HEX, T01_SKDM_HEX)
        with open(os.path.join(RESULTS_DIR, "session_keys.json")) as f:
            sk = json.load(f)
        assert sk["trace_01"] == expected, \
            f"trace_01 SK mismatch: got {sk['trace_01']}, expected {expected}"

    def test_trace_05_key_correct(self):
        expected = compute_expected_sk(LTK_HEX, T05_SKDS_HEX, T05_SKDM_HEX)
        with open(os.path.join(RESULTS_DIR, "session_keys.json")) as f:
            sk = json.load(f)
        assert sk["trace_05"] == expected, \
            f"trace_05 SK mismatch: got {sk['trace_05']}, expected {expected}"

    def test_skd_reuse_produces_same_key(self):
        """trace_01 and trace_05 have identical SKDm||SKDs => same session key."""
        with open(os.path.join(RESULTS_DIR, "session_keys.json")) as f:
            sk = json.load(f)
        assert sk["trace_01"] == sk["trace_05"], \
            f"SKD reuse should yield identical session keys: {sk['trace_01']} != {sk['trace_05']}"


# =========================================================================
# Cross-layer security audit tests
# =========================================================================

class TestSecurityAudit:
    """Verify cross-layer security findings from HCI+LL correlation."""

    def test_file_exists(self):
        path = os.path.join(RESULTS_DIR, "security_audit.json")
        assert os.path.exists(path), "security_audit.json not found"

    def test_has_findings_key(self):
        with open(os.path.join(RESULTS_DIR, "security_audit.json")) as f:
            audit = json.load(f)
        assert "findings" in audit
        assert isinstance(audit["findings"], list)

    def test_total_finding_count(self):
        with open(os.path.join(RESULTS_DIR, "security_audit.json")) as f:
            audit = json.load(f)
        assert len(audit["findings"]) == 2, \
            f"Expected 2 findings, got {len(audit['findings'])}: " \
            f"{[f['type'] for f in audit['findings']]}"

    def test_key_size_reduction_present(self):
        with open(os.path.join(RESULTS_DIR, "security_audit.json")) as f:
            audit = json.load(f)
        types = [f["type"] for f in audit["findings"]]
        assert "KEY_SIZE_REDUCTION" in types

    def test_key_size_reduction_details(self):
        with open(os.path.join(RESULTS_DIR, "security_audit.json")) as f:
            audit = json.load(f)
        ks_findings = [f for f in audit["findings"] if f["type"] == "KEY_SIZE_REDUCTION"]
        assert len(ks_findings) == 1
        f = ks_findings[0]
        assert f["connection_handle"] == "0x0040", \
            f"Expected handle 0x0040, got {f['connection_handle']}"
        assert f["effective_key_size"] == 7, \
            f"Expected key_size 7, got {f['effective_key_size']}"
        assert f["trace_file"] == "trace_01.bllc", \
            f"Expected trace_01.bllc, got {f['trace_file']}"

    def test_skd_reuse_present(self):
        with open(os.path.join(RESULTS_DIR, "security_audit.json")) as f:
            audit = json.load(f)
        types = [f["type"] for f in audit["findings"]]
        assert "SKD_REUSE" in types

    def test_skd_reuse_details(self):
        with open(os.path.join(RESULTS_DIR, "security_audit.json")) as f:
            audit = json.load(f)
        skd_findings = [f for f in audit["findings"] if f["type"] == "SKD_REUSE"]
        assert len(skd_findings) == 1
        f = skd_findings[0]
        assert "traces" in f
        assert sorted(f["traces"]) == ["trace_01.bllc", "trace_05.bllc"], \
            f"Expected trace_01+trace_05, got {sorted(f['traces'])}"
