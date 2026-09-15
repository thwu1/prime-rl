#!/usr/bin/env python3

"""DERP Mesh Relay Forensics Tool — Reference Implementation"""

import argparse
import json
import os
import sqlite3
import struct
import subprocess
import sys
from collections import defaultdict

DPCAP_MAGIC = b"DPCAP\x01"
DERP_MAGIC = b"DERP\xf0\x9f\x94\x91"
KEEPALIVE_THRESHOLD_US = 120_000_000
CORRELATION_WINDOW_US = 1_000_000

FRAME_TYPES = {
    0x01: "ServerKey",
    0x02: "ClientInfo",
    0x03: "ServerInfo",
    0x04: "SendPacket",
    0x05: "RecvPacket",
    0x06: "KeepAlive",
    0x07: "NotePreferred",
    0x08: "PeerGone",
    0x09: "PeerPresent",
    0x0A: "ForwardPacket",
    0x10: "WatchConns",
    0x11: "ClosePeer",
    0x12: "Ping",
    0x13: "Pong",
    0x14: "Health",
    0x15: "Restarting",
}

SIGNAL_WEIGHTS = {
    "blocked_peer": 60,
    "nonce_reuse": 40,
    "unauthorized_relay": 20,
    "ghost_traffic": 15,
    "unauthorized_destination": 15,
    "cross_relay_conflict": 10,
}

DIR_SERVER_TO_CLIENT = 0x00
DIR_CLIENT_TO_SERVER = 0x01
DATA_FRAME_TYPES = {"SendPacket", "RecvPacket", "ForwardPacket"}


def read_exact(f, n):
    data = f.read(n)
    if len(data) != n:
        raise ValueError(f"Expected {n} bytes, got {len(data)}")
    return data


def parse_capture(filepath):
    """Parse a DPCAP v1 capture file and return list of records."""
    records = []
    with open(filepath, "rb") as f:
        magic = f.read(6)
        if magic != DPCAP_MAGIC:
            raise ValueError(f"Invalid DPCAP magic: {magic!r}")
        while True:
            ts_bytes = f.read(8)
            if len(ts_bytes) == 0:
                break
            if len(ts_bytes) < 8:
                raise ValueError("Truncated timestamp")
            timestamp = struct.unpack("!Q", ts_bytes)[0]
            direction = struct.unpack("!B", read_exact(f, 1))[0]
            frame_type_byte = struct.unpack("!B", read_exact(f, 1))[0]
            body_length = struct.unpack("!I", read_exact(f, 4))[0]
            body = read_exact(f, body_length)
            records.append({
                "timestamp": timestamp,
                "direction": direction,
                "frame_type_byte": frame_type_byte,
                "frame_type_name": FRAME_TYPES.get(frame_type_byte, "Unknown"),
                "body": body,
                "body_length": body_length,
            })
    return records


def parse_raw_frames(raw_bytes):
    """Parse raw DERP frames (no DPCAP wrapper). For pcap mode."""
    records = []
    offset = 0
    while offset < len(raw_bytes):
        if offset + 5 > len(raw_bytes):
            break
        frame_type_byte = raw_bytes[offset]
        body_length = struct.unpack_from("!I", raw_bytes, offset + 1)[0]
        offset += 5
        if offset + body_length > len(raw_bytes):
            break
        body = raw_bytes[offset:offset + body_length]
        offset += body_length
        records.append({
            "timestamp": None,
            "direction": None,
            "frame_type_byte": frame_type_byte,
            "frame_type_name": FRAME_TYPES.get(frame_type_byte, "Unknown"),
            "body": body,
            "body_length": body_length,
        })
    return records


