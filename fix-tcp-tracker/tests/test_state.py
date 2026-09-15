"""
Tests for TCP Connection State Tracker output.

"""

import json
import os
import subprocess
import pytest

TRACE_PATH = "/app/trace.json"


@pytest.fixture(scope="module")
def trace():
    assert os.path.exists(TRACE_PATH), f"Trace not found at {TRACE_PATH}"
    with open(TRACE_PATH) as f:
        data = json.load(f)
    return data


def find_conn(trace, filename):
    """Find connection(s) by pcap filename."""
    return [c for c in trace["connections"] if c["file"] == filename]


# ============================================================
# Baseline: normal.pcap should work even without fixes
# ============================================================

class TestNormal:
    def test_found(self, trace):
        conns = find_conn(trace, "normal.pcap")
        assert len(conns) == 1

    def test_final_state(self, trace):
        c = find_conn(trace, "normal.pcap")[0]
        assert c["final_state"] == "CLOSED"

    def test_transitions(self, trace):
        c = find_conn(trace, "normal.pcap")[0]
        expected = [
            "SYN_SENT", "SYN_RECEIVED", "ESTABLISHED",
            "FIN_WAIT_1", "FIN_WAIT_2", "TIME_WAIT", "CLOSED",
        ]
        assert c["state_transitions"] == expected

    def test_client_bytes(self, trace):
        c = find_conn(trace, "normal.pcap")[0]
        assert c["client_bytes"] == 500

    def test_server_bytes(self, trace):
        c = find_conn(trace, "normal.pcap")[0]
        assert c["server_bytes"] == 300

    def test_no_retransmissions(self, trace):
        c = find_conn(trace, "normal.pcap")[0]
        assert c["retransmissions"] == 0

    def test_no_wscale(self, trace):
        c = find_conn(trace, "normal.pcap")[0]
        assert c["client_window_scale"] is None
        assert c["server_window_scale"] is None


# ============================================================
# Sequence number wrapping (seqwrap.pcap)
# ============================================================

class TestSeqWrap:
    def test_found(self, trace):
        conns = find_conn(trace, "seqwrap.pcap")
        assert len(conns) == 1

    def test_final_state(self, trace):
        c = find_conn(trace, "seqwrap.pcap")[0]
        assert c["final_state"] == "CLOSED"

    def test_client_bytes(self, trace):
        """5 segments x 512 bytes = 2560. Wrapping bug loses post-wrap segments."""
        c = find_conn(trace, "seqwrap.pcap")[0]
        assert c["client_bytes"] == 2560, (
            f"Expected 2560 client bytes (5x512), got {c['client_bytes']}. "
            "Check sequence number wrapping in comparisons."
        )

    def test_retransmissions(self, trace):
        """Exactly 1 retransmission (the delayed duplicate of Seg1)."""
        c = find_conn(trace, "seqwrap.pcap")[0]
        assert c["retransmissions"] == 1, (
            f"Expected 1 retransmission, got {c['retransmissions']}. "
            "Check sequence number wrapping in retransmission detection."
        )

    def test_server_bytes(self, trace):
        c = find_conn(trace, "seqwrap.pcap")[0]
        assert c["server_bytes"] == 256

    def test_transitions(self, trace):
        c = find_conn(trace, "seqwrap.pcap")[0]
        expected = [
            "SYN_SENT", "SYN_RECEIVED", "ESTABLISHED",
            "FIN_WAIT_1", "FIN_WAIT_2", "TIME_WAIT", "CLOSED",
        ]
        assert c["state_transitions"] == expected


# ============================================================
# Simultaneous close (simclose.pcap)
# ============================================================

