#!/usr/bin/env python3

"""DERP Protocol Capture Analyzer - Reference Implementation"""

import json
import struct
import sys
from collections import defaultdict

DPCAP_MAGIC = b"DPCAP\x01"
DERP_MAGIC = b"DERP\xf0\x9f\x94\x91"  # "DERP" + U+1F511 (key emoji) in UTF-8
KEEPALIVE_THRESHOLD_US = 120_000_000  # 120 seconds in microseconds

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

            # Read frame header
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


def analyze(records):
    """Analyze parsed records and produce the output report."""
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
    }

    if not records:
        result["handshake"]["valid"] = False
        result["handshake"]["violations"].append("invalid_handshake: no frames in capture")
        result["anomalies"].append("invalid_handshake: no frames in capture")
        return result

    # Session info
    result["session"]["start_time_us"] = records[0]["timestamp"]
    result["session"]["end_time_us"] = records[-1]["timestamp"]
    result["session"]["duration_us"] = records[-1]["timestamp"] - records[0]["timestamp"]
    result["session"]["total_frames"] = len(records)

    # Frame counts
    frame_counts = defaultdict(int)
    for r in records:
        frame_counts[r["frame_type_name"]] += 1
    result["frame_counts"] = dict(frame_counts)

    # Handshake validation
    handshake_step = 0  # 0=waiting for ServerKey, 1=waiting for ClientInfo, 2=waiting for ServerInfo, 3=complete
    handshake_valid = True
    server_key = None
    client_key = None
    handshake_violations = []

    # Track data for other analyses
    keepalive_timestamps = []
    ping_payloads = []  # list of 8-byte payloads
    pong_payloads = set()  # set of 8-byte payloads
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

        # Check for unknown frame type
        if ft == "Unknown":
            anomalies.append(f"unknown_frame_type: frame {i} has type 0x{r['frame_type_byte']:02x}")

        # Handshake state machine
        if handshake_step < 3:
            if ft in DATA_FRAME_TYPES:
                anomalies.append(f"pre_handshake_data: {ft} at frame {i} before handshake completion")
                if handshake_valid:
                    handshake_valid = False
                    handshake_violations.append(f"invalid_handshake: {ft} before handshake completion")

            if ft == "ServerKey":
                if handshake_step == 0:
                    if direction != DIR_SERVER_TO_CLIENT:
                        handshake_valid = False
                        handshake_violations.append("invalid_handshake: ServerKey not from server")
                    else:
                        # Parse ServerKey body: 8B magic + 32B key
                        if len(body) >= 40:
                            magic = body[:8]
                            if magic != DERP_MAGIC:
                                anomalies.append(f"bad_magic: ServerKey frame {i} has magic {magic.hex()}")
                            server_key = body[8:40].hex()
                        else:
                            handshake_valid = False
                            handshake_violations.append("invalid_handshake: ServerKey body too short")
                        handshake_step = 1
                else:
                    # Duplicate ServerKey or out of order
                    pass  # Allow duplicate ServerKey after handshake step advances

            elif ft == "ClientInfo":
                if handshake_step == 1:
                    if direction != DIR_CLIENT_TO_SERVER:
                        handshake_valid = False
                        handshake_violations.append("invalid_handshake: ClientInfo not from client")
                    else:
                        if len(body) >= 32:
                            client_key = body[:32].hex()
                        else:
                            handshake_valid = False
                            handshake_violations.append("invalid_handshake: ClientInfo body too short")
                        handshake_step = 2
                elif handshake_step == 0:
                    handshake_valid = False
                    handshake_violations.append("invalid_handshake: ClientInfo before ServerKey")
                    # Still extract key if possible
                    if len(body) >= 32:
                        client_key = body[:32].hex()
                    handshake_step = 2

            elif ft == "ServerInfo":
                if handshake_step == 2:
                    if direction != DIR_SERVER_TO_CLIENT:
                        handshake_valid = False
                        handshake_violations.append("invalid_handshake: ServerInfo not from server")
                    else:
                        handshake_step = 3
                elif handshake_step < 2:
                    handshake_valid = False
                    handshake_violations.append("invalid_handshake: ServerInfo before ClientInfo")
                    handshake_step = 3

        # Process frame content regardless of handshake state
        if ft == "SendPacket" and len(body) >= 32:
            dest_key = body[:32].hex()
            send_packets[dest_key] += 1

        elif ft == "RecvPacket" and len(body) >= 32:
            src_key = body[:32].hex()
            recv_packets[src_key] += 1

        elif ft == "ForwardPacket":
            forward_count += 1

        elif ft == "KeepAlive":
            keepalive_timestamps.append(ts)

        elif ft == "Ping" and len(body) == 8:
            ping_payloads.append(body)
            ping_payload_counts[body] += 1

        elif ft == "Pong" and len(body) == 8:
            pong_payloads.add(body)

    # If handshake never completed
    if handshake_step < 3 and handshake_valid:
        handshake_valid = False
        handshake_violations.append("invalid_handshake: handshake incomplete")

    result["handshake"]["valid"] = handshake_valid
    result["handshake"]["server_key"] = server_key
    result["handshake"]["client_key"] = client_key
    result["handshake"]["violations"] = handshake_violations
    if handshake_violations:
        for v in handshake_violations:
            if v not in anomalies:
                anomalies.append(v)

    # Routing
    result["routing"]["send_packets"] = dict(send_packets)
    result["routing"]["recv_packets"] = dict(recv_packets)
    result["routing"]["forward_packets"] = forward_count

    # KeepAlive analysis
    result["keepalive"]["count"] = len(keepalive_timestamps)
    if len(keepalive_timestamps) >= 2:
        gaps = []
        for j in range(1, len(keepalive_timestamps)):
            gaps.append(keepalive_timestamps[j] - keepalive_timestamps[j - 1])
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

    # Check duplicate ping payloads
    for payload, count in ping_payload_counts.items():
        if count > 1:
            anomalies.append(f"duplicate_ping: payload {payload.hex()} seen {count} times")

    result["anomalies"] = anomalies
    return result


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <capture_file>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    records = parse_capture(filepath)
    report = analyze(records)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