def analyze(records, skip_direction_checks=False):
    """Analyze parsed records and produce the output report.

    Supports multi-session detection, ghost traffic detection via
    PeerPresent/PeerGone lifecycle tracking, and full anomaly analysis.
    """
    result = {
        "session": {
            "start_time_us": 0,
            "end_time_us": 0,
            "duration_us": 0,
            "total_frames": 0,
        },
        "handshake": {
            "valid": False,
            "server_key": None,
            "client_key": None,
            "client_nonce": None,
            "violations": [],
        },
        "frame_counts": {},
        "routing": {
            "send_packets": {},
            "recv_packets": {},
            "forward_packets": 0,
        },
        "keepalive": {
            "count": 0,
            "max_gap_us": None,
            "threshold_exceeded": False,
        },
        "ping_pong": {
            "pings": 0,
            "pongs": 0,
            "matched": 0,
            "unmatched_pings": 0,
        },
        "anomalies": [],
        "session_count": 0,
        "session_boundaries": [],
    }

    if not records:
        result["handshake"]["valid"] = False
        result["handshake"]["violations"].append("invalid_handshake: no frames in capture")
        result["anomalies"].append("invalid_handshake: no frames in capture")
        return result

    # Aggregate session info
    timestamps = [r["timestamp"] for r in records if r["timestamp"] is not None]
    if timestamps:
        result["session"]["start_time_us"] = timestamps[0]
        result["session"]["end_time_us"] = timestamps[-1]
        result["session"]["duration_us"] = timestamps[-1] - timestamps[0]
    result["session"]["total_frames"] = len(records)

    # Aggregate frame counts
    frame_counts = defaultdict(int)
    for r in records:
        frame_counts[r["frame_type_name"]] += 1
    result["frame_counts"] = dict(frame_counts)

    # Per-session handshake state
    handshake_step = 0
    handshake_valid = True
    server_key = None
    client_key = None
    client_nonce = None
    handshake_violations = []
    session_start_idx = 0

    # Multi-session tracking
    all_sessions = []
    first_session_saved = False
    all_handshake_violations = []

    # Ghost traffic: peer lifecycle tracking
    gone_peers = set()

    # Global analysis state
    keepalive_timestamps = []
    ping_payloads = []
    pong_payloads = set()
    ping_payload_counts = defaultdict(int)
    send_packets = defaultdict(int)
    recv_packets = defaultdict(int)
    forward_count = 0
    anomalies = []

    for i, r in enumerate(records):
        ft = r["frame_type_name"]
        direction = r["direction"]
        body = r["body"]
        ts = r["timestamp"]

        if ft == "Unknown":
            anomalies.append(f"unknown_frame_type: frame {i} has type 0x{r['frame_type_byte']:02x}")

        # Multi-session detection: new ServerKey after completed handshake
        if ft == "ServerKey" and handshake_step == 3:
            prev_ts = 0
            if i > 0 and records[i - 1]["timestamp"] is not None:
                prev_ts = records[i - 1]["timestamp"]
            start_ts = 0
            if records[session_start_idx]["timestamp"] is not None:
                start_ts = records[session_start_idx]["timestamp"]

            all_sessions.append({
                "start_time_us": start_ts,
                "end_time_us": prev_ts,
                "handshake_valid": handshake_valid,
                "client_key": client_key,
                "server_key": server_key,
                "client_nonce": client_nonce,
            })

            if not first_session_saved:
                result["handshake"]["valid"] = handshake_valid
                result["handshake"]["server_key"] = server_key
                result["handshake"]["client_key"] = client_key
                result["handshake"]["client_nonce"] = client_nonce
                result["handshake"]["violations"] = handshake_violations[:]
                first_session_saved = True

            all_handshake_violations.extend(handshake_violations)

            # Reset state for new session
            session_start_idx = i
            handshake_step = 0
            handshake_valid = True
            server_key = None
            client_key = None
            client_nonce = None
            handshake_violations = []
            gone_peers.clear()  # Reset peer lifecycle on session boundary

        # Handshake state machine (runs when handshake not yet complete)
        if handshake_step < 3:
            if ft in DATA_FRAME_TYPES:
                anomalies.append(f"pre_handshake_data: {ft} at frame {i} before handshake completion")
                if handshake_valid:
                    handshake_valid = False
                    handshake_violations.append(f"invalid_handshake: {ft} before handshake completion")

            if ft == "ServerKey":
                if handshake_step == 0:
                    if not skip_direction_checks and direction is not None and direction != DIR_SERVER_TO_CLIENT:
                        handshake_valid = False
                        handshake_violations.append("invalid_handshake: ServerKey not from server")
                    else:
                        if len(body) >= 40:
                            magic = body[:8]
                            if magic != DERP_MAGIC:
                                anomalies.append(f"bad_magic: ServerKey frame {i} has magic {magic.hex()}")
                            server_key = body[8:40].hex()
                        else:
                            handshake_valid = False
                            handshake_violations.append("invalid_handshake: ServerKey body too short")
                        handshake_step = 1

            elif ft == "ClientInfo":
                if handshake_step == 1:
                    if not skip_direction_checks and direction is not None and direction != DIR_CLIENT_TO_SERVER:
                        handshake_valid = False
                        handshake_violations.append("invalid_handshake: ClientInfo not from client")
                    else:
                        if len(body) >= 32:
                            client_key = body[:32].hex()
                        else:
                            handshake_valid = False
                            handshake_violations.append("invalid_handshake: ClientInfo body too short")
                        if len(body) >= 56:
                            client_nonce = body[32:56].hex()
                        handshake_step = 2
                elif handshake_step == 0:
                    handshake_valid = False
                    handshake_violations.append("invalid_handshake: ClientInfo before ServerKey")
                    if len(body) >= 32:
                        client_key = body[:32].hex()
                    if len(body) >= 56:
                        client_nonce = body[32:56].hex()
                    handshake_step = 2

            elif ft == "ServerInfo":
                if handshake_step == 2:
                    if not skip_direction_checks and direction is not None and direction != DIR_SERVER_TO_CLIENT:
                        handshake_valid = False
                        handshake_violations.append("invalid_handshake: ServerInfo not from server")
                    else:
                        handshake_step = 3
                elif handshake_step < 2:
                    handshake_valid = False
                    handshake_violations.append("invalid_handshake: ServerInfo before ClientInfo")
                    handshake_step = 3

        # Peer lifecycle tracking for ghost traffic detection
        if ft == "PeerPresent" and len(body) >= 32:
            gone_peers.discard(body[:32].hex())
        elif ft == "PeerGone" and len(body) >= 32:
            gone_peers.add(body[:32].hex())

        # Process frame content regardless of handshake state
        if ft == "SendPacket" and len(body) >= 32:
            dest_hex = body[:32].hex()
            send_packets[dest_hex] += 1
            if dest_hex in gone_peers:
                anomalies.append(f"ghost_send: {dest_hex}")

        elif ft == "RecvPacket" and len(body) >= 32:
            src_hex = body[:32].hex()
            recv_packets[src_hex] += 1
            if src_hex in gone_peers:
                anomalies.append(f"ghost_recv: {src_hex}")

        elif ft == "ForwardPacket":
            forward_count += 1

        elif ft == "KeepAlive":
            if ts is not None:
                keepalive_timestamps.append(ts)

        elif ft == "Ping" and len(body) == 8:
            ping_payloads.append(body)
            ping_payload_counts[body] += 1

        elif ft == "Pong" and len(body) == 8:
            pong_payloads.add(body)

    # Check if final session's handshake is incomplete
    if handshake_step < 3 and handshake_valid:
        handshake_valid = False
        handshake_violations.append("invalid_handshake: handshake incomplete")

    # Save final session
    if records:
        last_ts = 0
        for r in reversed(records):
            if r["timestamp"] is not None:
                last_ts = r["timestamp"]
                break
        start_ts = 0
        if session_start_idx < len(records):
            st = records[session_start_idx]["timestamp"]
            if st is not None:
                start_ts = st

        all_sessions.append({
            "start_time_us": start_ts,
            "end_time_us": last_ts,
            "handshake_valid": handshake_valid,
            "client_key": client_key,
            "server_key": server_key,
            "client_nonce": client_nonce,
        })

    # Set main handshake section from first session if not already set
    if not first_session_saved:
        result["handshake"]["valid"] = handshake_valid
        result["handshake"]["server_key"] = server_key
        result["handshake"]["client_key"] = client_key
        result["handshake"]["client_nonce"] = client_nonce
        result["handshake"]["violations"] = handshake_violations

    all_handshake_violations.extend(handshake_violations)

    # Add all handshake violations to anomalies
    for v in all_handshake_violations:
        if v not in anomalies:
            anomalies.append(v)

    # Session boundaries
    result["session_count"] = len(all_sessions)
    result["session_boundaries"] = all_sessions

    # Routing
    result["routing"]["send_packets"] = dict(send_packets)
    result["routing"]["recv_packets"] = dict(recv_packets)
    result["routing"]["forward_packets"] = forward_count

    # KeepAlive analysis
    result["keepalive"]["count"] = len(keepalive_timestamps)
    if len(keepalive_timestamps) >= 2:
        gaps = [keepalive_timestamps[j] - keepalive_timestamps[j - 1]
                for j in range(1, len(keepalive_timestamps))]
        max_gap = max(gaps)
        result["keepalive"]["max_gap_us"] = max_gap
        if max_gap > KEEPALIVE_THRESHOLD_US:
            result["keepalive"]["threshold_exceeded"] = True
            anomalies.append(f"keepalive_gap: max gap {max_gap} us exceeds threshold")

    # Ping/Pong analysis
    pings_total = len(ping_payloads)
    pongs_total = frame_counts.get("Pong", 0)
    matched = 0
    unmatched = 0
    for payload in ping_payloads:
        if payload in pong_payloads:
            matched += 1
        else:
            unmatched += 1

    result["ping_pong"]["pings"] = pings_total
    result["ping_pong"]["pongs"] = pongs_total
    result["ping_pong"]["matched"] = matched
    result["ping_pong"]["unmatched_pings"] = unmatched

    if unmatched > 0:
        anomalies.append(f"unmatched_ping: {unmatched} ping(s) without matching pong")

    for payload, count in ping_payload_counts.items():
        if count > 1:
            anomalies.append(f"duplicate_ping: payload {payload.hex()} seen {count} times")

    result["anomalies"] = anomalies
    return result


