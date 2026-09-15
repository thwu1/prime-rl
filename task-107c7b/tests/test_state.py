"""
Tests for TCP-AO security audit report.

Validates that /app/audit_report.json correctly evaluates all candidate
implementations against RFC 9235 test vectors.

"""

import json
import os
import pytest


# RFC 9235 published traffic keys for client SYN (dst_ISN=0)
EXPECTED_TRAFFIC_KEYS = {
    "4.1": "6d63ef1b02fe1509d4b1402707fd7b0416abb74f",
    "5.1": "f5b8b3d5f34fdbb6eb8d4ab9660e60e3",
    "6.1": "625ec09d575836edc9b6428418bbf06989a361bb",
    "7.1": "fa5a2108882d39d0c71929175ab1b7b8",
}

# MACs embedded in the pcap packets (from RFC 9235 test vectors)
EXPECTED_MACS = {
    "4.1": "2ee437c6f8ede6d7c4d602e7",
    "4.2": "80af3cfeb85368937b8f9ec2",
    "5.1": "e477e99c8040765498e55091",
    "5.2": "c44e60cb31f7c0b1de3d2749",
    "6.1": "9033ec3d7334b64c5edd039f",
    "6.2": "885698b0530ed4d5a15f8346",
    "7.1": "59b588107481ac6dc3927040",
    "7.2": "3d45b4342de8bb1530847898",
}

ALL_CONN_IDS = {"4.1", "4.2", "5.1", "5.2", "6.1", "6.2", "7.1", "7.2"}
AES_CONN_IDS = {"5.1", "5.2", "7.1", "7.2"}


@pytest.fixture
def report():
    path = '/app/audit_report.json'
    assert os.path.exists(path), "audit_report.json not found at /app/"
    with open(path) as f:
        return json.load(f)


# ======================================================================
# Structure tests
# ======================================================================
class TestStructure:

    def test_top_level_keys(self, report):
        required = {"candidates", "reference_values", "pcap_analysis",
                     "recommendation"}
        assert required.issubset(report.keys()), \
            f"Missing top-level keys: {required - set(report.keys())}"

    def test_all_candidates_present(self, report):
        required = {"impl_a", "impl_b", "impl_c", "impl_d"}
        actual = set(report["candidates"].keys())
        assert required == actual, \
            f"Expected candidates {required}, got {actual}"

    def test_candidate_fields(self, report):
        required = {"verdict", "failing_connections", "bug_description",
                     "rfc_violation", "severity"}
        for name, info in report["candidates"].items():
            missing = required - set(info.keys())
            assert not missing, \
                f"Candidate {name} missing fields: {missing}"

    def test_reference_values_fields(self, report):
        rv = report["reference_values"]
        assert "method" in rv, "reference_values missing 'method'"
        assert "openssl_commands" in rv, \
            "reference_values missing 'openssl_commands'"
        assert "traffic_keys" in rv, \
            "reference_values missing 'traffic_keys'"

    def test_pcap_analysis_fields(self, report):
        pa = report["pcap_analysis"]
        assert "method" in pa, "pcap_analysis missing 'method'"
        assert "tshark_command" in pa, \
            "pcap_analysis missing 'tshark_command'"
        assert "packets" in pa, "pcap_analysis missing 'packets'"


