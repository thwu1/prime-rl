#!/usr/bin/env python3
"""Generate DERP relay forensic audit scenario.

Creates a DPCAP capture with embedded protocol anomalies, server identity
certificate, ACL policy, mesh topology spec, and database schema.

Output files:
  /app/relay_capture.bin   — DPCAP v1 binary capture (51 frames, 6 anomalies)
  /app/certs/server_identity.pem — Ed25519 server public key
  /app/acl_policy.json     — Access control policy
  /app/topology.json       — Expected mesh topology
  /app/schema.sql          — Required SQLite schema
  /app/derp_spec.md        — DERP wire format spec
  /app/envelope_spec.md    — DPCAP capture format spec
"""
import struct
import hashlib
import json
import subprocess
import os

# --- Constants ---
FILE_MAGIC = b'DPCAP\x01\x00\x00'
DERP_MAGIC = bytes([0x44, 0x45, 0x52, 0x50, 0xf0, 0x9f, 0x94, 0x91])

FT_SERVER_KEY     = 0x01
FT_CLIENT_INFO    = 0x02
FT_SERVER_INFO    = 0x03
FT_SEND_PACKET    = 0x04
FT_RECV_PACKET    = 0x05
FT_KEEP_ALIVE     = 0x06
FT_NOTE_PREFERRED = 0x07
FT_PEER_GONE      = 0x08
FT_PEER_PRESENT   = 0x09
FT_FORWARD_PACKET = 0x0a
FT_WATCH_CONNS    = 0x10
FT_CLOSE_PEER     = 0x11
FT_PING           = 0x12
FT_PONG           = 0x13
FT_HEALTH         = 0x14
FT_RESTARTING     = 0x15

C2S = 0x00
S2C = 0x01

# Deterministic client keys (SHA-256 of known seeds)
key_alpha      = hashlib.sha256(b"audit_client_alpha").digest()
key_bravo      = hashlib.sha256(b"audit_client_bravo").digest()
key_charlie    = hashlib.sha256(b"audit_client_charlie").digest()
key_mesh_west  = hashlib.sha256(b"audit_mesh_west_peer").digest()
key_phantom    = hashlib.sha256(b"audit_phantom_node").digest()

# Connection IDs
CONN_ALPHA     = 0
CONN_BRAVO     = 1
CONN_CHARLIE   = 2
CONN_MESH_WEST = 3
CONN_ROGUE     = 4
CONN_ALPHA_DUP = 5


def derp_frame(ftype, payload):
    """Build raw DERP frame: 1B type + 4B big-endian length + payload."""
    return struct.pack('>BI', ftype, len(payload)) + payload


def rec(conn_id, direction, ftype, payload):
    """Build DPCAP record: 2B conn_id + 1B direction + DERP frame."""
    return struct.pack('>HB', conn_id, direction) + derp_frame(ftype, payload)


def server_key_payload(server_key):
    return DERP_MAGIC + server_key


def client_info_payload(client_key, extra_len=64):
    nonce = b'\x00' * 24
    fake_encrypted = b'\xAA' * extra_len
    return client_key + nonce + fake_encrypted


def server_info_payload():
    nonce = b'\x00' * 24
    fake_encrypted = b'\xBB' * 48
    return nonce + fake_encrypted


def peer_present_payload(key, ipv4_bytes, port, flags=0x01):
    ip16 = b'\x00' * 10 + b'\xff\xff' + ipv4_bytes
    return key + ip16 + struct.pack('>H', port) + bytes([flags])


def generate_server_key_pem():
    """Generate Ed25519 key pair via openssl; return raw 32-byte public key."""
    os.makedirs('/app/certs', exist_ok=True)
    subprocess.run(
        ['openssl', 'genpkey', '-algorithm', 'Ed25519',
         '-out', '/tmp/server_priv.pem'],
        check=True, capture_output=True
    )
    subprocess.run(
        ['openssl', 'pkey', '-in', '/tmp/server_priv.pem',
         '-pubout', '-out', '/app/certs/server_identity.pem'],
        check=True, capture_output=True
    )
    result = subprocess.run(
        ['openssl', 'pkey', '-pubin',
         '-in', '/app/certs/server_identity.pem',
         '-outform', 'DER'],
        capture_output=True, check=True
    )
    der = result.stdout
    # Ed25519 SubjectPublicKeyInfo DER = 12-byte header + 32-byte key
    raw_key = der[12:]
    assert len(raw_key) == 32, f"Expected 32-byte key, got {len(raw_key)}"
    os.remove('/tmp/server_priv.pem')
    return raw_key