class TestSimClose:
    def test_found(self, trace):
        conns = find_conn(trace, "simclose.pcap")
        assert len(conns) == 1

    def test_final_state(self, trace):
        c = find_conn(trace, "simclose.pcap")[0]
        assert c["final_state"] == "CLOSED"

    def test_transitions_include_closing(self, trace):
        """Simultaneous close must pass through CLOSING state."""
        c = find_conn(trace, "simclose.pcap")[0]
        assert "CLOSING" in c["state_transitions"], (
            f"Simultaneous close must pass through CLOSING state. "
            f"Got transitions: {c['state_transitions']}"
        )

    def test_transitions_include_time_wait(self, trace):
        c = find_conn(trace, "simclose.pcap")[0]
        assert "TIME_WAIT" in c["state_transitions"], (
            f"Simultaneous close must pass through TIME_WAIT. "
            f"Got transitions: {c['state_transitions']}"
        )

    def test_full_transition_sequence(self, trace):
        c = find_conn(trace, "simclose.pcap")[0]
        expected = [
            "SYN_SENT", "SYN_RECEIVED", "ESTABLISHED",
            "FIN_WAIT_1", "CLOSING", "TIME_WAIT", "CLOSED",
        ]
        assert c["state_transitions"] == expected, (
            f"Expected {expected}, got {c['state_transitions']}"
        )

    def test_client_bytes(self, trace):
        c = find_conn(trace, "simclose.pcap")[0]
        assert c["client_bytes"] == 200

    def test_no_retransmissions(self, trace):
        c = find_conn(trace, "simclose.pcap")[0]
        assert c["retransmissions"] == 0


# ============================================================
# Half-close data tracking (halfclose.pcap)
# ============================================================

class TestHalfClose:
    def test_found(self, trace):
        conns = find_conn(trace, "halfclose.pcap")
        assert len(conns) == 1

    def test_final_state(self, trace):
        c = find_conn(trace, "halfclose.pcap")[0]
        assert c["final_state"] == "CLOSED"

    def test_server_bytes(self, trace):
        """Server sends 3x200=600 bytes after client FIN (half-close).
        Data must be tracked in FIN_WAIT_2 state."""
        c = find_conn(trace, "halfclose.pcap")[0]
        assert c["server_bytes"] == 600, (
            f"Expected 600 server bytes (3x200 during half-close), "
            f"got {c['server_bytes']}. "
            "Server data must be tracked in FIN_WAIT_2 state."
        )

    def test_client_bytes(self, trace):
        c = find_conn(trace, "halfclose.pcap")[0]
        assert c["client_bytes"] == 100

    def test_transitions(self, trace):
        c = find_conn(trace, "halfclose.pcap")[0]
        expected = [
            "SYN_SENT", "SYN_RECEIVED", "ESTABLISHED",
            "FIN_WAIT_1", "FIN_WAIT_2", "TIME_WAIT", "CLOSED",
        ]
        assert c["state_transitions"] == expected

    def test_no_retransmissions(self, trace):
        c = find_conn(trace, "halfclose.pcap")[0]
        assert c["retransmissions"] == 0


# ============================================================
# Window scaling (wscale.pcap)
# ============================================================

class TestWScale:
    def test_found(self, trace):
        conns = find_conn(trace, "wscale.pcap")
        assert len(conns) == 1

    def test_wscale_factors(self, trace):
        c = find_conn(trace, "wscale.pcap")[0]
        assert c["client_window_scale"] == 7
        assert c["server_window_scale"] == 3

    def test_syn_window_client_unscaled(self, trace):
        """SYN window must NOT be scaled (RFC 7323 section 2.2).
        Raw value is 512."""
        c = find_conn(trace, "wscale.pcap")[0]
        assert c["syn_window_client"] == 512, (
            f"SYN window must be unscaled (512), got {c['syn_window_client']}. "
            "Window scaling must not be applied to SYN packets (RFC 7323)."
        )

    def test_syn_window_server_unscaled(self, trace):
        """SYN-ACK window must NOT be scaled. Raw value is 8192."""
        c = find_conn(trace, "wscale.pcap")[0]
        assert c["syn_window_server"] == 8192, (
            f"SYN-ACK window must be unscaled (8192), "
            f"got {c['syn_window_server']}. "
            "Window scaling must not be applied to SYN-ACK packets (RFC 7323)."
        )

    def test_effective_window_scaled(self, trace):
        """After handshake, windows should be scaled:
        512<<7=65536, 8192<<3=65536."""
        c = find_conn(trace, "wscale.pcap")[0]
        assert c["effective_window_client"] == 65536, (
            f"Post-handshake client window should be 512<<7=65536, "
            f"got {c['effective_window_client']}"
        )
        assert c["effective_window_server"] == 65536, (
            f"Post-handshake server window should be 8192<<3=65536, "
            f"got {c['effective_window_server']}"
        )

    def test_client_bytes(self, trace):
        c = find_conn(trace, "wscale.pcap")[0]
        assert c["client_bytes"] == 100

    def test_server_bytes(self, trace):
        c = find_conn(trace, "wscale.pcap")[0]
        assert c["server_bytes"] == 100

    def test_final_state(self, trace):
        c = find_conn(trace, "wscale.pcap")[0]
        assert c["final_state"] == "CLOSED"