def analyze_pcap(pcap_path):
    """Process pcap file using tshark to extract DERP frames."""
    for field in ["tcp.payload", "data.data"]:
        proc = subprocess.run(
            ["tshark", "-r", pcap_path,
             "-o", "tcp.check_checksum:FALSE",
             "-T", "fields", "-e", field,
             "-Y", "tcp", "-Q"],
            capture_output=True, text=True, timeout=30
        )
        if proc.returncode == 0 and proc.stdout.strip():
            break
    else:
        raise RuntimeError(f"tshark failed to extract TCP payloads: {proc.stderr}")

    hex_lines = proc.stdout.strip().split("\n")
    raw_bytes = b""
    for line in hex_lines:
        line = line.strip()
        if line:
            raw_bytes += bytes.fromhex(line.replace(":", ""))

    records = parse_raw_frames(raw_bytes)
    report = analyze(records, skip_direction_checks=True)
    report["mode"] = "pcap"
    return report


def analyze_single_file(filepath):
    """Analyze a single DPCAP file."""
    records = parse_capture(filepath)
    return analyze(records)


def build_topology(relay_reports):
    """Build mesh topology from relay reports, including multi-session peers."""
    peers = defaultdict(lambda: {
        "relays": set(), "destinations": set(),
        "total_packets_sent": 0, "total_packets_received": 0
    })

    for relay_id, report in relay_reports.items():
        # Collect all client keys from all sessions on this relay
        client_keys = set()
        ck = report["handshake"]["client_key"]
        if ck:
            client_keys.add(ck)
        for session in report.get("session_boundaries", []):
            sk = session.get("client_key")
            if sk:
                client_keys.add(sk)

        for k in client_keys:
            peers[k]["relays"].add(relay_id)

        # Attribute routing to primary client key
        primary_ck = report["handshake"]["client_key"]
        if primary_ck:
            for dk, cnt in report["routing"]["send_packets"].items():
                peers[primary_ck]["destinations"].add(dk)
                peers[primary_ck]["total_packets_sent"] += cnt
            for sk, cnt in report["routing"]["recv_packets"].items():
                peers[primary_ck]["total_packets_received"] += cnt

    result_peers = {}
    for k, v in peers.items():
        result_peers[k] = {
            "relays": sorted(v["relays"]),
            "destinations": sorted(v["destinations"]),
            "total_packets_sent": v["total_packets_sent"],
            "total_packets_received": v["total_packets_received"],
        }

    relay_peer_counts = {}
    for relay_id, report in relay_reports.items():
        unique_peers = set()
        ck = report["handshake"]["client_key"]
        if ck:
            unique_peers.add(ck)
        for session in report.get("session_boundaries", []):
            sk = session.get("client_key")
            if sk:
                unique_peers.add(sk)
        for k in report["routing"]["send_packets"]:
            unique_peers.add(k)
        for k in report["routing"]["recv_packets"]:
            unique_peers.add(k)
        relay_peer_counts[relay_id] = len(unique_peers)

    return {"peers": result_peers, "relay_peer_counts": relay_peer_counts}


