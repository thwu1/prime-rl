#!/usr/bin/env python3
"""DERP relay forensic audit — reference implementation.

Parses a DPCAP v1 capture, builds a SQLite audit database, verifies server
identity via openssl, detects protocol anomalies, and outputs a JSON report.
"""

import struct
import json
import sqlite3
import hashlib
import subprocess
import os
import sys

FILE_MAGIC = b'DPCAP\x01\x00\x00'
KEY_LEN = 32

FRAME_NAMES = {
    0x01: 'FrameServerKey',
    0x02: 'FrameClientInfo',
    0x03: 'FrameServerInfo',
    0x04: 'FrameSendPacket',
    0x05: 'FrameRecvPacket',
    0x06: 'FrameKeepAlive',
    0x07: 'FrameNotePreferred',
    0x08: 'FramePeerGone',
    0x09: 'FramePeerPresent',
    0x0a: 'FrameForwardPacket',
    0x10: 'FrameWatchConns',
    0x11: 'FrameClosePeer',
    0x12: 'FramePing',
    0x13: 'FramePong',
    0x14: 'FrameHealth',
    0x15: 'FrameRestarting',
}

MESH_ONLY_FRAMES = {0x0a, 0x10, 0x11}


def read_exact(f, n):
    data = f.read(n)
    return data if len(data) == n else None


def parse_capture(filename):
    records = []
    with open(filename, 'rb') as f:
        magic = read_exact(f, 8)
        if magic != FILE_MAGIC:
            raise ValueError(f"Bad file magic: {magic!r}")
        while True:
            env = read_exact(f, 3)
            if env is None:
                break
            conn_id = struct.unpack('>H', env[:2])[0]
            direction = env[2]
            fhdr = read_exact(f, 5)
            if fhdr is None:
                break
            frame_type = fhdr[0]
            payload_len = struct.unpack('>I', fhdr[1:5])[0]
            if payload_len > 0:
                payload = read_exact(f, payload_len)
                if payload is None:
                    break
            else:
                payload = b''
            records.append({
                'conn_id': conn_id,
                'direction': direction,
                'frame_type': frame_type,
                'payload': payload,
            })
    return records


def extract_server_key_from_pem(pem_path):
    """Extract raw 32-byte Ed25519 public key from PEM via openssl."""
    result = subprocess.run(
        ['openssl', 'pkey', '-pubin', '-in', pem_path, '-outform', 'DER'],
        capture_output=True, check=True
    )
    der = result.stdout
    # Ed25519 SubjectPublicKeyInfo DER: 12-byte header + 32-byte key
    return der[12:]


def load_json(path):
    with open(path) as f:
        return json.load(f)


def evaluate_acl(policy, src_hex, dst_hex):
    """First-match ACL evaluation. Returns 'allow' or 'deny'."""
    for rule in policy['rules']:
        src_match = rule['src'] == '*' or rule['src'] == src_hex
        dst_match = rule['dst'] == '*' or rule['dst'] == dst_hex
        if src_match and dst_match:
            return rule['action']
    return policy['default_action']


