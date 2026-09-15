
"""Tests for QUIC Connection Forensics task.

Verifies the forensic report produced from pcap, qlog, transport
parameter, and certificate artifacts.
"""

import json
import os

import pytest

RESULTS_PATH = "/app/report.json"


@pytest.fixture(scope="session", autouse=True)
def ensure_results():
    """Try to run the analyzer if report.json does not exist."""
    if not os.path.exists(RESULTS_PATH):
        import subprocess
        for script in [
            "/app/quic_analyzer.py", "/app/analyzer.py",
            "/app/solve.py", "/app/main.py",
        ]:
            if os.path.exists(script):
                subprocess.run(
                    ["python3", script], cwd="/app", timeout=120, check=False
                )
                break


@pytest.fixture
def results():
    """Load report.json."""
    assert os.path.exists(RESULTS_PATH), \
        "report.json not found at /app/report.json"
    with open(RESULTS_PATH) as f:
        return json.load(f)


# -------------------------------------------------------------------
# pcap_summary — values derived from packet capture analysis
# -------------------------------------------------------------------

class TestPcapSummary:
    def test_total_packets(self, results):
        assert results["pcap_summary"]["total_packets"] == 4

    def test_client_ip(self, results):
        assert results["pcap_summary"]["client_ip"] == "10.0.0.1"

    def test_server_ip(self, results):
        assert results["pcap_summary"]["server_ip"] == "10.0.0.2"

    def test_server_port(self, results):
        assert results["pcap_summary"]["server_port"] == 443

    def test_quic_version_1_present(self, results):
        versions = results["pcap_summary"]["quic_versions"]
        int_versions = []
        for v in versions:
            if isinstance(v, int):
                int_versions.append(v)
            elif isinstance(v, str):
                int_versions.append(int(v, 0))
        assert 1 in int_versions, "QUIC v1 not found in versions"

    def test_quic_version_0_present(self, results):
        """Version Negotiation packets carry version 0."""
        versions = results["pcap_summary"]["quic_versions"]
        int_versions = []
        for v in versions:
            if isinstance(v, int):
                int_versions.append(v)
            elif isinstance(v, str):
                int_versions.append(int(v, 0))
        assert 0 in int_versions, "Version 0 (VN) not found"

    def test_has_initial(self, results):
        types = [t.lower().replace('_', '').replace('-', '').replace(' ', '')
                 for t in results["pcap_summary"]["packet_types"]]
        assert "initial" in types

    def test_has_handshake(self, results):
        types = [t.lower().replace('_', '').replace('-', '').replace(' ', '')
                 for t in results["pcap_summary"]["packet_types"]]
        assert "handshake" in types

    def test_has_zerortt(self, results):
        types = [t.lower().replace('_', '').replace('-', '').replace(' ', '')
                 for t in results["pcap_summary"]["packet_types"]]
        assert any(t in types for t in
                   ['0rtt', 'zerortt', '0rtt']), \
            f"0-RTT not found in {results['pcap_summary']['packet_types']}"

    def test_has_version_negotiation(self, results):
        types = [t.lower().replace('_', '').replace('-', '').replace(' ', '')
                 for t in results["pcap_summary"]["packet_types"]]
        assert any(t in types for t in
                   ['versionnegotiation', 'versionnego']), \
            f"VersionNegotiation not found in {results['pcap_summary']['packet_types']}"


# -------------------------------------------------------------------
# certificate — values derived from TLS certificate inspection
# -------------------------------------------------------------------

class TestCertificate:
    def test_subject_cn(self, results):
        assert results["certificate"]["subject_cn"] == \
               "quic-test.example.com"

    def test_issuer_cn(self, results):
        assert results["certificate"]["issuer_cn"] == \
               "quic-test.example.com"

    def test_is_self_signed(self, results):
        assert results["certificate"]["is_self_signed"] is True

    def test_serial_hex(self, results):
        serial = results["certificate"]["serial_hex"].lower()
        assert "1234abcd" in serial, \
            f"Expected serial containing 1234abcd, got {serial}"

    def test_san_primary(self, results):
        san = results["certificate"]["san_dns"]
        assert "quic-test.example.com" in san

    def test_san_wildcard(self, results):
        san = results["certificate"]["san_dns"]
        assert "*.example.com" in san

    def test_key_type(self, results):
        kt = results["certificate"]["key_type"].upper()
        assert "EC" in kt, f"Expected EC key type, got {kt}"


# -------------------------------------------------------------------
# Server transport parameter decoding
# -------------------------------------------------------------------