def check_policies(relay_reports, db_path):
    """Check session data against SQLite policy database."""
    violations = []
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    for relay_id, report in sorted(relay_reports.items()):
        ck = report["handshake"]["client_key"]
        if not ck:
            continue

        # Check blocklist
        c.execute("SELECT reason FROM blocklist WHERE peer_key_hex = ?", (ck,))
        row = c.fetchone()
        if row:
            violations.append({
                "type": "blocked_peer",
                "peer_key": ck,
                "relay_id": relay_id,
                "detail": f"Peer is blocklisted: {row[0]}"
            })

        # Check relay authorization
        c.execute("SELECT allowed_relay_ids FROM peer_policies WHERE peer_key_hex = ?", (ck,))
        row = c.fetchone()
        if row:
            allowed = [r.strip() for r in row[0].split(",")]
            if relay_id not in allowed:
                violations.append({
                    "type": "unauthorized_relay",
                    "peer_key": ck,
                    "relay_id": relay_id,
                    "detail": f"Peer not authorized for relay {relay_id}; allowed: {','.join(allowed)}"
                })

        # Check destination authorization
        c.execute("SELECT allowed_dest_keys FROM peer_policies WHERE peer_key_hex = ?", (ck,))
        row = c.fetchone()
        if row and row[0]:
            allowed_dests = set(d.strip() for d in row[0].split(","))
            for dk in sorted(report["routing"]["send_packets"].keys()):
                if dk not in allowed_dests:
                    violations.append({
                        "type": "unauthorized_destination",
                        "peer_key": ck,
                        "relay_id": relay_id,
                        "destination_key": dk,
                        "detail": f"Destination {dk[:16]}... not in allowed list"
                    })

    conn.close()
    return violations