def main():
    capture_file = '/app/relay_capture.bin'
    pem_file = '/app/certs/server_identity.pem'
    acl_file = '/app/acl_policy.json'
    topo_file = '/app/topology.json'
    schema_file = '/app/schema.sql'
    db_file = '/app/audit.db'
    output_file = '/app/audit.json'

    records = parse_capture(capture_file)
    policy = load_json(acl_file)
    topology = load_json(topo_file)
    mesh_keys = {p['key'] for p in topology['mesh_peers']}

    # Extract expected server key from PEM
    expected_server_key = extract_server_key_from_pem(pem_file)

    # Build connection metadata
    conn_to_key = {}
    conn_frame_types = {}
    conn_frame_counts = {}

    for r in records:
        cid = r['conn_id']
        conn_frame_counts[cid] = conn_frame_counts.get(cid, 0) + 1
        conn_frame_types.setdefault(cid, set()).add(r['frame_type'])
        if r['frame_type'] == 0x02 and len(r['payload']) >= KEY_LEN:
            conn_to_key[cid] = r['payload'][:KEY_LEN]

    all_conn_ids = sorted(set(r['conn_id'] for r in records))

    handshake_complete = {}
    for cid in all_conn_ids:
        ftypes = conn_frame_types.get(cid, set())
        handshake_complete[cid] = (
            0x01 in ftypes and 0x02 in ftypes and 0x03 in ftypes
        )

    is_mesh = {}
    for cid in all_conn_ids:
        key = conn_to_key.get(cid)
        is_mesh[cid] = (key.hex() in mesh_keys) if key else False

    # --- Create SQLite database ---
    if os.path.exists(db_file):
        os.remove(db_file)

    db = sqlite3.connect(db_file)
    with open(schema_file) as f:
        db.executescript(f.read())

    # Populate frames
    for idx, r in enumerate(records):
        name = FRAME_NAMES.get(r['frame_type'], f"Unknown_0x{r['frame_type']:02x}")
        db.execute(
            "INSERT INTO frames VALUES (?,?,?,?,?,?)",
            (idx, r['conn_id'], r['direction'], r['frame_type'],
             name, len(r['payload']))
        )

    # Populate connections
    for cid in all_conn_ids:
        key_hex = conn_to_key[cid].hex() if cid in conn_to_key else None
        db.execute(
            "INSERT INTO connections VALUES (?,?,?,?,?)",
            (cid, key_hex,
             1 if is_mesh.get(cid, False) else 0,
             1 if handshake_complete.get(cid, False) else 0,
             conn_frame_counts.get(cid, 0))
        )

    # Populate routing_events
    rid = 0
    for idx, r in enumerate(records):
        if r['frame_type'] == 0x04:  # SendPacket
            src_key = conn_to_key.get(r['conn_id'])
            src_hex = src_key.hex() if src_key else None
            dst_hex = r['payload'][:KEY_LEN].hex() if len(r['payload']) >= KEY_LEN else None
            data_bytes = max(0, len(r['payload']) - KEY_LEN)
            db.execute("INSERT INTO routing_events VALUES (?,?,?,?,?,?)",
                       (rid, idx, src_hex, dst_hex, data_bytes, 'send'))
            rid += 1
        elif r['frame_type'] == 0x05:  # RecvPacket
            src_hex = r['payload'][:KEY_LEN].hex() if len(r['payload']) >= KEY_LEN else None
            dst_key = conn_to_key.get(r['conn_id'])
            dst_hex = dst_key.hex() if dst_key else None
            data_bytes = max(0, len(r['payload']) - KEY_LEN)
            db.execute("INSERT INTO routing_events VALUES (?,?,?,?,?,?)",
                       (rid, idx, src_hex, dst_hex, data_bytes, 'recv'))
            rid += 1
        elif r['frame_type'] == 0x0a:  # ForwardPacket
            src_hex = r['payload'][:KEY_LEN].hex() if len(r['payload']) >= KEY_LEN else None
            dst_hex = (r['payload'][KEY_LEN:2*KEY_LEN].hex()
                       if len(r['payload']) >= 2*KEY_LEN else None)
            data_bytes = max(0, len(r['payload']) - 2*KEY_LEN)
            db.execute("INSERT INTO routing_events VALUES (?,?,?,?,?,?)",
                       (rid, idx, src_hex, dst_hex, data_bytes, 'forward'))
            rid += 1

    # --- Detect anomalies ---
    aid = 0
    all_client_key_hexes = set(k.hex() for k in conn_to_key.values())

    # 1. Split brain: same key on multiple connections
    key_to_conns = {}
    for cid, key in conn_to_key.items():
        key_to_conns.setdefault(key.hex(), []).append(cid)

    for idx, r in enumerate(records):
        if r['frame_type'] == 0x02 and len(r['payload']) >= KEY_LEN:
            key_hex = r['payload'][:KEY_LEN].hex()
            conns_with_key = key_to_conns.get(key_hex, [])
            if len(conns_with_key) > 1 and r['conn_id'] == max(conns_with_key):
                db.execute("INSERT INTO anomalies VALUES (?,?,?,?,?)",
                           (aid, idx, 'split_brain', r['conn_id'],
                            f"Client key {key_hex[:16]}... on connections "
                            f"{','.join(str(c) for c in sorted(conns_with_key))}"))
                aid += 1

    # 2. Handshake violation: SendPacket from connection without ClientInfo
    for idx, r in enumerate(records):
        if r['frame_type'] == 0x04 and r['conn_id'] not in conn_to_key:
            db.execute("INSERT INTO anomalies VALUES (?,?,?,?,?)",
                       (aid, idx, 'handshake_violation', r['conn_id'],
                        f"SendPacket from connection {r['conn_id']} "
                        f"without completed handshake"))
            aid += 1

    # 3. Unauthorized mesh ops: mesh-only C2S frames from non-mesh connections
    for idx, r in enumerate(records):
        if (r['frame_type'] in MESH_ONLY_FRAMES
                and r['direction'] == 0x00
                and not is_mesh.get(r['conn_id'], False)):
            fname = FRAME_NAMES.get(r['frame_type'], '?')
            db.execute("INSERT INTO anomalies VALUES (?,?,?,?,?)",
                       (aid, idx, 'unauthorized_mesh_op', r['conn_id'],
                        f"{fname} from non-mesh connection {r['conn_id']}"))
            aid += 1

    # 4. ACL violations: SendPacket forbidden by policy
    for idx, r in enumerate(records):
        if r['frame_type'] == 0x04:
            src_key = conn_to_key.get(r['conn_id'])
            if src_key and len(r['payload']) >= KEY_LEN:
                src_hex = src_key.hex()
                dst_hex = r['payload'][:KEY_LEN].hex()
                if evaluate_acl(policy, src_hex, dst_hex) == 'deny':
                    db.execute("INSERT INTO anomalies VALUES (?,?,?,?,?)",
                               (aid, idx, 'acl_violation', r['conn_id'],
                                f"SendPacket {src_hex[:16]}...→{dst_hex[:16]}... "
                                f"denied by ACL"))
                    aid += 1

    # 5. Phantom peer: ForwardPacket source key not in any ClientInfo
    for idx, r in enumerate(records):
        if r['frame_type'] == 0x0a and len(r['payload']) >= KEY_LEN:
            src_hex = r['payload'][:KEY_LEN].hex()
            if src_hex not in all_client_key_hexes:
                db.execute("INSERT INTO anomalies VALUES (?,?,?,?,?)",
                           (aid, idx, 'phantom_peer', r['conn_id'],
                            f"ForwardPacket source key {src_hex[:16]}... "
                            f"not authenticated on any connection"))
                aid += 1

    db.commit()

    # --- Verify server key ---
    capture_server_key = None
    for r in records:
        if r['frame_type'] == 0x01 and len(r['payload']) >= 40:
            capture_server_key = r['payload'][8:40]  # Skip 8-byte DERP magic
            break

    server_key_verified = False
    if capture_server_key and expected_server_key:
        server_key_verified = (capture_server_key == expected_server_key)

    server_key_fingerprint = (
        hashlib.sha256(capture_server_key).hexdigest()
        if capture_server_key else None
    )

    # --- Build JSON report ---
    type_counts = {}
    for r in records:
        name = FRAME_NAMES.get(r['frame_type'], f"Unknown_0x{r['frame_type']:02x}")
        type_counts[name] = type_counts.get(name, 0) + 1

    connections_summary = []
    for cid in all_conn_ids:
        key_hex = conn_to_key[cid].hex() if cid in conn_to_key else None
        connections_summary.append({
            'conn_id': cid,
            'client_key_hex': key_hex,
            'is_mesh_peer': is_mesh.get(cid, False),
            'handshake_complete': handshake_complete.get(cid, False),
            'frame_count': conn_frame_counts.get(cid, 0),
        })

    total_send = sum(1 for r in records if r['frame_type'] == 0x04)
    total_recv = sum(1 for r in records if r['frame_type'] == 0x05)
    total_forward = sum(1 for r in records if r['frame_type'] == 0x0a)

    total_data_bytes = 0
    for r in records:
        if r['frame_type'] == 0x04:
            total_data_bytes += max(0, len(r['payload']) - KEY_LEN)
        elif r['frame_type'] == 0x05:
            total_data_bytes += max(0, len(r['payload']) - KEY_LEN)
        elif r['frame_type'] == 0x0a:
            total_data_bytes += max(0, len(r['payload']) - 2 * KEY_LEN)

    # Anomaly counts from DB
    anomaly_counts = {}
    for row in db.execute(
            "SELECT anomaly_type, COUNT(*) FROM anomalies GROUP BY anomaly_type"):
        anomaly_counts[row[0]] = row[1]
    total_anomalies = sum(anomaly_counts.values())

    # ACL compliance
    evaluated_sends = 0
    permitted_sends = 0
    denied_sends = 0
    for r in records:
        if r['frame_type'] == 0x04:
            src_key = conn_to_key.get(r['conn_id'])
            if src_key and len(r['payload']) >= KEY_LEN:
                src_hex = src_key.hex()
                dst_hex = r['payload'][:KEY_LEN].hex()
                action = evaluate_acl(policy, src_hex, dst_hex)
                evaluated_sends += 1
                if action == 'allow':
                    permitted_sends += 1
                else:
                    denied_sends += 1

    compliance_ratio = (permitted_sends / evaluated_sends
                        if evaluated_sends > 0 else 0.0)

    audit = {
        'total_frames': len(records),
        'frame_type_distribution': dict(sorted(type_counts.items())),
        'connections_summary': connections_summary,
        'server_key_verified': server_key_verified,
        'server_key_fingerprint': server_key_fingerprint,
        'routing_summary': {
            'total_send': total_send,
            'total_recv': total_recv,
            'total_forward': total_forward,
            'total_data_bytes': total_data_bytes,
        },
        'anomaly_counts': anomaly_counts,
        'total_anomalies': total_anomalies,
        'acl_compliance': {
            'evaluated_sends': evaluated_sends,
            'permitted_sends': permitted_sends,
            'denied_sends': denied_sends,
            'compliance_ratio': compliance_ratio,
        },
    }

    with open(output_file, 'w') as f:
        json.dump(audit, f, indent=2)

    db.close()
    print(f"Audit complete: {total_anomalies} anomalies in {len(records)} frames")


if __name__ == '__main__':
    main()
