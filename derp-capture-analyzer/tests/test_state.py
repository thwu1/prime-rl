#!/usr/bin/env python3

"""Tests for the DERP Mesh Relay Forensics tool."""

import json
import os
import shutil
import sqlite3
import struct
import subprocess
import tempfile

import pytest

TOOL = "/app/mesh_forensics"
DPCAP_MAGIC = b"DPCAP\x01"
DERP_MAGIC = b"DERP\xf0\x9f\x94\x91"

DIR_S2C = 0x00  # server to client
DIR_C2S = 0x01  # client to server

# Deterministic test keys
SERVER_KEY = bytes(range(1, 33))  # 0x01..0x20
CLIENT_KEY = bytes(range(33, 65))  # 0x21..0x40
DEST_KEY_A = bytes(range(65, 97))  # 0x41..0x60
DEST_KEY_B = bytes(range(97, 129))  # 0x61..0x80
SRC_KEY_C = bytes(range(129, 161))  # 0x81..0xa0
SRC_KEY_D = bytes(range(161, 193))  # 0xa1..0xc0


def make_frame(frame_type, body):
    """Create a raw DERP frame (header + body)."""
    return struct.pack("!BI", frame_type, len(body)) + body


def make_record(timestamp_us, direction, frame_type, body):
    """Create a DPCAP record: timestamp + direction + frame."""
    frame = make_frame(frame_type, body)
    return struct.pack("!QB", timestamp_us, direction) + frame


def make_server_key_body(key=SERVER_KEY):
    """Create ServerKey frame body: 8B magic + 32B key."""
    return DERP_MAGIC + key


def make_client_info_body(key=CLIENT_KEY, nonce=None, encrypted=None):
    """Create ClientInfo frame body: 32B key + 24B nonce + encrypted."""
    if nonce is None:
        nonce = b"\x00" * 24
    if encrypted is None:
        encrypted = b'{"version":2}'
    return key + nonce + encrypted


def make_server_info_body(nonce=None, encrypted=None):
    """Create ServerInfo frame body: 24B nonce + encrypted."""
    if nonce is None:
        nonce = b"\x00" * 24
    if encrypted is None:
        encrypted = b'{"version":2}'
    return nonce + encrypted


def make_send_packet_body(dest_key, data=b"payload"):
    """Create SendPacket frame body: 32B dest key + data."""
    return dest_key + data


def make_recv_packet_body(src_key, data=b"payload"):
    """Create RecvPacket frame body: 32B src key + data."""
    return src_key + data


def make_forward_packet_body(src_key, dst_key, data=b"payload"):
    """Create ForwardPacket frame body: 32B src + 32B dst + data."""
    return src_key + dst_key + data


def make_peer_present_body(peer_key):
    """Create PeerPresent frame body: 32B key + 16B IP + 2B port + 1B flags."""
    ip_bytes = b"\x0a\x00\x01\x02" + b"\x00" * 12
    port_bytes = struct.pack("!H", 41641)
    flags_byte = b"\x01"
    return peer_key + ip_bytes + port_bytes + flags_byte


def make_peer_gone_body(peer_key, reason=0):
    """Create PeerGone frame body: 32B key + 1B reason."""
    return peer_key + struct.pack("B", reason)


def write_capture(records):
    """Write records to a temp DPCAP file, return path."""
    fd, path = tempfile.mkstemp(suffix=".dpcap")
    with os.fdopen(fd, "wb") as f:
        f.write(DPCAP_MAGIC)
        for rec in records:
            f.write(rec)
    return path


def write_capture_to(records, path):
    """Write records to a DPCAP file at the given path."""
    with open(path, "wb") as f:
        f.write(DPCAP_MAGIC)
        for rec in records:
            f.write(rec)


def valid_handshake_records(start_ts=1000000, nonce=None):
    """Create a standard valid handshake as 3 records."""
    return [
        make_record(start_ts, DIR_S2C, 0x01, make_server_key_body()),
        make_record(start_ts + 100000, DIR_C2S, 0x02, make_client_info_body(nonce=nonce)),
        make_record(start_ts + 200000, DIR_S2C, 0x03, make_server_info_body()),
    ]