def detect_cross_relay_conflicts(relay_reports):
    """Detect same peer with overlapping sessions on different relays."""
    peer_sessions = defaultdict(list)
    for relay_id, report in relay_reports.items():
        for session in report.get("session_boundaries", []):
            ck = session.get("client_key")
            if ck:
                start = session.get("start_time_us", 0)
                end = session.get("end_time_us", 0)
                if start is not None and end is not None:
                    peer_sessions[ck].append((relay_id, start, end))

    conflicts = []
    for pk, sessions in sorted(peer_sessions.items()):
        if len(sessions) < 2:
            continue
        for i in range(len(sessions)):
            for j in range(i + 1, len(sessions)):
                r1, s1, e1 = sessions[i]
                r2, s2, e2 = sessions[j]
                if r1 == r2:
                    continue
                overlap_start = max(s1, s2)
                overlap_end = min(e1, e2)
                if overlap_start < overlap_end:
                    conflicts.append({
                        "peer_key": pk,
                        "relays": sorted([r1, r2]),
                        "time_overlap_us": [overlap_start, overlap_end]
                    })

    return conflicts


def detect_nonce_reuse(relay_reports):
    """Detect same client key presenting identical nonces on different relays."""
    nonce_map = defaultdict(lambda: defaultdict(set))

    for relay_id, report in sorted(relay_reports.items()):
        for session in report.get("session_boundaries", []):
            ck = session.get("client_key")
            nonce = session.get("client_nonce")
            if ck and nonce:
                nonce_map[ck][nonce].add(relay_id)

    alerts = []
    for peer_key in sorted(nonce_map.keys()):
        for nonce_hex in sorted(nonce_map[peer_key].keys()):
            relay_ids = nonce_map[peer_key][nonce_hex]
            if len(relay_ids) > 1:
                alerts.append({
                    "peer_key": peer_key,
                    "nonce_hex": nonce_hex,
                    "relays": sorted(relay_ids),
                })

    return alerts