# ======================================================================
# Candidate verdict tests
# ======================================================================
class TestCandidateVerdicts:

    def test_impl_a_passes(self, report):
        assert report["candidates"]["impl_a"]["verdict"] == "pass"

    def test_impl_a_no_failures(self, report):
        fc = report["candidates"]["impl_a"]["failing_connections"]
        assert len(fc) == 0, f"impl_a should have no failures, got {fc}"

    def test_impl_a_severity_none(self, report):
        assert report["candidates"]["impl_a"]["severity"] == "none"

    def test_impl_b_fails(self, report):
        assert report["candidates"]["impl_b"]["verdict"] == "fail"

    def test_impl_b_fails_all_connections(self, report):
        failing = set(report["candidates"]["impl_b"]["failing_connections"])
        assert failing == ALL_CONN_IDS, \
            f"impl_b should fail all connections, got {failing}"

    def test_impl_b_severity_critical(self, report):
        assert report["candidates"]["impl_b"]["severity"] == "critical"

    def test_impl_c_fails(self, report):
        assert report["candidates"]["impl_c"]["verdict"] == "fail"

    def test_impl_c_fails_all_connections(self, report):
        failing = set(report["candidates"]["impl_c"]["failing_connections"])
        assert failing == ALL_CONN_IDS, \
            f"impl_c should fail all connections, got {failing}"

    def test_impl_c_severity_critical(self, report):
        assert report["candidates"]["impl_c"]["severity"] == "critical"

    def test_impl_d_fails(self, report):
        assert report["candidates"]["impl_d"]["verdict"] == "fail"

    def test_impl_d_fails_only_aes_connections(self, report):
        failing = set(report["candidates"]["impl_d"]["failing_connections"])
        assert failing == AES_CONN_IDS, \
            f"impl_d should fail only AES connections {AES_CONN_IDS}, " \
            f"got {failing}"

    def test_impl_d_severity_high(self, report):
        assert report["candidates"]["impl_d"]["severity"] == "high"


# ======================================================================
# Reference values tests (openssl-computed traffic keys)
# ======================================================================
class TestReferenceValues:

    def test_method_is_openssl(self, report):
        assert report["reference_values"]["method"] == "openssl"

    def test_openssl_commands_nonempty(self, report):
        cmds = report["reference_values"]["openssl_commands"]
        assert isinstance(cmds, list) and len(cmds) >= 2, \
            "openssl_commands should contain at least 2 commands"

    def test_openssl_commands_contain_openssl(self, report):
        for cmd in report["reference_values"]["openssl_commands"]:
            assert "openssl" in cmd.lower(), \
                f"Command does not reference openssl: {cmd}"

    def test_traffic_key_41(self, report):
        keys = report["reference_values"]["traffic_keys"]
        assert keys.get("4.1") == EXPECTED_TRAFFIC_KEYS["4.1"], \
            f"4.1 key mismatch: {keys.get('4.1')}"

    def test_traffic_key_51(self, report):
        keys = report["reference_values"]["traffic_keys"]
        assert keys.get("5.1") == EXPECTED_TRAFFIC_KEYS["5.1"], \
            f"5.1 key mismatch: {keys.get('5.1')}"

    def test_traffic_key_61(self, report):
        keys = report["reference_values"]["traffic_keys"]
        assert keys.get("6.1") == EXPECTED_TRAFFIC_KEYS["6.1"], \
            f"6.1 key mismatch: {keys.get('6.1')}"

    def test_traffic_key_71(self, report):
        keys = report["reference_values"]["traffic_keys"]
        assert keys.get("7.1") == EXPECTED_TRAFFIC_KEYS["7.1"], \
            f"7.1 key mismatch: {keys.get('7.1')}"

    def test_all_eight_keys_present(self, report):
        keys = report["reference_values"]["traffic_keys"]
        present = set(keys.keys())
        assert ALL_CONN_IDS.issubset(present), \
            f"Missing keys for connections: {ALL_CONN_IDS - present}"