def run_analyzer(capture_path):
    """Run the tool in single-file mode and return parsed JSON output."""
    result = subprocess.run(
        [TOOL, capture_path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Tool failed: stderr={result.stderr}"
    return json.loads(result.stdout)


def run_pcap_analyzer(pcap_path):
    """Run the tool in pcap mode and return parsed JSON output."""
    result = subprocess.run(
        [TOOL, "--pcap", pcap_path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Tool pcap mode failed: stderr={result.stderr}"
    return json.loads(result.stdout)


def run_dir_analyzer(dir_path, db_path=None):
    """Run the tool in directory mode and return parsed JSON output."""
    cmd = [TOOL, "--dir", dir_path]
    if db_path:
        cmd.extend(["--db", db_path])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"Tool dir mode failed: stderr={result.stderr}"
    return json.loads(result.stdout)


def create_pcap_with_tcp_payload(payload):
    """Create a minimal pcap file with DERP frames as TCP payload.
    Uses LINKTYPE_ETHERNET (1) with minimal IPv4 + TCP headers."""
    # Ethernet header (14 bytes): dst MAC + src MAC + EtherType IPv4
    eth_hdr = b"\x00" * 6 + b"\x00" * 6 + struct.pack("!H", 0x0800)

    # TCP header (20 bytes, minimal, no options)
    tcp_hdr = struct.pack("!HHIIHHHH",
        12345, 443, 1, 1,
        (5 << 12) | 0x018, 65535, 0, 0)

    # IPv4 header (20 bytes, no options)
    total_len = 20 + 20 + len(payload)
    ip_hdr = struct.pack("!BBHHHBBH4s4s",
        0x45, 0, total_len, 0, 0x4000,
        64, 6, 0,
        b"\x0a\x00\x00\x01", b"\x0a\x00\x00\x02")

    packet = eth_hdr + ip_hdr + tcp_hdr + payload

    # PCAP global header (24 bytes) - LINKTYPE_ETHERNET = 1
    pcap = struct.pack("<IHHiIII",
        0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)

    # Packet record header (16 bytes)
    pcap += struct.pack("<IIII",
        1000, 0, len(packet), len(packet))
    pcap += packet

    return pcap


def create_test_db(db_path, relays=None, policies=None, blocklist=None):
    """Create a SQLite database with relay metadata for testing."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS relays (
        relay_id TEXT PRIMARY KEY,
        region TEXT NOT NULL,
        fqdn TEXT NOT NULL,
        capacity_peers INTEGER NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS peer_policies (
        peer_key_hex TEXT PRIMARY KEY,
        owner TEXT NOT NULL,
        allowed_relay_ids TEXT NOT NULL,
        allowed_dest_keys TEXT,
        max_session_count INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS blocklist (
        peer_key_hex TEXT PRIMARY KEY,
        reason TEXT NOT NULL,
        added_at TEXT NOT NULL
    )""")
    if relays:
        for r in relays:
            c.execute("INSERT INTO relays VALUES (?, ?, ?, ?)", r)
    if policies:
        for p in policies:
            c.execute("INSERT INTO peer_policies VALUES (?, ?, ?, ?, ?)", p)
    if blocklist:
        for b in blocklist:
            c.execute("INSERT INTO blocklist VALUES (?, ?, ?)", b)
    conn.commit()
    conn.close()


# ===========================================================================
# Single-file DPCAP tests
# ===========================================================================


class TestBasicSession:
    """Test a valid basic DERP session with handshake and data."""

    def test_valid_handshake_and_data(self):
        records = valid_handshake_records()
        records.append(make_record(2000000, DIR_S2C, 0x06, b""))  # KeepAlive
        records.append(make_record(3000000, DIR_C2S, 0x04, make_send_packet_body(DEST_KEY_A)))
        records.append(make_record(4000000, DIR_S2C, 0x05, make_recv_packet_body(SRC_KEY_C)))
        records.append(make_record(5000000, DIR_S2C, 0x12, b"\x01\x02\x03\x04\x05\x06\x07\x08"))
        records.append(make_record(5100000, DIR_C2S, 0x13, b"\x01\x02\x03\x04\x05\x06\x07\x08"))

        path = write_capture(records)
        try:
            out = run_analyzer(path)

            assert out["session"]["total_frames"] == 8
            assert out["session"]["start_time_us"] == 1000000
            assert out["session"]["end_time_us"] == 5100000
            assert out["session"]["duration_us"] == 4100000

            assert out["handshake"]["valid"] is True
            assert out["handshake"]["server_key"] == SERVER_KEY.hex()
            assert out["handshake"]["client_key"] == CLIENT_KEY.hex()
            assert out["handshake"]["violations"] == []

            assert out["frame_counts"]["ServerKey"] == 1
            assert out["frame_counts"]["ClientInfo"] == 1
            assert out["frame_counts"]["ServerInfo"] == 1
            assert out["frame_counts"]["KeepAlive"] == 1
            assert out["frame_counts"]["SendPacket"] == 1
            assert out["frame_counts"]["RecvPacket"] == 1
            assert out["frame_counts"]["Ping"] == 1
            assert out["frame_counts"]["Pong"] == 1

            assert out["routing"]["send_packets"][DEST_KEY_A.hex()] == 1
            assert out["routing"]["recv_packets"][SRC_KEY_C.hex()] == 1
            assert out["routing"]["forward_packets"] == 0

            assert out["ping_pong"]["pings"] == 1
            assert out["ping_pong"]["pongs"] == 1
            assert out["ping_pong"]["matched"] == 1
            assert out["ping_pong"]["unmatched_pings"] == 0

            assert out["anomalies"] == []
        finally:
            os.unlink(path)


class TestInvalidHandshake:
    """Test handshake violations."""

    def test_client_info_before_server_key(self):
        records = [
            make_record(1000000, DIR_C2S, 0x02, make_client_info_body()),
            make_record(1100000, DIR_S2C, 0x01, make_server_key_body()),
            make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
        ]
        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["handshake"]["valid"] is False
            violations_text = " ".join(out["handshake"]["violations"])
            assert "invalid_handshake" in violations_text
            anomalies_text = " ".join(out["anomalies"])
            assert "invalid_handshake" in anomalies_text
        finally:
            os.unlink(path)

    def test_incomplete_handshake(self):
        records = [
            make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
            make_record(1100000, DIR_C2S, 0x02, make_client_info_body()),
            make_record(2000000, DIR_S2C, 0x06, b""),
        ]
        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["handshake"]["valid"] is False
            violations_text = " ".join(out["handshake"]["violations"])
            assert "invalid_handshake" in violations_text
        finally:
            os.unlink(path)

    def test_pre_handshake_data(self):
        records = [
            make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
            make_record(1100000, DIR_C2S, 0x04, make_send_packet_body(DEST_KEY_A)),
            make_record(1200000, DIR_C2S, 0x02, make_client_info_body()),
            make_record(1300000, DIR_S2C, 0x03, make_server_info_body()),
        ]
        path = write_capture(records)
        try:
            out = run_analyzer(path)
            anomalies_text = " ".join(out["anomalies"])
            assert "pre_handshake_data" in anomalies_text
        finally:
            os.unlink(path)


class TestRoutingTable:
    """Test routing table extraction from SendPacket and RecvPacket."""

    def test_multiple_destinations(self):
        records = valid_handshake_records()
        for i in range(3):
            records.append(make_record(2000000 + i * 100000, DIR_C2S, 0x04,
                                       make_send_packet_body(DEST_KEY_A, f"data{i}".encode())))
        for i in range(2):
            records.append(make_record(3000000 + i * 100000, DIR_C2S, 0x04,
                                       make_send_packet_body(DEST_KEY_B, f"data{i}".encode())))
        for i in range(4):
            records.append(make_record(4000000 + i * 100000, DIR_S2C, 0x05,
                                       make_recv_packet_body(SRC_KEY_C, f"data{i}".encode())))
        records.append(make_record(5000000, DIR_S2C, 0x05,
                                   make_recv_packet_body(SRC_KEY_D, b"data")))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["routing"]["send_packets"][DEST_KEY_A.hex()] == 3
            assert out["routing"]["send_packets"][DEST_KEY_B.hex()] == 2
            assert out["routing"]["recv_packets"][SRC_KEY_C.hex()] == 4
            assert out["routing"]["recv_packets"][SRC_KEY_D.hex()] == 1
            assert out["routing"]["forward_packets"] == 0
        finally:
            os.unlink(path)

    def test_forward_packets(self):
        records = valid_handshake_records()
        records.append(make_record(2000000, DIR_S2C, 0x0A,
                                   make_forward_packet_body(SRC_KEY_C, DEST_KEY_A, b"fwd_data")))
        records.append(make_record(2100000, DIR_S2C, 0x0A,
                                   make_forward_packet_body(SRC_KEY_D, DEST_KEY_B, b"fwd_data2")))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["routing"]["forward_packets"] == 2
        finally:
            os.unlink(path)


class TestKeepalive:
    """Test KeepAlive timing analysis."""

    def test_keepalive_within_threshold(self):
        records = valid_handshake_records()
        records.append(make_record(10_000_000, DIR_S2C, 0x06, b""))
        records.append(make_record(50_000_000, DIR_S2C, 0x06, b""))
        records.append(make_record(100_000_000, DIR_S2C, 0x06, b""))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["keepalive"]["count"] == 3
            assert out["keepalive"]["max_gap_us"] == 50_000_000
            assert out["keepalive"]["threshold_exceeded"] is False
            assert not any("keepalive_gap" in a for a in out["anomalies"])
        finally:
            os.unlink(path)

    def test_keepalive_exceeds_threshold(self):
        records = valid_handshake_records()
        records.append(make_record(10_000_000, DIR_S2C, 0x06, b""))
        records.append(make_record(50_000_000, DIR_S2C, 0x06, b""))
        records.append(make_record(200_000_000, DIR_S2C, 0x06, b""))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["keepalive"]["count"] == 3
            assert out["keepalive"]["max_gap_us"] == 150_000_000
            assert out["keepalive"]["threshold_exceeded"] is True
            assert any("keepalive_gap" in a for a in out["anomalies"])
        finally:
            os.unlink(path)

    def test_single_keepalive(self):
        records = valid_handshake_records()
        records.append(make_record(10_000_000, DIR_S2C, 0x06, b""))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["keepalive"]["count"] == 1
            assert out["keepalive"]["max_gap_us"] is None
            assert out["keepalive"]["threshold_exceeded"] is False
        finally:
            os.unlink(path)


class TestPingPong:
    """Test Ping/Pong matching logic."""

    def test_matched_pair(self):
        records = valid_handshake_records()
        payload = b"\xaa\xbb\xcc\xdd\xee\xff\x11\x22"
        records.append(make_record(2000000, DIR_S2C, 0x12, payload))
        records.append(make_record(2100000, DIR_C2S, 0x13, payload))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["ping_pong"]["pings"] == 1
            assert out["ping_pong"]["pongs"] == 1
            assert out["ping_pong"]["matched"] == 1
            assert out["ping_pong"]["unmatched_pings"] == 0
            assert not any("unmatched_ping" in a for a in out["anomalies"])
        finally:
            os.unlink(path)

    def test_unmatched_pings(self):
        records = valid_handshake_records()
        payload_1 = b"\x01" * 8
        payload_2 = b"\x02" * 8
        records.append(make_record(2000000, DIR_S2C, 0x12, payload_1))
        records.append(make_record(2100000, DIR_S2C, 0x12, payload_2))
        records.append(make_record(2200000, DIR_C2S, 0x13, payload_1))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["ping_pong"]["pings"] == 2
            assert out["ping_pong"]["pongs"] == 1
            assert out["ping_pong"]["matched"] == 1
            assert out["ping_pong"]["unmatched_pings"] == 1
            assert any("unmatched_ping" in a for a in out["anomalies"])
        finally:
            os.unlink(path)

    def test_duplicate_ping_payload(self):
        records = valid_handshake_records()
        payload = b"\xde\xad\xbe\xef" * 2
        records.append(make_record(2000000, DIR_S2C, 0x12, payload))
        records.append(make_record(2100000, DIR_S2C, 0x12, payload))
        records.append(make_record(2200000, DIR_C2S, 0x13, payload))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert any("duplicate_ping" in a for a in out["anomalies"])
        finally:
            os.unlink(path)


class TestAnomalyDetection:
    """Test anomaly detection for various edge cases."""

    def test_unknown_frame_type(self):
        records = valid_handshake_records()
        records.append(make_record(2000000, DIR_S2C, 0xFF, b"\x00" * 10))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert "Unknown" in out["frame_counts"]
            assert out["frame_counts"]["Unknown"] == 1
            assert any("unknown_frame_type" in a for a in out["anomalies"])
        finally:
            os.unlink(path)

    def test_bad_server_key_magic(self):
        bad_magic = b"BADMAGIC"
        bad_body = bad_magic + SERVER_KEY
        records = [
            make_record(1000000, DIR_S2C, 0x01, bad_body),
            make_record(1100000, DIR_C2S, 0x02, make_client_info_body()),
            make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
        ]
        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert any("bad_magic" in a for a in out["anomalies"])
        finally:
            os.unlink(path)


class TestMeshFrames:
    """Test mesh-related frame types."""

    def test_mesh_frame_counts(self):
        records = valid_handshake_records()
        peer_key = bytes(range(200, 232))

        records.append(make_record(2000000, DIR_C2S, 0x10, b""))

        records.append(make_record(2100000, DIR_S2C, 0x09,
                                   make_peer_present_body(peer_key)))

        records.append(make_record(3000000, DIR_S2C, 0x08, make_peer_gone_body(peer_key)))
        records.append(make_record(3100000, DIR_C2S, 0x11, peer_key))
        records.append(make_record(3200000, DIR_C2S, 0x07, b"\x01"))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["frame_counts"]["WatchConns"] == 1
            assert out["frame_counts"]["PeerPresent"] == 1
            assert out["frame_counts"]["PeerGone"] == 1
            assert out["frame_counts"]["ClosePeer"] == 1
            assert out["frame_counts"]["NotePreferred"] == 1
            assert out["handshake"]["valid"] is True
        finally:
            os.unlink(path)


class TestHealthAndRestarting:
    """Test Health and Restarting frame types."""

    def test_health_and_restarting(self):
        records = valid_handshake_records()
        records.append(make_record(2000000, DIR_S2C, 0x14, b"duplicate connection detected"))
        restarting_body = struct.pack("!II", 5000, 15000)
        records.append(make_record(3000000, DIR_S2C, 0x15, restarting_body))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["frame_counts"]["Health"] == 1
            assert out["frame_counts"]["Restarting"] == 1
            assert out["handshake"]["valid"] is True
        finally:
            os.unlink(path)


class TestComplexSession:
    """Integration test with a complex multi-frame session."""

    def test_full_session(self):
        records = valid_handshake_records(start_ts=0)
        records.append(make_record(10_000_000, DIR_S2C, 0x06, b""))
        records.append(make_record(60_000_000, DIR_S2C, 0x06, b""))
        records.append(make_record(119_000_000, DIR_S2C, 0x06, b""))

        for i in range(5):
            records.append(make_record(120_000_000 + i * 100_000, DIR_C2S, 0x04,
                                       make_send_packet_body(DEST_KEY_A, f"msg{i}".encode())))
        records.append(make_record(125_000_000, DIR_C2S, 0x04,
                                   make_send_packet_body(DEST_KEY_B, b"hello")))

        for i in range(3):
            records.append(make_record(130_000_000 + i * 100_000, DIR_S2C, 0x05,
                                       make_recv_packet_body(SRC_KEY_C, f"reply{i}".encode())))

        p1 = b"\x11\x22\x33\x44\x55\x66\x77\x88"
        p2 = b"\xaa\xbb\xcc\xdd\xee\xff\x00\x11"
        records.append(make_record(140_000_000, DIR_S2C, 0x12, p1))
        records.append(make_record(140_050_000, DIR_C2S, 0x13, p1))
        records.append(make_record(141_000_000, DIR_S2C, 0x12, p2))

        records.append(make_record(150_000_000, DIR_C2S, 0x07, b"\x01"))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["frame_counts"]["SendPacket"] == 6
            assert out["frame_counts"]["RecvPacket"] == 3
            assert out["frame_counts"]["KeepAlive"] == 3
            assert out["frame_counts"]["Ping"] == 2
            assert out["frame_counts"]["Pong"] == 1
            assert out["frame_counts"]["NotePreferred"] == 1

            assert out["routing"]["send_packets"][DEST_KEY_A.hex()] == 5
            assert out["routing"]["send_packets"][DEST_KEY_B.hex()] == 1
            assert out["routing"]["recv_packets"][SRC_KEY_C.hex()] == 3

            assert out["keepalive"]["count"] == 3
            assert out["keepalive"]["threshold_exceeded"] is False

            assert out["ping_pong"]["pings"] == 2
            assert out["ping_pong"]["matched"] == 1
            assert out["ping_pong"]["unmatched_pings"] == 1
            assert any("unmatched_ping" in a for a in out["anomalies"])

            assert out["handshake"]["valid"] is True
            assert out["handshake"]["server_key"] == SERVER_KEY.hex()
            assert out["handshake"]["client_key"] == CLIENT_KEY.hex()
        finally:
            os.unlink(path)


class TestOutputSchema:
    """Verify the output conforms to the expected schema structure."""

    def test_all_required_keys_present(self):
        records = valid_handshake_records()
        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert "session" in out
            assert "handshake" in out
            assert "frame_counts" in out
            assert "routing" in out
            assert "keepalive" in out
            assert "ping_pong" in out
            assert "anomalies" in out
            assert "session_count" in out
            assert "session_boundaries" in out

            assert "start_time_us" in out["session"]
            assert "end_time_us" in out["session"]
            assert "duration_us" in out["session"]
            assert "total_frames" in out["session"]

            assert "valid" in out["handshake"]
            assert "server_key" in out["handshake"]
            assert "client_key" in out["handshake"]
            assert "client_nonce" in out["handshake"]
            assert "violations" in out["handshake"]

            assert "send_packets" in out["routing"]
            assert "recv_packets" in out["routing"]
            assert "forward_packets" in out["routing"]

            assert "count" in out["keepalive"]
            assert "max_gap_us" in out["keepalive"]
            assert "threshold_exceeded" in out["keepalive"]

            assert "pings" in out["ping_pong"]
            assert "pongs" in out["ping_pong"]
            assert "matched" in out["ping_pong"]
            assert "unmatched_pings" in out["ping_pong"]

            assert isinstance(out["anomalies"], list)
        finally:
            os.unlink(path)

    def test_keys_are_lowercase_hex(self):
        records = valid_handshake_records()
        path = write_capture(records)
        try:
            out = run_analyzer(path)
            sk = out["handshake"]["server_key"]
            ck = out["handshake"]["client_key"]
            assert sk is not None
            assert ck is not None
            assert sk == sk.lower(), "server_key must be lowercase hex"
            assert ck == ck.lower(), "client_key must be lowercase hex"
            assert len(bytes.fromhex(sk)) == 32
            assert len(bytes.fromhex(ck)) == 32
        finally:
            os.unlink(path)


# ===========================================================================
# Ghost traffic detection tests
# ===========================================================================


class TestGhostTraffic:
    """Test session lifecycle integrity: ghost traffic after PeerGone."""

    def test_ghost_recv_after_peer_gone(self):
        """RecvPacket from peer X after PeerGone(X) is ghost traffic."""
        records = valid_handshake_records()
        # PeerPresent for SRC_KEY_C
        records.append(make_record(2000000, DIR_S2C, 0x09,
                                   make_peer_present_body(SRC_KEY_C)))
        # PeerGone for SRC_KEY_C
        records.append(make_record(3000000, DIR_S2C, 0x08,
                                   make_peer_gone_body(SRC_KEY_C)))
        # RecvPacket from SRC_KEY_C after PeerGone — ghost traffic
        records.append(make_record(4000000, DIR_S2C, 0x05,
                                   make_recv_packet_body(SRC_KEY_C)))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert any("ghost_recv" in a for a in out["anomalies"]), \
                f"Expected ghost_recv anomaly, got: {out['anomalies']}"
        finally:
            os.unlink(path)

    def test_ghost_send_after_peer_gone(self):
        """SendPacket to peer X after PeerGone(X) is ghost traffic."""
        records = valid_handshake_records()
        # PeerPresent for DEST_KEY_A
        records.append(make_record(2000000, DIR_S2C, 0x09,
                                   make_peer_present_body(DEST_KEY_A)))
        # PeerGone for DEST_KEY_A
        records.append(make_record(3000000, DIR_S2C, 0x08,
                                   make_peer_gone_body(DEST_KEY_A)))
        # SendPacket to DEST_KEY_A after PeerGone — ghost traffic
        records.append(make_record(4000000, DIR_C2S, 0x04,
                                   make_send_packet_body(DEST_KEY_A)))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert any("ghost_send" in a for a in out["anomalies"]), \
                f"Expected ghost_send anomaly, got: {out['anomalies']}"
        finally:
            os.unlink(path)

    def test_no_ghost_after_peer_restored(self):
        """PeerGone then PeerPresent restores peer — subsequent traffic is NOT ghost."""
        records = valid_handshake_records()
        # PeerPresent
        records.append(make_record(2000000, DIR_S2C, 0x09,
                                   make_peer_present_body(SRC_KEY_C)))
        # PeerGone
        records.append(make_record(3000000, DIR_S2C, 0x08,
                                   make_peer_gone_body(SRC_KEY_C)))
        # PeerPresent again (restore)
        records.append(make_record(3500000, DIR_S2C, 0x09,
                                   make_peer_present_body(SRC_KEY_C)))
        # RecvPacket — NOT ghost because PeerPresent restored the peer
        records.append(make_record(4000000, DIR_S2C, 0x05,
                                   make_recv_packet_body(SRC_KEY_C)))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            ghost_anomalies = [a for a in out["anomalies"]
                               if "ghost_recv" in a or "ghost_send" in a]
            assert len(ghost_anomalies) == 0, \
                f"Expected no ghost anomalies after restore, got: {ghost_anomalies}"
        finally:
            os.unlink(path)

    def test_ghost_only_after_explicit_peer_gone(self):
        """Traffic to never-announced peers is NOT ghost traffic."""
        records = valid_handshake_records()
        # RecvPacket from SRC_KEY_C — never had PeerPresent or PeerGone
        records.append(make_record(2000000, DIR_S2C, 0x05,
                                   make_recv_packet_body(SRC_KEY_C)))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            ghost_anomalies = [a for a in out["anomalies"]
                               if "ghost_recv" in a or "ghost_send" in a]
            assert len(ghost_anomalies) == 0, \
                f"Expected no ghost anomalies for unannounced peers, got: {ghost_anomalies}"
        finally:
            os.unlink(path)


# ===========================================================================
# Multi-session detection tests
# ===========================================================================


class TestMultiSession:
    """Test multi-session detection within a single capture."""

    def test_two_sequential_sessions(self):
        """Two complete handshakes in one capture produces session_count=2."""
        records = valid_handshake_records(start_ts=1000000)
        records.append(make_record(2000000, DIR_C2S, 0x04,
                                   make_send_packet_body(DEST_KEY_A)))
        # Second session starts with new ServerKey
        records.append(make_record(5000000, DIR_S2C, 0x01,
                                   make_server_key_body(key=bytes(range(200, 232)))))
        records.append(make_record(5100000, DIR_C2S, 0x02,
                                   make_client_info_body(key=SRC_KEY_C,
                                                         nonce=b"\xdd" * 24)))
        records.append(make_record(5200000, DIR_S2C, 0x03, make_server_info_body()))
        records.append(make_record(6000000, DIR_C2S, 0x04,
                                   make_send_packet_body(DEST_KEY_B)))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["session_count"] == 2
            assert len(out["session_boundaries"]) == 2

            # First session
            sb0 = out["session_boundaries"][0]
            assert sb0["start_time_us"] == 1000000
            assert sb0["end_time_us"] == 2000000
            assert sb0["handshake_valid"] is True
            assert sb0["client_key"] == CLIENT_KEY.hex()
            assert sb0["server_key"] == SERVER_KEY.hex()

            # Second session
            sb1 = out["session_boundaries"][1]
            assert sb1["start_time_us"] == 5000000
            assert sb1["end_time_us"] == 6000000
            assert sb1["handshake_valid"] is True
            assert sb1["client_key"] == SRC_KEY_C.hex()
            assert sb1["server_key"] == bytes(range(200, 232)).hex()
            assert sb1["client_nonce"] == ("dd" * 24)

            # Main handshake reflects first session
            assert out["handshake"]["valid"] is True
            assert out["handshake"]["client_key"] == CLIENT_KEY.hex()
            assert out["handshake"]["server_key"] == SERVER_KEY.hex()

            # Aggregate frame counts include both sessions
            assert out["frame_counts"]["ServerKey"] == 2
            assert out["frame_counts"]["ClientInfo"] == 2
            assert out["frame_counts"]["ServerInfo"] == 2
            assert out["frame_counts"]["SendPacket"] == 2
        finally:
            os.unlink(path)

    def test_single_session_count(self):
        """Standard single session produces session_count=1."""
        records = valid_handshake_records()
        records.append(make_record(2000000, DIR_S2C, 0x06, b""))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["session_count"] == 1
            assert len(out["session_boundaries"]) == 1
            assert out["session_boundaries"][0]["handshake_valid"] is True
            assert out["session_boundaries"][0]["client_key"] == CLIENT_KEY.hex()
        finally:
            os.unlink(path)

    def test_session_nonce_extraction(self):
        """Client nonce is correctly extracted from ClientInfo body."""
        test_nonce = b"\xfe\xdc\xba" * 8  # 24 bytes
        records = valid_handshake_records(nonce=test_nonce)
        records.append(make_record(2000000, DIR_S2C, 0x06, b""))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["handshake"]["client_nonce"] == test_nonce.hex()
            assert out["session_boundaries"][0]["client_nonce"] == test_nonce.hex()
        finally:
            os.unlink(path)

    def test_session_with_rekeying(self):
        """New handshake after data frames indicates reconnection/rekeying."""
        records = valid_handshake_records(start_ts=1000000)
        for i in range(3):
            records.append(make_record(2000000 + i * 100000, DIR_C2S, 0x04,
                           make_send_packet_body(DEST_KEY_A)))
        # Rekey with different client key
        records.append(make_record(10000000, DIR_S2C, 0x01,
                                   make_server_key_body(key=bytes(range(200, 232)))))
        records.append(make_record(10100000, DIR_C2S, 0x02,
                                   make_client_info_body(key=DEST_KEY_B)))
        records.append(make_record(10200000, DIR_S2C, 0x03, make_server_info_body()))
        records.append(make_record(11000000, DIR_C2S, 0x04,
                                   make_send_packet_body(SRC_KEY_D)))

        path = write_capture(records)
        try:
            out = run_analyzer(path)
            assert out["session_count"] == 2
            assert out["session_boundaries"][0]["client_key"] == CLIENT_KEY.hex()
            assert out["session_boundaries"][1]["client_key"] == DEST_KEY_B.hex()
        finally:
            os.unlink(path)


# ===========================================================================
# pcap ingestion tests
# ===========================================================================


class TestPcapInput:
    """Test processing pcap files via tshark."""

    def test_pcap_frame_counts(self):
        """Verify frame extraction from pcap file via tshark."""
        frames = b""
        frames += make_frame(0x01, make_server_key_body())
        frames += make_frame(0x02, make_client_info_body())
        frames += make_frame(0x03, make_server_info_body())
        frames += make_frame(0x06, b"")  # KeepAlive
        frames += make_frame(0x04, make_send_packet_body(DEST_KEY_A))

        pcap_data = create_pcap_with_tcp_payload(frames)
        fd, path = tempfile.mkstemp(suffix=".pcap")
        with os.fdopen(fd, "wb") as f:
            f.write(pcap_data)

        try:
            out = run_pcap_analyzer(path)
            assert out["mode"] == "pcap"
            assert out["frame_counts"]["ServerKey"] == 1
            assert out["frame_counts"]["ClientInfo"] == 1
            assert out["frame_counts"]["ServerInfo"] == 1
            assert out["frame_counts"]["KeepAlive"] == 1
            assert out["frame_counts"]["SendPacket"] == 1
            assert out["session"]["total_frames"] == 5
        finally:
            os.unlink(path)

    def test_pcap_routing_extraction(self):
        """Verify routing table extraction from pcap."""
        frames = b""
        frames += make_frame(0x01, make_server_key_body())
        frames += make_frame(0x02, make_client_info_body())
        frames += make_frame(0x03, make_server_info_body())
        frames += make_frame(0x04, make_send_packet_body(DEST_KEY_A, b"d1"))
        frames += make_frame(0x04, make_send_packet_body(DEST_KEY_A, b"d2"))
        frames += make_frame(0x05, make_recv_packet_body(SRC_KEY_C, b"r1"))

        pcap_data = create_pcap_with_tcp_payload(frames)
        fd, path = tempfile.mkstemp(suffix=".pcap")
        with os.fdopen(fd, "wb") as f:
            f.write(pcap_data)

        try:
            out = run_pcap_analyzer(path)
            assert out["routing"]["send_packets"][DEST_KEY_A.hex()] == 2
            assert out["routing"]["recv_packets"][SRC_KEY_C.hex()] == 1
        finally:
            os.unlink(path)


# ===========================================================================
# Multi-relay directory mode tests
# ===========================================================================


class TestMultiCaptureTopology:
    """Test directory mode with multiple relay captures."""

    def test_topology_reconstruction(self):
        """Same client on multiple relays should appear in topology."""
        dir_path = tempfile.mkdtemp()
        try:
            # Relay Alpha: CLIENT_KEY sends to DEST_KEY_A
            records_a = valid_handshake_records(start_ts=1000000)
            records_a.append(make_record(2000000, DIR_C2S, 0x04,
                                         make_send_packet_body(DEST_KEY_A)))
            records_a.append(make_record(3000000, DIR_S2C, 0x05,
                                         make_recv_packet_body(SRC_KEY_C)))
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            # Relay Beta: same CLIENT_KEY sends to DEST_KEY_B
            records_b = valid_handshake_records(start_ts=1500000)
            records_b.append(make_record(2500000, DIR_C2S, 0x04,
                                         make_send_packet_body(DEST_KEY_B)))
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)

            assert out["mode"] == "directory"
            assert "relay-alpha" in out["relay_reports"]
            assert "relay-beta" in out["relay_reports"]

            ck = CLIENT_KEY.hex()
            assert ck in out["topology"]["peers"]
            peer_info = out["topology"]["peers"][ck]
            assert sorted(peer_info["relays"]) == ["relay-alpha", "relay-beta"]
            assert DEST_KEY_A.hex() in peer_info["destinations"]
            assert DEST_KEY_B.hex() in peer_info["destinations"]
            assert peer_info["total_packets_sent"] == 2
            assert peer_info["total_packets_received"] == 1
        finally:
            shutil.rmtree(dir_path)

    def test_relay_peer_counts(self):
        """Verify peer count per relay includes client + routing peers."""
        dir_path = tempfile.mkdtemp()
        try:
            records = valid_handshake_records()
            records.append(make_record(2000000, DIR_C2S, 0x04,
                                       make_send_packet_body(DEST_KEY_A)))
            records.append(make_record(3000000, DIR_C2S, 0x04,
                                       make_send_packet_body(DEST_KEY_B)))
            write_capture_to(records, os.path.join(dir_path, "relay-gamma.dpcap"))

            out = run_dir_analyzer(dir_path)
            # CLIENT_KEY + DEST_KEY_A + DEST_KEY_B = 3 unique peers
            assert out["topology"]["relay_peer_counts"]["relay-gamma"] == 3
        finally:
            shutil.rmtree(dir_path)

    def test_per_relay_reports_match_single_file(self):
        """Each relay report in directory mode matches single-file output."""
        dir_path = tempfile.mkdtemp()
        try:
            records = valid_handshake_records()
            records.append(make_record(2000000, DIR_S2C, 0x06, b""))
            capture_path = os.path.join(dir_path, "relay-delta.dpcap")
            write_capture_to(records, capture_path)

            single_out = run_analyzer(capture_path)
            dir_out = run_dir_analyzer(dir_path)

            relay_report = dir_out["relay_reports"]["relay-delta"]
            assert relay_report["session"] == single_out["session"]
            assert relay_report["handshake"] == single_out["handshake"]
            assert relay_report["frame_counts"] == single_out["frame_counts"]
            assert relay_report["routing"] == single_out["routing"]
        finally:
            shutil.rmtree(dir_path)


# ===========================================================================
# Policy violation tests
# ===========================================================================


class TestPolicyViolations:
    """Test SQLite-based policy enforcement."""

    def test_unauthorized_relay(self):
        """Peer on unauthorized relay triggers violation."""
        dir_path = tempfile.mkdtemp()
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)

        try:
            records = valid_handshake_records()
            records.append(make_record(2000000, DIR_C2S, 0x04,
                                       make_send_packet_body(DEST_KEY_A)))
            write_capture_to(records, os.path.join(dir_path, "relay-beta.dpcap"))

            create_test_db(db_path,
                relays=[("relay-alpha", "us-east", "derp1.example.com", 100),
                        ("relay-beta", "us-west", "derp2.example.com", 100)],
                policies=[(CLIENT_KEY.hex(), "testuser", "relay-alpha", None, 1)])

            out = run_dir_analyzer(dir_path, db_path)

            violations = [v for v in out["policy_violations"]
                         if v["type"] == "unauthorized_relay"]
            assert len(violations) == 1
            assert violations[0]["peer_key"] == CLIENT_KEY.hex()
            assert violations[0]["relay_id"] == "relay-beta"
        finally:
            shutil.rmtree(dir_path)
            os.unlink(db_path)

    def test_blocked_peer(self):
        """Blocklisted peer triggers violation."""
        dir_path = tempfile.mkdtemp()
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)

        try:
            records = valid_handshake_records()
            write_capture_to(records, os.path.join(dir_path, "relay-alpha.dpcap"))

            create_test_db(db_path,
                relays=[("relay-alpha", "us-east", "derp1.example.com", 100)],
                blocklist=[(CLIENT_KEY.hex(), "compromised_key", "2024-01-15T00:00:00Z")])

            out = run_dir_analyzer(dir_path, db_path)

            violations = [v for v in out["policy_violations"]
                         if v["type"] == "blocked_peer"]
            assert len(violations) == 1
            assert violations[0]["peer_key"] == CLIENT_KEY.hex()
        finally:
            shutil.rmtree(dir_path)
            os.unlink(db_path)

    def test_unauthorized_destination(self):
        """Sending to unauthorized destination triggers violation."""
        dir_path = tempfile.mkdtemp()
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)

        try:
            records = valid_handshake_records()
            records.append(make_record(2000000, DIR_C2S, 0x04,
                                       make_send_packet_body(DEST_KEY_B)))
            write_capture_to(records, os.path.join(dir_path, "relay-alpha.dpcap"))

            create_test_db(db_path,
                relays=[("relay-alpha", "us-east", "derp1.example.com", 100)],
                policies=[(CLIENT_KEY.hex(), "testuser", "relay-alpha",
                           DEST_KEY_A.hex(), 1)])

            out = run_dir_analyzer(dir_path, db_path)

            violations = [v for v in out["policy_violations"]
                         if v["type"] == "unauthorized_destination"]
            assert len(violations) == 1
            assert violations[0]["destination_key"] == DEST_KEY_B.hex()
        finally:
            shutil.rmtree(dir_path)
            os.unlink(db_path)

    def test_no_violations_when_compliant(self):
        """Compliant peer produces no violations."""
        dir_path = tempfile.mkdtemp()
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)

        try:
            records = valid_handshake_records()
            records.append(make_record(2000000, DIR_C2S, 0x04,
                                       make_send_packet_body(DEST_KEY_A)))
            write_capture_to(records, os.path.join(dir_path, "relay-alpha.dpcap"))

            create_test_db(db_path,
                relays=[("relay-alpha", "us-east", "derp1.example.com", 100)],
                policies=[(CLIENT_KEY.hex(), "testuser", "relay-alpha",
                           DEST_KEY_A.hex(), 1)])

            out = run_dir_analyzer(dir_path, db_path)
            assert len(out["policy_violations"]) == 0
        finally:
            shutil.rmtree(dir_path)
            os.unlink(db_path)