class TestServerTransportParams:
    def test_original_dcid(self, results):
        tp = results["transport_params"]["server"]
        assert tp["original_destination_connection_id"] == \
               "8394c8f03e515708"

    def test_max_idle_timeout(self, results):
        tp = results["transport_params"]["server"]
        assert tp["max_idle_timeout"] == 30000

    def test_stateless_reset_token(self, results):
        tp = results["transport_params"]["server"]
        assert tp["stateless_reset_token"] == \
               "0123456789abcdef0123456789abcdef"

    def test_max_udp_payload_size(self, results):
        tp = results["transport_params"]["server"]
        assert tp["max_udp_payload_size"] == 1472

    def test_initial_max_data(self, results):
        tp = results["transport_params"]["server"]
        assert tp["initial_max_data"] == 10485760

    def test_initial_max_stream_data_bidi_local(self, results):
        tp = results["transport_params"]["server"]
        assert tp["initial_max_stream_data_bidi_local"] == 262144

    def test_initial_max_stream_data_bidi_remote(self, results):
        tp = results["transport_params"]["server"]
        assert tp["initial_max_stream_data_bidi_remote"] == 262144

    def test_initial_max_stream_data_uni(self, results):
        tp = results["transport_params"]["server"]
        assert tp["initial_max_stream_data_uni"] == 262144

    def test_initial_max_streams_bidi(self, results):
        tp = results["transport_params"]["server"]
        assert tp["initial_max_streams_bidi"] == 100

    def test_initial_max_streams_uni(self, results):
        tp = results["transport_params"]["server"]
        assert tp["initial_max_streams_uni"] == 3

    def test_ack_delay_exponent(self, results):
        tp = results["transport_params"]["server"]
        assert tp["ack_delay_exponent"] == 3

    def test_max_ack_delay(self, results):
        tp = results["transport_params"]["server"]
        assert tp["max_ack_delay"] == 25

    def test_disable_active_migration(self, results):
        tp = results["transport_params"]["server"]
        assert tp["disable_active_migration"] is True

    def test_active_connection_id_limit(self, results):
        tp = results["transport_params"]["server"]
        assert tp["active_connection_id_limit"] == 2

    def test_initial_source_connection_id(self, results):
        tp = results["transport_params"]["server"]
        assert tp["initial_source_connection_id"] == "a1b2c3d4e5f6a7b8"


# -------------------------------------------------------------------
# Client transport parameter decoding
# -------------------------------------------------------------------

class TestClientTransportParams:
    def test_max_idle_timeout(self, results):
        tp = results["transport_params"]["client"]
        assert tp["max_idle_timeout"] == 60000

    def test_max_udp_payload_size(self, results):
        tp = results["transport_params"]["client"]
        assert tp["max_udp_payload_size"] == 1472

    def test_initial_max_data(self, results):
        tp = results["transport_params"]["client"]
        assert tp["initial_max_data"] == 15728640

    def test_initial_max_stream_data_bidi_local(self, results):
        tp = results["transport_params"]["client"]
        assert tp["initial_max_stream_data_bidi_local"] == 524288

    def test_initial_max_stream_data_bidi_remote(self, results):
        tp = results["transport_params"]["client"]
        assert tp["initial_max_stream_data_bidi_remote"] == 524288

    def test_initial_max_stream_data_uni(self, results):
        tp = results["transport_params"]["client"]
        assert tp["initial_max_stream_data_uni"] == 524288

    def test_initial_max_streams_bidi(self, results):
        tp = results["transport_params"]["client"]
        assert tp["initial_max_streams_bidi"] == 200

    def test_initial_max_streams_uni(self, results):
        tp = results["transport_params"]["client"]
        assert tp["initial_max_streams_uni"] == 50

    def test_ack_delay_exponent(self, results):
        tp = results["transport_params"]["client"]
        assert tp["ack_delay_exponent"] == 3

    def test_max_ack_delay_raw(self, results):
        tp = results["transport_params"]["client"]
        assert tp["max_ack_delay"] == 16384

    def test_active_connection_id_limit(self, results):
        tp = results["transport_params"]["client"]
        assert tp["active_connection_id_limit"] == 4

    def test_initial_source_connection_id(self, results):
        tp = results["transport_params"]["client"]
        assert tp["initial_source_connection_id"] == "f067a5502a4262b5"


# -------------------------------------------------------------------
# RFC compliance violation detection
# -------------------------------------------------------------------

class TestViolations:
    def test_violations_not_empty(self, results):
        assert len(results["violations"]) > 0

    def test_max_ack_delay_violation(self, results):
        found = False
        for v in results["violations"]:
            if v.get("source") == "client" and \
               "max_ack_delay" in v.get("parameter", ""):
                found = True
                assert v["value"] == 16384
                reason = v.get("reason", "").lower()
                assert any(kw in reason for kw in
                           ["2^14", "16384", "invalid", "violation",
                            "greater", "exceed"]), \
                    f"Reason not informative: {v.get('reason')}"
        assert found, "max_ack_delay violation not detected"


# -------------------------------------------------------------------
# Negotiated connection parameters
# -------------------------------------------------------------------

class TestNegotiated:
    def test_effective_idle_timeout(self, results):
        assert results["negotiated"]["effective_idle_timeout_ms"] == 30000

    def test_client_initiated_max_bidi_streams(self, results):
        assert results["negotiated"][
            "client_initiated_max_bidi_streams"] == 100

    def test_server_initiated_max_bidi_streams(self, results):
        assert results["negotiated"][
            "server_initiated_max_bidi_streams"] == 200

    def test_client_to_server_max_data(self, results):
        assert results["negotiated"][
            "client_to_server_max_data"] == 10485760

    def test_server_to_client_max_data(self, results):
        assert results["negotiated"][
            "server_to_client_max_data"] == 15728640


# -------------------------------------------------------------------
# qlog analysis
# -------------------------------------------------------------------

class TestQlogAnalysis:
    def test_server_event_count(self, results):
        assert results["qlog_analysis"]["server_event_count"] == 7

    def test_client_event_count(self, results):
        assert results["qlog_analysis"]["client_event_count"] == 8

    def test_handshake_not_completed(self, results):
        assert results["qlog_analysis"]["handshake_completed"] is False

    def test_connection_error(self, results):
        err = results["qlog_analysis"]["connection_error"].lower()
        assert "transport_parameter" in err, \
            f"Expected TRANSPORT_PARAMETER_ERROR, got: {err}"

    def test_server_min_rtt(self, results):
        assert abs(results["qlog_analysis"]["server_min_rtt_ms"] - 0.5) \
               < 0.01