# ======================================================================
# pcap analysis tests (extracted fields)
# ======================================================================
class TestPcapAnalysis:

    def test_method_is_tshark(self, report):
        assert report["pcap_analysis"]["method"] == "tshark"

    def test_tshark_command_references_tool(self, report):
        cmd = report["pcap_analysis"]["tshark_command"]
        assert "tshark" in cmd, "tshark_command should reference tshark"

    def test_tshark_command_references_pcap(self, report):
        cmd = report["pcap_analysis"]["tshark_command"]
        assert "bgp_capture.pcap" in cmd, \
            "tshark_command should reference bgp_capture.pcap"

    def test_packet_count(self, report):
        pkts = report["pcap_analysis"]["packets"]
        assert len(pkts) == 8, f"Expected 8 packets, got {len(pkts)}"

    def test_all_connections_mapped(self, report):
        conn_ids = {p["connection_id"]
                    for p in report["pcap_analysis"]["packets"]}
        assert conn_ids == ALL_CONN_IDS, \
            f"Expected connections {ALL_CONN_IDS}, got {conn_ids}"

    def test_packet_fields_present(self, report):
        required = {"frame", "connection_id", "src_ip", "dst_ip",
                     "src_port", "dst_port", "ao_keyid",
                     "ao_rnextkeyid", "ao_mac"}
        for pkt in report["pcap_analysis"]["packets"]:
            missing = required - set(pkt.keys())
            assert not missing, \
                f"Packet frame {pkt.get('frame')} missing: {missing}"

    def test_ao_keyid_values(self, report):
        for pkt in report["pcap_analysis"]["packets"]:
            assert pkt["ao_keyid"] == 61, \
                f"Frame {pkt['frame']}: expected KeyID 61, " \
                f"got {pkt['ao_keyid']}"

    def test_ao_rnextkeyid_values(self, report):
        for pkt in report["pcap_analysis"]["packets"]:
            assert pkt["ao_rnextkeyid"] == 84, \
                f"Frame {pkt['frame']}: expected RNextKeyID 84, " \
                f"got {pkt['ao_rnextkeyid']}"

    def test_mac_41(self, report):
        pkt = next(p for p in report["pcap_analysis"]["packets"]
                   if p["connection_id"] == "4.1")
        assert pkt["ao_mac"] == EXPECTED_MACS["4.1"], \
            f"4.1 MAC: {pkt['ao_mac']}"

    def test_mac_51(self, report):
        pkt = next(p for p in report["pcap_analysis"]["packets"]
                   if p["connection_id"] == "5.1")
        assert pkt["ao_mac"] == EXPECTED_MACS["5.1"], \
            f"5.1 MAC: {pkt['ao_mac']}"

    def test_mac_61(self, report):
        pkt = next(p for p in report["pcap_analysis"]["packets"]
                   if p["connection_id"] == "6.1")
        assert pkt["ao_mac"] == EXPECTED_MACS["6.1"], \
            f"6.1 MAC: {pkt['ao_mac']}"

    def test_mac_71(self, report):
        pkt = next(p for p in report["pcap_analysis"]["packets"]
                   if p["connection_id"] == "7.1")
        assert pkt["ao_mac"] == EXPECTED_MACS["7.1"], \
            f"7.1 MAC: {pkt['ao_mac']}"

    def test_mac_72(self, report):
        pkt = next(p for p in report["pcap_analysis"]["packets"]
                   if p["connection_id"] == "7.2")
        assert pkt["ao_mac"] == EXPECTED_MACS["7.2"], \
            f"7.2 MAC: {pkt['ao_mac']}"


# ======================================================================
# Recommendation test
# ======================================================================
class TestRecommendation:

    def test_recommendation_is_impl_a(self, report):
        assert report["recommendation"] == "impl_a"


# ======================================================================
# Anti-hardcoding / consistency tests
# ======================================================================
class TestAntiHardcoding:

    def test_traffic_keys_all_unique(self, report):
        keys = report["reference_values"]["traffic_keys"]
        vals = list(keys.values())
        assert len(set(vals)) == len(vals), \
            "All traffic keys should be distinct"

    def test_macs_all_unique(self, report):
        macs = [p["ao_mac"] for p in report["pcap_analysis"]["packets"]]
        assert len(set(macs)) == len(macs), \
            "All MAC values should be distinct"

    def test_impl_b_and_d_differ(self, report):
        b_fail = set(
            report["candidates"]["impl_b"]["failing_connections"])
        d_fail = set(
            report["candidates"]["impl_d"]["failing_connections"])
        assert b_fail != d_fail, \
            "impl_b and impl_d should fail different connection sets"

    def test_bug_descriptions_nonempty(self, report):
        for name in ["impl_b", "impl_c", "impl_d"]:
            desc = report["candidates"][name]["bug_description"]
            assert len(desc) > 10, \
                f"{name} bug_description too short: '{desc}'"

    def test_rfc_violations_nonempty_for_failures(self, report):
        for name in ["impl_b", "impl_c", "impl_d"]:
            ref = report["candidates"][name]["rfc_violation"]
            assert len(ref) > 3 and ref != "none", \
                f"{name} should cite an RFC violation: '{ref}'"