# ===========================================================================
# Cross-relay conflict tests
# ===========================================================================


class TestCrossRelayConflicts:
    """Test cross-relay session conflict detection."""

    def test_overlapping_sessions(self):
        """Same peer with overlapping sessions on different relays."""
        dir_path = tempfile.mkdtemp()
        try:
            # Relay Alpha: session from ts 1000000 to 5000000
            records_a = valid_handshake_records(start_ts=1000000)
            records_a.append(make_record(5000000, DIR_S2C, 0x06, b""))
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            # Relay Beta: same client, session from ts 3000000 to 7000000
            records_b = valid_handshake_records(start_ts=3000000)
            records_b.append(make_record(7000000, DIR_S2C, 0x06, b""))
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)

            assert len(out["cross_relay_conflicts"]) == 1
            conflict = out["cross_relay_conflicts"][0]
            assert conflict["peer_key"] == CLIENT_KEY.hex()
            assert sorted(conflict["relays"]) == ["relay-alpha", "relay-beta"]
            assert conflict["time_overlap_us"] == [3000000, 5000000]
        finally:
            shutil.rmtree(dir_path)

    def test_non_overlapping_sessions(self):
        """Same peer with non-overlapping sessions should not conflict."""
        dir_path = tempfile.mkdtemp()
        try:
            # Relay Alpha: session from ts 1000000 to 3000000
            records_a = valid_handshake_records(start_ts=1000000)
            records_a.append(make_record(3000000, DIR_S2C, 0x06, b""))
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            # Relay Beta: same client, session from ts 5000000 to 7000000
            records_b = valid_handshake_records(start_ts=5000000)
            records_b.append(make_record(7000000, DIR_S2C, 0x06, b""))
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)
            assert len(out["cross_relay_conflicts"]) == 0
        finally:
            shutil.rmtree(dir_path)

    def test_different_peers_no_conflict(self):
        """Different peers on different relays should not conflict."""
        dir_path = tempfile.mkdtemp()
        alt_client_key = bytes(range(200, 232))
        try:
            records_a = valid_handshake_records(start_ts=1000000)
            records_a.append(make_record(5000000, DIR_S2C, 0x06, b""))
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            # Different client key on relay-beta
            records_b = [
                make_record(2000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(2100000, DIR_C2S, 0x02, make_client_info_body(key=alt_client_key)),
                make_record(2200000, DIR_S2C, 0x03, make_server_info_body()),
                make_record(6000000, DIR_S2C, 0x06, b""),
            ]
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)
            assert len(out["cross_relay_conflicts"]) == 0
        finally:
            shutil.rmtree(dir_path)


