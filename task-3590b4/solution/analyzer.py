#!/usr/bin/env python3
"""DERP relay mesh forensic analyzer.

Parses binary DERP captures from two relay nodes, correlates peer keys
with a WireGuard configuration (base64 -> hex conversion), evaluates an
authorization policy, and produces a structured audit report.
"""

import struct
import json
import base64

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

CLIENT_FRAMES = {
    "ClientInfo", "SendPacket", "NotePreferred", "WatchConns",
    "ClosePeer", "ForwardPacket", "Ping", "Pong",
}

ROLE_ORDER = ["client", "mesh", "admin"]

KEY_LEN = 32
MAGIC_LEN = 8


def parse_frames(data):
    """Parse DERP frames from raw binary data."""
    frames = []
    offset = 0
    while offset + 5 <= len(data):
        ftype = data[offset]
        plen = struct.unpack(">I", data[offset + 1:offset + 5])[0]
        offset += 5
        if offset + plen > len(data):
            break
        payload = data[offset:offset + plen]
        offset += plen
        name = FRAME_TYPES.get(ftype, f"Unknown_0x{ftype:02x}")
        frames.append((name, payload))
    return frames


def split_sessions(frames):
    """Split a frame list into sessions delimited by ServerKey frames."""
    sessions = []
    current = []
    for frame in frames:
        if frame[0] == "ServerKey":
            if current:
                sessions.append(current)
            current = [frame]
        else:
            current.append(frame)
    if current:
        sessions.append(current)
    return sessions


def read_wg_config(path):
    """Read WireGuard config and return a map of hex pubkey -> peer name."""
    peer_key_map = {}
    current_name = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("# ") and current_name is None:
                current_name = line[2:]
            elif line.startswith("PublicKey = ") and current_name:
                pub_b64 = line[len("PublicKey = "):]
                pub_hex = base64.b64decode(pub_b64).hex()
                peer_key_map[pub_hex] = current_name
                current_name = None
            elif line.startswith("["):
                if not line.startswith("[Peer]"):
                    current_name = None
    return peer_key_map


def analyze_node(capture_path, node_name, peer_key_map, policy, results):
    """Analyze one node's binary capture and populate results."""
    with open(capture_path, "rb") as f:
        data = f.read()

    frames = parse_frames(data)
    sessions = split_sessions(frames)

    # Frame type counts
    ftc = {}
    for name, _ in frames:
        ftc[name] = ftc.get(name, 0) + 1

    # Data byte totals
    send_b = recv_b = fwd_b = 0
    for name, payload in frames:
        if name == "SendPacket":
            send_b += max(0, len(payload) - KEY_LEN)
        elif name == "RecvPacket":
            recv_b += max(0, len(payload) - KEY_LEN)
        elif name == "ForwardPacket":
            fwd_b += max(0, len(payload) - 2 * KEY_LEN)

    node_result = {
        "total_frames": len(frames),
        "session_count": len(sessions),
        "frame_type_counts": ftc,
        "data_bytes": {"send": send_b, "recv": recv_b, "forward": fwd_b},
    }

    # Per-session analysis
    node_peers = set()
    for sess_idx, session in enumerate(sessions):
        # Locate ClientInfo to identify the session peer
        peer_key_hex = None
        ci_idx = None
        for i, (name, payload) in enumerate(session):
            if name == "ClientInfo" and len(payload) >= KEY_LEN:
                peer_key_hex = payload[:KEY_LEN].hex()
                ci_idx = i
                node_peers.add(peer_key_hex)
                break

        # Protocol violations: client frames before ClientInfo
        if ci_idx is not None:
            for i, (name, _) in enumerate(session):
                if i < ci_idx and name in CLIENT_FRAMES and name != "ClientInfo":
                    results["protocol_violations"].append({
                        "node": node_name,
                        "session_index": sess_idx,
                        "violation": f"{name} before ClientInfo",
                        "frame_index_in_session": i,
                    })

        if peer_key_hex is None:
            continue

        peer_name = peer_key_map.get(peer_key_hex)

        # Unauthorized peer check
        if peer_name is None:
            results["unauthorized_peers"].append({
                "key": peer_key_hex,
                "node": node_name,
                "session_index": sess_idx,
            })
            continue

        # Node policy check
        peer_info = policy["authorized_peers"].get(peer_name)
        if peer_info and node_name not in peer_info["allowed_nodes"]:
            results["node_policy_violations"].append({
                "peer_name": peer_name,
                "peer_key": peer_key_hex,
                "node": node_name,
                "allowed_nodes": peer_info["allowed_nodes"],
            })

        # Privilege violation check
        peer_role = peer_info["role"] if peer_info else None
        allowed = set(policy["role_permissions"].get(peer_role, []))

        for _, (name, _) in enumerate(session):
            if name in CLIENT_FRAMES and name != "ClientInfo" and name not in allowed:
                req_role = None
                for role in ROLE_ORDER:
                    if name in policy["role_permissions"].get(role, []):
                        req_role = role
                        break
                if req_role and req_role != peer_role:
                    results["privilege_violations"].append({
                        "peer_name": peer_name,
                        "peer_key": peer_key_hex,
                        "node": node_name,
                        "frame_type": name,
                        "peer_role": peer_role,
                        "required_role": req_role,
                    })

    return node_result, node_peers


def main():
    peer_key_map = read_wg_config("/app/wg_peers.conf")

    with open("/app/peer_policy.json") as f:
        policy = json.load(f)

    results = {
        "unauthorized_peers": [],
        "privilege_violations": [],
        "node_policy_violations": [],
        "protocol_violations": [],
    }

    n1, n1_peers = analyze_node(
        "/app/node1_capture.bin", "node1", peer_key_map, policy, results
    )
    n2, n2_peers = analyze_node(
        "/app/node2_capture.bin", "node2", peer_key_map, policy, results
    )

    results["node1"] = n1
    results["node2"] = n2
    results["peer_key_mapping"] = peer_key_map

    # Cross-node forwarding metrics
    fwd_pkts = (
        n1["frame_type_counts"].get("ForwardPacket", 0)
        + n2["frame_type_counts"].get("ForwardPacket", 0)
    )
    fwd_bytes = n1["data_bytes"]["forward"] + n2["data_bytes"]["forward"]
    results["cross_node_forward_packets"] = fwd_pkts
    results["cross_node_forward_bytes"] = fwd_bytes

    # Total data bytes
    total = 0
    for nd in [n1, n2]:
        for k in ("send", "recv", "forward"):
            total += nd["data_bytes"][k]
    results["total_data_bytes"] = total

    # Mesh topology
    n1_names = {peer_key_map[k] for k in n1_peers if k in peer_key_map}
    n2_names = {peer_key_map[k] for k in n2_peers if k in peer_key_map}
    results["mesh_topology"] = {
        "node1_peer_count": len(n1_peers),
        "node2_peer_count": len(n2_peers),
        "shared_peers": sorted(n1_names & n2_names),
    }

    with open("/app/audit_report.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Audit report written to /app/audit_report.json")


if __name__ == "__main__":
    main()