def find_bridge_peers(relay_reports):
    """Identify peers bridging relay segments."""
    client_relays = defaultdict(set)
    target_relays = defaultdict(set)

    for relay_id, report in relay_reports.items():
        ck = report["handshake"]["client_key"]
        if ck:
            client_relays[ck].add(relay_id)
        for session in report.get("session_boundaries", []):
            sk = session.get("client_key")
            if sk:
                client_relays[sk].add(relay_id)

        for dk in report["routing"]["send_packets"]:
            target_relays[dk].add(relay_id)
        for sk in report["routing"]["recv_packets"]:
            target_relays[sk].add(relay_id)

    bridge = []
    for key in sorted(set(client_relays.keys()) & set(target_relays.keys())):
        if target_relays[key] - client_relays[key]:
            bridge.append(key)

    return bridge


def detect_traffic_correlations(relay_reports, relay_raw_records):
    """Detect relay-mediated communication paths via cross-relay timing correlation.

    A correlation exists when peer A sends to peer D on relay R1 at time T1,
    and peer D receives from peer A on relay R2 at time T2, with |T1-T2| < 1 second.
    """
    # Build per-relay event lists with timestamps
    relay_events = {}
    for relay_id, records in relay_raw_records.items():
        client_key = relay_reports[relay_id]["handshake"]["client_key"]
        sends = []
        recvs = []
        for r in records:
            if r["timestamp"] is None:
                continue
            if r["frame_type_name"] == "SendPacket" and len(r["body"]) >= 32:
                sends.append((r["body"][:32].hex(), r["timestamp"]))
            elif r["frame_type_name"] == "RecvPacket" and len(r["body"]) >= 32:
                recvs.append((r["body"][:32].hex(), r["timestamp"]))
        relay_events[relay_id] = {
            "client_key": client_key,
            "sends": sends,
            "recvs": recvs,
        }

    # Check all relay pairs for correlated flows
    correlations = {}

    for r1_id in sorted(relay_events.keys()):
        r1 = relay_events[r1_id]
        if not r1["client_key"]:
            continue
        for r2_id in sorted(relay_events.keys()):
            if r1_id == r2_id:
                continue
            r2 = relay_events[r2_id]
            if not r2["client_key"]:
                continue

            # Check: R1's client sends to R2's client, R2 receives from R1's client
            for dest_key, send_ts in r1["sends"]:
                if dest_key != r2["client_key"]:
                    continue
                for src_key, recv_ts in r2["recvs"]:
                    if src_key != r1["client_key"]:
                        continue
                    if abs(send_ts - recv_ts) < CORRELATION_WINDOW_US:
                        key = (r1["client_key"], r2["client_key"], r1_id, r2_id)
                        correlations[key] = correlations.get(key, 0) + 1

    result = []
    for (src, dst, sr, dr), count in sorted(correlations.items()):
        result.append({
            "src_peer": src,
            "dst_peer": dst,
            "src_relay": sr,
            "dst_relay": dr,
            "correlated_packets": count,
        })

    return result