# ===========================================================================
# Nonce reuse detection tests
# ===========================================================================


class TestNonceReuse:
    """Test cross-relay nonce reuse detection for NaCl replay attacks."""

    def test_same_nonce_different_relays(self):
        """Same client key with identical nonce on two relays triggers alert."""
        dir_path = tempfile.mkdtemp()
        shared_nonce = b"\xaa" * 24

        try:
            records_a = [
                make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(1100000, DIR_C2S, 0x02,
                            make_client_info_body(nonce=shared_nonce)),
                make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
            ]
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            records_b = [
                make_record(2000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(2100000, DIR_C2S, 0x02,
                            make_client_info_body(nonce=shared_nonce)),
                make_record(2200000, DIR_S2C, 0x03, make_server_info_body()),
            ]
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)

            assert len(out["nonce_reuse_alerts"]) == 1
            alert = out["nonce_reuse_alerts"][0]
            assert alert["peer_key"] == CLIENT_KEY.hex()
            assert alert["nonce_hex"] == shared_nonce.hex()
            assert sorted(alert["relays"]) == ["relay-alpha", "relay-beta"]
        finally:
            shutil.rmtree(dir_path)

    def test_different_nonces_no_alert(self):
        """Same client key with different nonces across relays is normal."""
        dir_path = tempfile.mkdtemp()

        try:
            records_a = [
                make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(1100000, DIR_C2S, 0x02,
                            make_client_info_body(nonce=b"\xaa" * 24)),
                make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
            ]
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            records_b = [
                make_record(2000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(2100000, DIR_C2S, 0x02,
                            make_client_info_body(nonce=b"\xbb" * 24)),
                make_record(2200000, DIR_S2C, 0x03, make_server_info_body()),
            ]
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)
            assert len(out["nonce_reuse_alerts"]) == 0
        finally:
            shutil.rmtree(dir_path)

    def test_nonce_reuse_three_relays(self):
        """Nonce reused across three relays reports all three."""
        dir_path = tempfile.mkdtemp()
        shared_nonce = b"\xee" * 24

        try:
            for name in ["relay-alpha", "relay-beta", "relay-gamma"]:
                ts = {"relay-alpha": 1000000, "relay-beta": 2000000,
                      "relay-gamma": 3000000}[name]
                records = [
                    make_record(ts, DIR_S2C, 0x01, make_server_key_body()),
                    make_record(ts + 100000, DIR_C2S, 0x02,
                                make_client_info_body(nonce=shared_nonce)),
                    make_record(ts + 200000, DIR_S2C, 0x03, make_server_info_body()),
                ]
                write_capture_to(records, os.path.join(dir_path, f"{name}.dpcap"))

            out = run_dir_analyzer(dir_path)

            assert len(out["nonce_reuse_alerts"]) == 1
            alert = out["nonce_reuse_alerts"][0]
            assert sorted(alert["relays"]) == ["relay-alpha", "relay-beta", "relay-gamma"]
        finally:
            shutil.rmtree(dir_path)