# ============================================================
# Out-of-order segment handling (reorder.pcap)
# ============================================================

class TestReorder:
    def test_pcap_exists(self):
        assert os.path.exists("/app/captures/reorder.pcap"), \
            "reorder.pcap must be generated using scapy"

    def test_found(self, trace):
        conns = find_conn(trace, "reorder.pcap")
        assert len(conns) == 1, "reorder.pcap must contain exactly one TCP connection"

    def test_final_state(self, trace):
        c = find_conn(trace, "reorder.pcap")[0]
        assert c["final_state"] == "CLOSED"

    def test_client_bytes(self, trace):
        """4 segments x 256 bytes = 1024 unique client bytes."""
        c = find_conn(trace, "reorder.pcap")[0]
        assert c["client_bytes"] == 1024, (
            f"Expected 1024 client bytes (4x256), got {c['client_bytes']}. "
            "Out-of-order segments must be counted as new data, not dropped."
        )

    def test_server_bytes(self, trace):
        c = find_conn(trace, "reorder.pcap")[0]
        assert c["server_bytes"] == 128

    def test_retransmissions(self, trace):
        """Only 1 genuine retransmission (duplicate seg1), not out-of-order segments."""
        c = find_conn(trace, "reorder.pcap")[0]
        assert c["retransmissions"] == 1, (
            f"Expected 1 retransmission, got {c['retransmissions']}. "
            "Out-of-order segments must NOT be counted as retransmissions."
        )

    def test_reorder_events_field_exists(self, trace):
        c = find_conn(trace, "reorder.pcap")[0]
        assert "reorder_events" in c, \
            "Tracker must include a 'reorder_events' field in per-connection output"

    def test_reorder_events_count(self, trace):
        """At least 1 reorder event (seg2 arriving after seg3)."""
        c = find_conn(trace, "reorder.pcap")[0]
        assert c["reorder_events"] >= 1, (
            f"Expected at least 1 reorder event, got {c['reorder_events']}. "
            "Gap-filling segments must be tracked as reorder events."
        )

    def test_transitions(self, trace):
        c = find_conn(trace, "reorder.pcap")[0]
        expected = [
            "SYN_SENT", "SYN_RECEIVED", "ESTABLISHED",
            "FIN_WAIT_1", "FIN_WAIT_2", "TIME_WAIT", "CLOSED",
        ]
        assert c["state_transitions"] == expected

    def test_tshark_validates_pcap(self):
        """Verify tshark can parse reorder.pcap and finds expected data segments."""
        result = subprocess.run(
            ["tshark", "-r", "/app/captures/reorder.pcap", "-T", "fields",
             "-e", "tcp.len", "-Y", "tcp.len > 0"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"tshark failed: {result.stderr}"
        lens = [int(line.strip()) for line in result.stdout.strip().split("\n")
                if line.strip()]
        # 4 unique client segments + 1 retransmit + 1 server segment = 6 data packets
        assert len(lens) >= 5, (
            f"Expected at least 5 data segments in reorder.pcap, got {len(lens)}"
        )

    def test_tshark_byte_totals(self):
        """Verify unique byte totals using TCP ACK-based sequence accounting.

        Uses ISN-relative ACK values rather than tcp.analysis.retransmission
        filtering, which misclassifies gap-filling segments as retransmissions
        in reordered traffic (tshark marks a segment as retransmission when
        seq + len <= nextseq, even if it fills a gap left by OOO arrival).
        """
        pcap = "/app/captures/reorder.pcap"

        # Get client endpoint from SYN
        r = subprocess.run(
            ["tshark", "-r", pcap, "-T", "fields",
             "-e", "ip.src", "-e", "tcp.srcport",
             "-Y", "tcp.flags.syn == 1 and tcp.flags.ack == 0", "-c", "1"],
            capture_output=True, text=True
        )
        assert r.returncode == 0, f"tshark failed: {r.stderr}"
        parts = r.stdout.strip().split("\t")
        client_ip, client_port = parts[0], parts[1]

        # Server->Client ACKs (relative seq nums: final ACK = data + 2)
        r = subprocess.run(
            ["tshark", "-r", pcap, "-T", "fields",
             "-e", "tcp.ack",
             "-Y", f"ip.dst == {client_ip} and tcp.dstport == {client_port} "
                   f"and tcp.flags.ack == 1"],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        server_acks = [int(x) for x in r.stdout.strip().split("\n") if x.strip()]

        # Client->Server ACKs
        r = subprocess.run(
            ["tshark", "-r", pcap, "-T", "fields",
             "-e", "tcp.ack",
             "-Y", f"ip.src == {client_ip} and tcp.srcport == {client_port} "
                   f"and tcp.flags.ack == 1"],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        client_acks = [int(x) for x in r.stdout.strip().split("\n") if x.strip()]

        # With relative seq nums: unique_bytes = max_peer_ack - 2
        # (SYN and FIN each consume one sequence number)
        client_bytes = max(server_acks) - 2
        server_bytes = max(client_acks) - 2

        assert client_bytes == 1024, (
            f"tshark ACK accounting shows {client_bytes} client bytes (expected 1024)"
        )
        assert server_bytes == 128, (
            f"tshark ACK accounting shows {server_bytes} server bytes (expected 128)"
        )


# ============================================================
# Cross-validation against tshark
# ============================================================

class TestCrossValidation:
    @pytest.fixture(scope="class")
    def cross_val(self):
        path = "/app/cross_validation.json"
        assert os.path.exists(path), "cross_validation.json must be generated"
        with open(path) as f:
            return json.load(f)

    def test_has_captures_key(self, cross_val):
        assert "captures" in cross_val, "cross_validation.json must have 'captures' key"

    def test_has_all_captures(self, cross_val, trace):
        cv_files = {c["file"] for c in cross_val["captures"]}
        trace_files = {c["file"] for c in trace["connections"]}
        assert trace_files.issubset(cv_files), (
            f"Cross-validation missing captures: {trace_files - cv_files}"
        )

    def test_entry_schema(self, cross_val):
        required = {"file", "tracker_client_bytes", "tracker_server_bytes",
                     "tshark_client_bytes", "tshark_server_bytes", "match"}
        for entry in cross_val["captures"]:
            missing = required - set(entry.keys())
            assert not missing, f"{entry['file']} missing fields: {missing}"

    def test_all_match(self, cross_val):
        for entry in cross_val["captures"]:
            assert entry["match"] is True, (
                f"{entry['file']}: byte mismatch — "
                f"tracker ({entry['tracker_client_bytes']}, "
                f"{entry['tracker_server_bytes']}) vs "
                f"tshark ({entry['tshark_client_bytes']}, "
                f"{entry['tshark_server_bytes']})"
            )

    def test_tracker_values_consistent(self, cross_val, trace):
        """Cross-validation tracker values must match trace.json."""
        for entry in cross_val["captures"]:
            conns = find_conn(trace, entry["file"])
            assert len(conns) >= 1, f"No connection in trace for {entry['file']}"
            c = conns[0]
            assert entry["tracker_client_bytes"] == c["client_bytes"], (
                f"{entry['file']}: cross_val tracker_client_bytes "
                f"({entry['tracker_client_bytes']}) != "
                f"trace.json ({c['client_bytes']})"
            )
            assert entry["tracker_server_bytes"] == c["server_bytes"], (
                f"{entry['file']}: cross_val tracker_server_bytes "
                f"({entry['tracker_server_bytes']}) != "
                f"trace.json ({c['server_bytes']})"
            )

    def test_tshark_spot_check_normal(self, cross_val):
        """Independently verify tshark byte counts for normal.pcap
        using ACK-based sequence accounting."""
        pcap = "/app/captures/normal.pcap"

        # Get client endpoint
        r = subprocess.run(
            ["tshark", "-r", pcap, "-T", "fields",
             "-e", "ip.src", "-e", "tcp.srcport",
             "-Y", "tcp.flags.syn == 1 and tcp.flags.ack == 0", "-c", "1"],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        parts = r.stdout.strip().split("\t")
        client_ip, client_port = parts[0], parts[1]

        # Server->Client ACKs
        r = subprocess.run(
            ["tshark", "-r", pcap, "-T", "fields",
             "-e", "tcp.ack",
             "-Y", f"ip.dst == {client_ip} and tcp.dstport == {client_port} "
                   f"and tcp.flags.ack == 1"],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        server_acks = [int(x) for x in r.stdout.strip().split("\n") if x.strip()]

        # Client->Server ACKs
        r = subprocess.run(
            ["tshark", "-r", pcap, "-T", "fields",
             "-e", "tcp.ack",
             "-Y", f"ip.src == {client_ip} and tcp.srcport == {client_port} "
                   f"and tcp.flags.ack == 1"],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        client_acks = [int(x) for x in r.stdout.strip().split("\n") if x.strip()]

        client_bytes = max(server_acks) - 2
        server_bytes = max(client_acks) - 2

        entry = next(e for e in cross_val["captures"] if e["file"] == "normal.pcap")
        assert entry["tshark_client_bytes"] == client_bytes, (
            f"Spot check failed: tshark gives {client_bytes} client bytes, "
            f"cross_validation has {entry['tshark_client_bytes']}"
        )
        assert entry["tshark_server_bytes"] == server_bytes, (
            f"Spot check failed: tshark gives {server_bytes} server bytes, "
            f"cross_validation has {entry['tshark_server_bytes']}"
        )

    def test_tshark_spot_check_seqwrap(self, cross_val):
        """Independently verify tshark byte counts for seqwrap.pcap
        using ACK-based sequence accounting (handles wrapping correctly)."""
        pcap = "/app/captures/seqwrap.pcap"

        # Get client endpoint
        r = subprocess.run(
            ["tshark", "-r", pcap, "-T", "fields",
             "-e", "ip.src", "-e", "tcp.srcport",
             "-Y", "tcp.flags.syn == 1 and tcp.flags.ack == 0", "-c", "1"],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        parts = r.stdout.strip().split("\t")
        client_ip, client_port = parts[0], parts[1]

        # Server->Client ACKs
        r = subprocess.run(
            ["tshark", "-r", pcap, "-T", "fields",
             "-e", "tcp.ack",
             "-Y", f"ip.dst == {client_ip} and tcp.dstport == {client_port} "
                   f"and tcp.flags.ack == 1"],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        server_acks = [int(x) for x in r.stdout.strip().split("\n") if x.strip()]

        # Client->Server ACKs
        r = subprocess.run(
            ["tshark", "-r", pcap, "-T", "fields",
             "-e", "tcp.ack",
             "-Y", f"ip.src == {client_ip} and tcp.srcport == {client_port} "
                   f"and tcp.flags.ack == 1"],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        client_acks = [int(x) for x in r.stdout.strip().split("\n") if x.strip()]

        client_bytes = max(server_acks) - 2
        server_bytes = max(client_acks) - 2

        entry = next(e for e in cross_val["captures"] if e["file"] == "seqwrap.pcap")
        assert entry["tshark_client_bytes"] == client_bytes, (
            f"Spot check failed: tshark gives {client_bytes} client bytes, "
            f"cross_validation has {entry['tshark_client_bytes']}"
        )
        assert entry["tshark_server_bytes"] == server_bytes


# ============================================================
# Cross-connection validation
# ============================================================

class TestGlobal:
    def test_total_connections(self, trace):
        assert len(trace["connections"]) == 6, (
            f"Expected 6 connections (one per pcap including reorder.pcap), "
            f"got {len(trace['connections'])}"
        )

    def test_all_closed(self, trace):
        for c in trace["connections"]:
            assert c["final_state"] == "CLOSED", (
                f"{c['file']} final state is {c['final_state']}, "
                "expected CLOSED"
            )

    def test_no_anomalies_in_normal(self, trace):
        c = find_conn(trace, "normal.pcap")[0]
        assert len(c["anomalies"]) == 0