def classify_threats(relay_reports, policy_violations, nonce_alerts, conflicts):
    """Synthesize all security signals into per-peer threat levels with risk scoring.

    Each signal has a weight. The risk_score is the sum of weights (capped at 100).
    Level thresholds: >=60=critical, >=40=high, >=20=medium, >=1=low, 0=none.
    """
    peer_signals = defaultdict(set)

    for v in policy_violations:
        peer_signals[v["peer_key"]].add(v["type"])

    for a in nonce_alerts:
        peer_signals[a["peer_key"]].add("nonce_reuse")

    for c in conflicts:
        peer_signals[c["peer_key"]].add("cross_relay_conflict")

    # Extract ghost traffic signals from relay anomalies
    for relay_id, report in relay_reports.items():
        for anomaly in report.get("anomalies", []):
            if anomaly.startswith("ghost_recv: "):
                peer_key = anomaly[len("ghost_recv: "):]
                peer_signals[peer_key].add("ghost_traffic")
            elif anomaly.startswith("ghost_send: "):
                peer_key = anomaly[len("ghost_send: "):]
                peer_signals[peer_key].add("ghost_traffic")

    # Collect all known peers (session clients)
    all_peers = set()
    for relay_id, report in relay_reports.items():
        ck = report["handshake"]["client_key"]
        if ck:
            all_peers.add(ck)
        for session in report.get("session_boundaries", []):
            sk = session.get("client_key")
            if sk:
                all_peers.add(sk)

    # Also include peers with ghost_traffic signals
    for peer_key in list(peer_signals.keys()):
        if "ghost_traffic" in peer_signals[peer_key]:
            all_peers.add(peer_key)

    threat_levels = {}
    for peer_key in sorted(all_peers):
        signals = peer_signals.get(peer_key, set())
        risk_score = min(100, sum(SIGNAL_WEIGHTS.get(s, 0) for s in signals))

        if risk_score >= 60:
            level = "critical"
        elif risk_score >= 40:
            level = "high"
        elif risk_score >= 20:
            level = "medium"
        elif risk_score >= 1:
            level = "low"
        else:
            level = "none"

        threat_levels[peer_key] = {
            "level": level,
            "risk_score": risk_score,
            "signals": sorted(signals),
        }

    return threat_levels


def analyze_directory(dir_path, db_path=None):
    """Analyze all DPCAP files in directory with cross-relay security assessment."""
    relay_reports = {}
    relay_raw_records = {}

    for fname in sorted(os.listdir(dir_path)):
        if fname.endswith(".dpcap"):
            relay_id = fname[:-6]
            fpath = os.path.join(dir_path, fname)
            records = parse_capture(fpath)
            relay_raw_records[relay_id] = records
            relay_reports[relay_id] = analyze(records)

    topology = build_topology(relay_reports)

    policy_violations = []
    if db_path and os.path.exists(db_path):
        policy_violations = check_policies(relay_reports, db_path)

    conflicts = detect_cross_relay_conflicts(relay_reports)
    nonce_alerts = detect_nonce_reuse(relay_reports)
    bridges = find_bridge_peers(relay_reports)
    correlations = detect_traffic_correlations(relay_reports, relay_raw_records)
    threat_levels = classify_threats(
        relay_reports, policy_violations, nonce_alerts, conflicts
    )

    return {
        "mode": "directory",
        "relay_reports": relay_reports,
        "topology": topology,
        "policy_violations": policy_violations,
        "cross_relay_conflicts": conflicts,
        "nonce_reuse_alerts": nonce_alerts,
        "bridge_peers": bridges,
        "traffic_correlations": correlations,
        "peer_threat_levels": threat_levels,
    }


def main():
    parser = argparse.ArgumentParser(description="DERP Mesh Relay Forensics")
    parser.add_argument("target", nargs="?", help="DPCAP file path (single-file mode)")
    parser.add_argument("--pcap", metavar="FILE", help="Process pcap file using tshark")
    parser.add_argument("--dir", metavar="DIR", help="Directory of DPCAP files (multi-relay mode)")
    parser.add_argument("--db", default="/app/relay_metadata.db",
                        help="SQLite database with relay metadata (default: /app/relay_metadata.db)")
    args = parser.parse_args()

    if args.pcap:
        result = analyze_pcap(args.pcap)
    elif args.dir:
        result = analyze_directory(args.dir, args.db)
    elif args.target:
        result = analyze_single_file(args.target)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