# ===========================================================================
# Bridge peer identification tests
# ===========================================================================


class TestBridgePeers:
    """Test bridge peer identification across relay segments."""

    def test_bridge_peer_detection(self):
        """Peer that is client on one relay and send destination on another."""
        dir_path = tempfile.mkdtemp()

        try:
            # Relay Alpha: CLIENT_KEY sends to DEST_KEY_A
            records_a = valid_handshake_records(start_ts=1000000)
            records_a.append(make_record(2000000, DIR_C2S, 0x04,
                             make_send_packet_body(DEST_KEY_A)))
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            # Relay Beta: DEST_KEY_A is the client (bridges the two relays)
            records_b = [
                make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(1100000, DIR_C2S, 0x02,
                            make_client_info_body(key=DEST_KEY_A,
                                                   nonce=b"\xcc" * 24)),
                make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
                make_record(2000000, DIR_C2S, 0x04,
                            make_send_packet_body(SRC_KEY_D)),
            ]
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)

            # DEST_KEY_A is a client on relay-beta AND a send target on relay-alpha
            assert DEST_KEY_A.hex() in out["bridge_peers"]
        finally:
            shutil.rmtree(dir_path)

    def test_bridge_via_recv_source(self):
        """Peer that is client on one relay and recv source on another."""
        dir_path = tempfile.mkdtemp()

        try:
            # Relay Alpha: CLIENT_KEY receives from SRC_KEY_C
            records_a = valid_handshake_records(start_ts=1000000)
            records_a.append(make_record(2000000, DIR_S2C, 0x05,
                             make_recv_packet_body(SRC_KEY_C)))
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            # Relay Beta: SRC_KEY_C is the client
            records_b = [
                make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(1100000, DIR_C2S, 0x02,
                            make_client_info_body(key=SRC_KEY_C,
                                                   nonce=b"\xdd" * 24)),
                make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
            ]
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)

            # SRC_KEY_C is a client on relay-beta AND a recv source on relay-alpha
            assert SRC_KEY_C.hex() in out["bridge_peers"]
        finally:
            shutil.rmtree(dir_path)

    def test_no_bridge_when_isolated(self):
        """Peers on separate relays with no overlap are not bridges."""
        dir_path = tempfile.mkdtemp()

        try:
            records_a = valid_handshake_records(start_ts=1000000)
            records_a.append(make_record(2000000, DIR_C2S, 0x04,
                             make_send_packet_body(DEST_KEY_A)))
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            # Relay Beta: completely different peer, no key overlap
            records_b = [
                make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(1100000, DIR_C2S, 0x02,
                            make_client_info_body(key=SRC_KEY_D,
                                                   nonce=b"\xee" * 24)),
                make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
            ]
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)
            assert len(out["bridge_peers"]) == 0
        finally:
            shutil.rmtree(dir_path)