def main():
    server_key = generate_server_key_pem()
    records = []
    sk_pay = server_key_payload(server_key)
    si_pay = server_info_payload()

    # ========== Phase 1: Handshakes (15 frames, indices 0-14) ==========
    # ServerKey to conns 0,1,2,3,5
    for c in [CONN_ALPHA, CONN_BRAVO, CONN_CHARLIE, CONN_MESH_WEST, CONN_ALPHA_DUP]:
        records.append(rec(c, S2C, FT_SERVER_KEY, sk_pay))
    # ClientInfo from conns 0,1,2,3,5
    for c, k, elen in [
        (CONN_ALPHA, key_alpha, 64),
        (CONN_BRAVO, key_bravo, 64),
        (CONN_CHARLIE, key_charlie, 64),
        (CONN_MESH_WEST, key_mesh_west, 80),
        (CONN_ALPHA_DUP, key_alpha, 64),       # ANOMALY: split_brain (same key as conn 0)
    ]:
        records.append(rec(c, C2S, FT_CLIENT_INFO, client_info_payload(k, elen)))
    # ServerInfo to conns 0,1,2,3,5
    for c in [CONN_ALPHA, CONN_BRAVO, CONN_CHARLIE, CONN_MESH_WEST, CONN_ALPHA_DUP]:
        records.append(rec(c, S2C, FT_SERVER_INFO, si_pay))

    # ========== Phase 1b: Rogue gets ServerKey only (1 frame, index 15) ==========
    records.append(rec(CONN_ROGUE, S2C, FT_SERVER_KEY, sk_pay))

    # ========== Phase 2: Mesh setup (3 frames, indices 16-18) ==========
    records.append(rec(CONN_MESH_WEST, C2S, FT_WATCH_CONNS, b''))
    records.append(rec(CONN_MESH_WEST, S2C, FT_PEER_PRESENT,
                       peer_present_payload(key_alpha, b'\xc0\xa8\x01\x0a', 41641)))
    records.append(rec(CONN_MESH_WEST, S2C, FT_PEER_PRESENT,
                       peer_present_payload(key_bravo, b'\xc0\xa8\x01\x14', 41641)))

    # ========== Phase 3: Preferences (2 frames, indices 19-20) ==========
    records.append(rec(CONN_ALPHA, C2S, FT_NOTE_PREFERRED, b'\x01'))
    records.append(rec(CONN_BRAVO, C2S, FT_NOTE_PREFERRED, b'\x00'))

    # ========== Phase 4: alpha→bravo data (4 frames, indices 21-24) — ALLOWED ==========
    for sz in [100, 200]:
        data = bytes([sz & 0xFF]) * sz
        records.append(rec(CONN_ALPHA, C2S, FT_SEND_PACKET, key_bravo + data))
        records.append(rec(CONN_BRAVO, S2C, FT_RECV_PACKET, key_alpha + data))

    # ========== Phase 5: bravo→alpha data (4 frames, indices 25-28) — ALLOWED ==========
    for sz in [150, 250]:
        data = bytes([sz & 0xFF]) * sz
        records.append(rec(CONN_BRAVO, C2S, FT_SEND_PACKET, key_alpha + data))
        records.append(rec(CONN_ALPHA, S2C, FT_RECV_PACKET, key_bravo + data))

    # ========== Phase 6: alpha→charlie (2 frames, indices 29-30) — ALLOWED ==========
    data_ac = b'\xEE' * 80
    records.append(rec(CONN_ALPHA, C2S, FT_SEND_PACKET, key_charlie + data_ac))
    records.append(rec(CONN_CHARLIE, S2C, FT_RECV_PACKET, key_alpha + data_ac))

    # ========== Phase 7: charlie→bravo (2 frames, indices 31-32) — ACL VIOLATION ==========
    data_cb = b'\xDD' * 120
    records.append(rec(CONN_CHARLIE, C2S, FT_SEND_PACKET, key_bravo + data_cb))
    records.append(rec(CONN_BRAVO, S2C, FT_RECV_PACKET, key_charlie + data_cb))

    # ========== Phase 8: charlie→alpha (2 frames, indices 33-34) — ACL VIOLATION ==========
    data_ca = b'\xCC' * 60
    records.append(rec(CONN_CHARLIE, C2S, FT_SEND_PACKET, key_alpha + data_ca))
    records.append(rec(CONN_ALPHA, S2C, FT_RECV_PACKET, key_charlie + data_ca))

    # ========== Phase 9: Mesh forward phantom→alpha (2 frames, indices 35-36) ==========
    data_fwd = b'\x42' * 90
    records.append(rec(CONN_MESH_WEST, C2S, FT_FORWARD_PACKET,
                       key_phantom + key_alpha + data_fwd))
    records.append(rec(CONN_ALPHA, S2C, FT_RECV_PACKET, key_phantom + data_fwd))

    # ========== Phase 10: Handshake violation (1 frame, index 37) ==========
    data_rogue = b'\xBB' * 50
    records.append(rec(CONN_ROGUE, C2S, FT_SEND_PACKET, key_bravo + data_rogue))

    # ========== Phase 11: Unauthorized mesh op (1 frame, index 38) ==========
    records.append(rec(CONN_CHARLIE, C2S, FT_WATCH_CONNS, b''))

    # ========== Phase 12: KeepAlive (4 frames, indices 39-42) ==========
    for c in [CONN_ALPHA, CONN_BRAVO, CONN_CHARLIE, CONN_MESH_WEST]:
        records.append(rec(c, S2C, FT_KEEP_ALIVE, b''))

    # ========== Phase 13: Ping/Pong (2 frames, indices 43-44) ==========
    ping_data = b'\x01\x02\x03\x04\x05\x06\x07\x08'
    records.append(rec(CONN_ALPHA, S2C, FT_PING, ping_data))
    records.append(rec(CONN_ALPHA, C2S, FT_PONG, ping_data))

    # ========== Phase 14: PeerGone — charlie disconnects (3 frames, indices 45-47) ==========
    for c in [CONN_ALPHA, CONN_BRAVO, CONN_MESH_WEST]:
        records.append(rec(c, S2C, FT_PEER_GONE, key_charlie + b'\x00'))

    # ========== Phase 15: Health + Restart (2 frames, indices 48-49) ==========
    records.append(rec(CONN_BRAVO, S2C, FT_HEALTH,
                       b'split brain detected for client'))
    records.append(rec(CONN_ALPHA, S2C, FT_RESTARTING,
                       struct.pack('>II', 3000, 10000)))

    # ========== Phase 16: ClosePeer (1 frame, index 50) ==========
    records.append(rec(CONN_MESH_WEST, C2S, FT_CLOSE_PEER, key_charlie))

    # --- Write capture file ---
    assert len(records) == 51, f"Expected 51 frames, got {len(records)}"
    with open('/app/relay_capture.bin', 'wb') as f:
        f.write(FILE_MAGIC)
        for r in records:
            f.write(r)
    print(f"Generated /app/relay_capture.bin: {len(records)} frames")

    # --- Write ACL policy ---
    acl = {
        "default_action": "deny",
        "rules": [
            {"action": "allow", "src": key_alpha.hex(), "dst": key_bravo.hex(),
             "description": "alpha to bravo"},
            {"action": "allow", "src": key_bravo.hex(), "dst": key_alpha.hex(),
             "description": "bravo to alpha"},
            {"action": "allow", "src": key_alpha.hex(), "dst": key_charlie.hex(),
             "description": "alpha to charlie"},
        ]
    }
    with open('/app/acl_policy.json', 'w') as f:
        json.dump(acl, f, indent=2)

    # --- Write topology ---
    topology = {
        "node_name": "derp-east",
        "region_id": 1,
        "mesh_peers": [
            {"name": "derp-west", "key": key_mesh_west.hex()}
        ],
        "expected_clients": [
            key_alpha.hex(),
            key_bravo.hex(),
            key_charlie.hex()
        ]
    }
    with open('/app/topology.json', 'w') as f:
        json.dump(topology, f, indent=2)

    print("Generated all audit scenario files")


if __name__ == '__main__':
    main()