# ===========================================================================
# Traffic flow correlation tests
# ===========================================================================


class TestTrafficCorrelation:
    """Test cross-relay traffic flow correlation via timing analysis."""

    def test_correlated_flow_detected(self):
        """Send on R1 at T, recv on R2 at T+500ms → correlated flow."""
        dir_path = tempfile.mkdtemp()

        try:
            # Relay Alpha: CLIENT_KEY sends to DEST_KEY_A at time 2000000
            records_a = valid_handshake_records(start_ts=1000000)
            records_a.append(make_record(2000000, DIR_C2S, 0x04,
                             make_send_packet_body(DEST_KEY_A)))
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            # Relay Beta: DEST_KEY_A is client, receives from CLIENT_KEY at 2500000
            # Delta = 500000 us < 1000000 us → correlated
            records_b = [
                make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(1100000, DIR_C2S, 0x02,
                            make_client_info_body(key=DEST_KEY_A, nonce=b"\xcc" * 24)),
                make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
                make_record(2500000, DIR_S2C, 0x05,
                            make_recv_packet_body(CLIENT_KEY)),
            ]
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)

            assert len(out["traffic_correlations"]) >= 1
            corr = out["traffic_correlations"][0]
            assert corr["src_peer"] == CLIENT_KEY.hex()
            assert corr["dst_peer"] == DEST_KEY_A.hex()
            assert corr["src_relay"] == "relay-alpha"
            assert corr["dst_relay"] == "relay-beta"
            assert corr["correlated_packets"] >= 1
        finally:
            shutil.rmtree(dir_path)

    def test_no_correlation_outside_window(self):
        """Send/recv with timing > 1 second apart should not correlate."""
        dir_path = tempfile.mkdtemp()

        try:
            # Relay Alpha: CLIENT_KEY sends to DEST_KEY_A at time 2000000
            records_a = valid_handshake_records(start_ts=1000000)
            records_a.append(make_record(2000000, DIR_C2S, 0x04,
                             make_send_packet_body(DEST_KEY_A)))
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            # Relay Beta: DEST_KEY_A is client, receives from CLIENT_KEY at 5000000
            # Delta = 3000000 us > 1000000 us → no correlation
            records_b = [
                make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(1100000, DIR_C2S, 0x02,
                            make_client_info_body(key=DEST_KEY_A, nonce=b"\xdd" * 24)),
                make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
                make_record(5000000, DIR_S2C, 0x05,
                            make_recv_packet_body(CLIENT_KEY)),
            ]
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)

            assert len(out["traffic_correlations"]) == 0
        finally:
            shutil.rmtree(dir_path)

    def test_multiple_correlated_packets(self):
        """Multiple send/recv within window produces higher correlated_packets."""
        dir_path = tempfile.mkdtemp()

        try:
            records_a = valid_handshake_records(start_ts=1000000)
            # Three sends to DEST_KEY_A, spaced 500ms apart
            records_a.append(make_record(2000000, DIR_C2S, 0x04,
                             make_send_packet_body(DEST_KEY_A, b"d1")))
            records_a.append(make_record(2500000, DIR_C2S, 0x04,
                             make_send_packet_body(DEST_KEY_A, b"d2")))
            records_a.append(make_record(3000000, DIR_C2S, 0x04,
                             make_send_packet_body(DEST_KEY_A, b"d3")))
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            records_b = [
                make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(1100000, DIR_C2S, 0x02,
                            make_client_info_body(key=DEST_KEY_A, nonce=b"\xee" * 24)),
                make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
                # Three matching recvs within 1s window of corresponding sends
                make_record(2200000, DIR_S2C, 0x05,
                            make_recv_packet_body(CLIENT_KEY, b"r1")),
                make_record(2700000, DIR_S2C, 0x05,
                            make_recv_packet_body(CLIENT_KEY, b"r2")),
                make_record(3300000, DIR_S2C, 0x05,
                            make_recv_packet_body(CLIENT_KEY, b"r3")),
            ]
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)

            assert len(out["traffic_correlations"]) >= 1
            corr = out["traffic_correlations"][0]
            assert corr["src_peer"] == CLIENT_KEY.hex()
            assert corr["dst_peer"] == DEST_KEY_A.hex()
            # Multiple timing matches should be counted
            assert corr["correlated_packets"] >= 3
        finally:
            shutil.rmtree(dir_path)


# ===========================================================================
# Threat classification tests (with risk scoring)
# ===========================================================================


class TestThreatClassification:
    """Test per-peer threat level classification via multi-signal synthesis."""

    def test_critical_threat_blocklisted(self):
        """Blocklisted peer receives critical threat level with risk_score=60."""
        dir_path = tempfile.mkdtemp()
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)

        try:
            records = valid_handshake_records(nonce=b"\x11" * 24)
            write_capture_to(records, os.path.join(dir_path, "relay-alpha.dpcap"))

            create_test_db(db_path,
                relays=[("relay-alpha", "us-east", "derp1.example.com", 100)],
                blocklist=[(CLIENT_KEY.hex(), "compromised", "2024-01-15")])

            out = run_dir_analyzer(dir_path, db_path)

            ck = CLIENT_KEY.hex()
            assert ck in out["peer_threat_levels"]
            assert out["peer_threat_levels"][ck]["level"] == "critical"
            assert out["peer_threat_levels"][ck]["risk_score"] == 60
            assert "blocked_peer" in out["peer_threat_levels"][ck]["signals"]
        finally:
            shutil.rmtree(dir_path)
            os.unlink(db_path)

    def test_high_threat_nonce_reuse(self):
        """Nonce reuse across relays produces high threat level with risk_score=40."""
        dir_path = tempfile.mkdtemp()
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        shared_nonce = b"\xcc" * 24

        try:
            records_a = [
                make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(1100000, DIR_C2S, 0x02,
                            make_client_info_body(nonce=shared_nonce)),
                make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
            ]
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            records_b = [
                make_record(2000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(2100000, DIR_C2S, 0x02,
                            make_client_info_body(nonce=shared_nonce)),
                make_record(2200000, DIR_S2C, 0x03, make_server_info_body()),
            ]
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            create_test_db(db_path,
                relays=[("relay-alpha", "us-east", "derp1.example.com", 100),
                        ("relay-beta", "us-west", "derp2.example.com", 100)],
                policies=[(CLIENT_KEY.hex(), "testuser",
                           "relay-alpha,relay-beta", None, 2)])

            out = run_dir_analyzer(dir_path, db_path)

            ck = CLIENT_KEY.hex()
            assert out["peer_threat_levels"][ck]["level"] == "high"
            assert out["peer_threat_levels"][ck]["risk_score"] == 40
            assert "nonce_reuse" in out["peer_threat_levels"][ck]["signals"]
        finally:
            shutil.rmtree(dir_path)
            os.unlink(db_path)

    def test_medium_threat_unauthorized_relay(self):
        """Unauthorized relay use produces medium threat level with risk_score=20."""
        dir_path = tempfile.mkdtemp()
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)

        try:
            records = valid_handshake_records(nonce=b"\x22" * 24)
            write_capture_to(records, os.path.join(dir_path, "relay-beta.dpcap"))

            create_test_db(db_path,
                relays=[("relay-alpha", "us-east", "derp1.example.com", 100),
                        ("relay-beta", "us-west", "derp2.example.com", 100)],
                policies=[(CLIENT_KEY.hex(), "testuser", "relay-alpha", None, 1)])

            out = run_dir_analyzer(dir_path, db_path)

            ck = CLIENT_KEY.hex()
            assert out["peer_threat_levels"][ck]["level"] == "medium"
            assert out["peer_threat_levels"][ck]["risk_score"] == 20
            assert "unauthorized_relay" in out["peer_threat_levels"][ck]["signals"]
        finally:
            shutil.rmtree(dir_path)
            os.unlink(db_path)

    def test_low_threat_session_conflict(self):
        """Cross-relay session conflict alone produces low threat level with risk_score=10."""
        dir_path = tempfile.mkdtemp()
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)

        try:
            # Overlapping sessions with different nonces (no nonce reuse)
            records_a = valid_handshake_records(start_ts=1000000, nonce=b"\x33" * 24)
            records_a.append(make_record(5000000, DIR_S2C, 0x06, b""))
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            records_b = valid_handshake_records(start_ts=3000000, nonce=b"\x44" * 24)
            records_b.append(make_record(7000000, DIR_S2C, 0x06, b""))
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            create_test_db(db_path,
                relays=[("relay-alpha", "us-east", "derp1.example.com", 100),
                        ("relay-beta", "us-west", "derp2.example.com", 100)],
                policies=[(CLIENT_KEY.hex(), "testuser",
                           "relay-alpha,relay-beta", None, 2)])

            out = run_dir_analyzer(dir_path, db_path)

            ck = CLIENT_KEY.hex()
            assert out["peer_threat_levels"][ck]["level"] == "low"
            assert out["peer_threat_levels"][ck]["risk_score"] == 10
            assert "cross_relay_conflict" in out["peer_threat_levels"][ck]["signals"]
        finally:
            shutil.rmtree(dir_path)
            os.unlink(db_path)

    def test_none_threat_compliant(self):
        """Compliant peer with no issues receives none threat level with risk_score=0."""
        dir_path = tempfile.mkdtemp()
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)

        try:
            records = valid_handshake_records(nonce=b"\x55" * 24)
            write_capture_to(records, os.path.join(dir_path, "relay-alpha.dpcap"))

            create_test_db(db_path,
                relays=[("relay-alpha", "us-east", "derp1.example.com", 100)],
                policies=[(CLIENT_KEY.hex(), "testuser", "relay-alpha", None, 1)])

            out = run_dir_analyzer(dir_path, db_path)

            ck = CLIENT_KEY.hex()
            assert out["peer_threat_levels"][ck]["level"] == "none"
            assert out["peer_threat_levels"][ck]["risk_score"] == 0
            assert out["peer_threat_levels"][ck]["signals"] == []
        finally:
            shutil.rmtree(dir_path)
            os.unlink(db_path)

    def test_critical_overrides_high(self):
        """Blocklist (critical=60) + nonce reuse (high=40) = risk_score=100, level=critical."""
        dir_path = tempfile.mkdtemp()
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        shared_nonce = b"\x66" * 24

        try:
            records_a = [
                make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(1100000, DIR_C2S, 0x02,
                            make_client_info_body(nonce=shared_nonce)),
                make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
            ]
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            records_b = [
                make_record(2000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(2100000, DIR_C2S, 0x02,
                            make_client_info_body(nonce=shared_nonce)),
                make_record(2200000, DIR_S2C, 0x03, make_server_info_body()),
            ]
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            create_test_db(db_path,
                relays=[("relay-alpha", "us-east", "derp1.example.com", 100),
                        ("relay-beta", "us-west", "derp2.example.com", 100)],
                blocklist=[(CLIENT_KEY.hex(), "compromised", "2024-06-01")])

            out = run_dir_analyzer(dir_path, db_path)

            ck = CLIENT_KEY.hex()
            # Critical overrides high — total score = 60 + 40 = 100
            assert out["peer_threat_levels"][ck]["level"] == "critical"
            assert out["peer_threat_levels"][ck]["risk_score"] == 100
            # Both signals present
            assert "blocked_peer" in out["peer_threat_levels"][ck]["signals"]
            assert "nonce_reuse" in out["peer_threat_levels"][ck]["signals"]
        finally:
            shutil.rmtree(dir_path)
            os.unlink(db_path)

    def test_ghost_traffic_affects_threat(self):
        """Ghost traffic on a relay feeds ghost_traffic signal into threat classification."""
        dir_path = tempfile.mkdtemp()

        try:
            # Relay Alpha: CLIENT_KEY connects, PeerPresent/PeerGone/RecvPacket for SRC_KEY_C
            records_a = valid_handshake_records(start_ts=1000000)
            records_a.append(make_record(2000000, DIR_S2C, 0x09,
                                         make_peer_present_body(SRC_KEY_C)))
            records_a.append(make_record(3000000, DIR_S2C, 0x08,
                                         make_peer_gone_body(SRC_KEY_C)))
            records_a.append(make_record(4000000, DIR_S2C, 0x05,
                                         make_recv_packet_body(SRC_KEY_C)))
            write_capture_to(records_a, os.path.join(dir_path, "relay-alpha.dpcap"))

            # Relay Beta: SRC_KEY_C is a client (so it appears in peer threat levels)
            records_b = [
                make_record(1000000, DIR_S2C, 0x01, make_server_key_body()),
                make_record(1100000, DIR_C2S, 0x02,
                            make_client_info_body(key=SRC_KEY_C, nonce=b"\xaa" * 24)),
                make_record(1200000, DIR_S2C, 0x03, make_server_info_body()),
            ]
            write_capture_to(records_b, os.path.join(dir_path, "relay-beta.dpcap"))

            out = run_dir_analyzer(dir_path)

            sk = SRC_KEY_C.hex()
            assert sk in out["peer_threat_levels"]
            assert "ghost_traffic" in out["peer_threat_levels"][sk]["signals"]
            assert out["peer_threat_levels"][sk]["risk_score"] == 15
            assert out["peer_threat_levels"][sk]["level"] == "low"
        finally:
            shutil.rmtree(dir_path)


# ===========================================================================
# Directory output completeness test
# ===========================================================================


class TestDirectoryOutputSchema:
    """Verify directory mode output includes all required cross-relay fields."""

    def test_directory_output_has_all_sections(self):
        """Directory output must include all security assessment sections."""
        dir_path = tempfile.mkdtemp()
        try:
            records = valid_handshake_records(nonce=b"\x77" * 24)
            write_capture_to(records, os.path.join(dir_path, "relay-alpha.dpcap"))

            out = run_dir_analyzer(dir_path)

            assert "mode" in out
            assert out["mode"] == "directory"
            assert "relay_reports" in out
            assert "topology" in out
            assert "policy_violations" in out
            assert "cross_relay_conflicts" in out
            assert "nonce_reuse_alerts" in out
            assert "bridge_peers" in out
            assert "traffic_correlations" in out
            assert "peer_threat_levels" in out

            # Relay reports should contain session boundaries
            rr = out["relay_reports"]["relay-alpha"]
            assert "session_count" in rr
            assert "session_boundaries" in rr
            assert rr["session_count"] == 1

            # Peer threat levels should have risk_score
            for pk, tl in out["peer_threat_levels"].items():
                assert "risk_score" in tl
                assert "level" in tl
                assert "signals" in tl
                assert isinstance(tl["risk_score"], int)
                assert 0 <= tl["risk_score"] <= 100
        finally:
            shutil.rmtree(dir_path)
