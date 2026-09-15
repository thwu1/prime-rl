#!/usr/bin/env python3
"""Generate DERP relay mesh forensics task environment.

Creates binary captures from two relay nodes, a WireGuard peer config,
and an authorization policy for the security audit task.
"""
import struct
import hashlib
import subprocess
import base64
import json
import os
import ipaddress

# DERP protocol constants
MAGIC = b"DERP\xf0\x9f\x94\x91"

FT_SERVER_KEY = 0x01
FT_CLIENT_INFO = 0x02
FT_SERVER_INFO = 0x03
FT_SEND_PACKET = 0x04
FT_RECV_PACKET = 0x05
FT_KEEP_ALIVE = 0x06
FT_NOTE_PREFERRED = 0x07
FT_PEER_GONE = 0x08
FT_PEER_PRESENT = 0x09
FT_FORWARD_PACKET = 0x0A
FT_WATCH_CONNS = 0x10
FT_CLOSE_PEER = 0x11
FT_PING = 0x12
FT_PONG = 0x13
FT_HEALTH = 0x14
FT_RESTARTING = 0x15


def gen_keypair(seed_name):
    """Generate a deterministic Curve25519 keypair using wg tools."""
    priv_bytes = hashlib.sha256(
        f"wg-private-{seed_name}-seed-v1".encode()
    ).digest()
    priv_b64 = base64.b64encode(priv_bytes).decode()
    result = subprocess.run(
        ["wg", "pubkey"],
        input=priv_b64,
        capture_output=True,
        text=True,
        check=True,
    )
    pub_b64 = result.stdout.strip()
    pub_bytes = base64.b64decode(pub_b64)
    return priv_b64, pub_b64, pub_bytes


def make_data(seed, size):
    """Generate deterministic payload data from a seed string."""
    h = hashlib.sha256(("data-" + seed).encode()).digest()
    result = b""
    i = 0
    while len(result) < size:
        result += hashlib.sha256(h + struct.pack(">I", i)).digest()
        i += 1
    return result[:size]


def write_frame(f, ftype, payload):
    """Write a single DERP frame (5-byte header + payload)."""
    f.write(struct.pack(">BI", ftype, len(payload)))
    f.write(payload)


def ipv4_to_16(addr_str):
    """Convert IPv4 to 16-byte IPv4-mapped IPv6 encoding."""
    addr = ipaddress.IPv4Address(addr_str)
    return b"\x00" * 10 + b"\xff\xff" + addr.packed


def generate():
    os.makedirs("/app", exist_ok=True)

    # Generate all keypairs
    peers = {}
    for name in [
        "alpha", "bravo", "gamma", "delta", "echo",
        "rogue", "server1", "server2",
    ]:
        priv_b64, pub_b64, pub_bytes = gen_keypair(name)
        peers[name] = {
            "priv_b64": priv_b64,
            "pub_b64": pub_b64,
            "pub_bytes": pub_bytes,
        }

    def key(name):
        return peers[name]["pub_bytes"]

    def nonce(tag):
        return hashlib.sha256(f"nonce-{tag}".encode()).digest()[:24]

    ping1 = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    ping2 = b"\x11\x12\x13\x14\x15\x16\x17\x18"
    ping3 = b"\x21\x22\x23\x24\x25\x26\x27\x28"
    ping4 = b"\xa1\xa2\xa3\xa4\xa5\xa6\xa7\xa8"

    # ===== Node 1 capture =====
    with open("/app/node1_capture.bin", "wb") as f:
        # Session A: alpha (authorized client, allowed on node1) — normal
        write_frame(f, FT_SERVER_KEY, MAGIC + key("server1"))
        write_frame(f, FT_CLIENT_INFO,
                    key("alpha") + nonce("alpha") + make_data("ci-alpha", 64))
        write_frame(f, FT_SERVER_INFO,
                    nonce("si-n1-a") + make_data("si-n1-a", 32))
        write_frame(f, FT_NOTE_PREFERRED, b"\x01")
        write_frame(f, FT_SEND_PACKET,
                    key("bravo") + make_data("pkt-a1", 128))
        write_frame(f, FT_RECV_PACKET,
                    key("bravo") + make_data("pkt-a2", 200))
        write_frame(f, FT_SEND_PACKET,
                    key("echo") + make_data("pkt-a3", 256))
        write_frame(f, FT_PING, ping1)
        write_frame(f, FT_PONG, ping1)
        write_frame(f, FT_KEEP_ALIVE, b"")

        # Session B: bravo (authorized client) — PRIVILEGE VIOLATIONS
        write_frame(f, FT_SERVER_KEY, MAGIC + key("server1"))
        write_frame(f, FT_CLIENT_INFO,
                    key("bravo") + nonce("bravo") + make_data("ci-bravo", 48))
        write_frame(f, FT_SERVER_INFO,
                    nonce("si-n1-b") + make_data("si-n1-b", 32))
        write_frame(f, FT_NOTE_PREFERRED, b"\x01")
        write_frame(f, FT_SEND_PACKET,
                    key("alpha") + make_data("pkt-b1", 100))
        # VIOLATION: client using mesh-only WatchConns
        write_frame(f, FT_WATCH_CONNS, b"")
        # VIOLATION: client using mesh-only ForwardPacket
        write_frame(f, FT_FORWARD_PACKET,
                    key("alpha") + key("delta") + make_data("pkt-b2", 150))
        write_frame(f, FT_RECV_PACKET,
                    key("alpha") + make_data("pkt-b3", 300))
        write_frame(f, FT_PING, ping2)
        write_frame(f, FT_PONG, ping2)

        # Session C: gamma (authorized mesh) — legitimate mesh operations
        write_frame(f, FT_SERVER_KEY, MAGIC + key("server1"))
        write_frame(f, FT_CLIENT_INFO,
                    key("gamma") + nonce("gamma") + make_data("ci-gamma", 56))
        write_frame(f, FT_SERVER_INFO,
                    nonce("si-n1-c") + make_data("si-n1-c", 32))
        write_frame(f, FT_WATCH_CONNS, b"")
        write_frame(f, FT_PEER_PRESENT,
                    key("alpha") + ipv4_to_16("100.64.1.1")
                    + struct.pack(">H", 41641) + b"\x01")
        write_frame(f, FT_PEER_PRESENT,
                    key("bravo") + ipv4_to_16("100.64.1.2")
                    + struct.pack(">H", 41641) + b"\x01")
        write_frame(f, FT_FORWARD_PACKET,
                    key("alpha") + key("echo") + make_data("pkt-c1", 300))
        write_frame(f, FT_FORWARD_PACKET,
                    key("echo") + key("alpha") + make_data("pkt-c2", 200))
        write_frame(f, FT_PING, ping3)
        write_frame(f, FT_PONG, ping3)
        write_frame(f, FT_PEER_GONE, key("bravo") + b"\x00")
        write_frame(f, FT_KEEP_ALIVE, b"")

        # Session D: rogue (UNAUTHORIZED + PROTOCOL VIOLATION)
        write_frame(f, FT_SERVER_KEY, MAGIC + key("server1"))
        # PROTOCOL VIOLATION: SendPacket before ClientInfo
        write_frame(f, FT_SEND_PACKET,
                    key("alpha") + make_data("pkt-d1", 64))
        write_frame(f, FT_CLIENT_INFO,
                    key("rogue") + nonce("rogue") + make_data("ci-rogue", 32))
        write_frame(f, FT_SERVER_INFO,
                    nonce("si-n1-d") + make_data("si-n1-d", 32))
        write_frame(f, FT_PEER_GONE, key("rogue") + b"\x01")

    # ===== Node 2 capture =====
    with open("/app/node2_capture.bin", "wb") as f:
        # Session E: echo (authorized client, allowed on node2) — normal
        write_frame(f, FT_SERVER_KEY, MAGIC + key("server2"))
        write_frame(f, FT_CLIENT_INFO,
                    key("echo") + nonce("echo") + make_data("ci-echo", 40))
        write_frame(f, FT_SERVER_INFO,
                    nonce("si-n2-e") + make_data("si-n2-e", 32))
        write_frame(f, FT_NOTE_PREFERRED, b"\x01")
        write_frame(f, FT_SEND_PACKET,
                    key("alpha") + make_data("pkt-e1", 180))
        write_frame(f, FT_RECV_PACKET,
                    key("alpha") + make_data("pkt-e2", 256))
        write_frame(f, FT_PING, ping4)
        write_frame(f, FT_PONG, ping4)
        write_frame(f, FT_KEEP_ALIVE, b"")

        # Session F: gamma (authorized mesh, on node2) — legitimate
        write_frame(f, FT_SERVER_KEY, MAGIC + key("server2"))
        write_frame(f, FT_CLIENT_INFO,
                    key("gamma") + nonce("gamma-n2")
                    + make_data("ci-gamma-n2", 56))
        write_frame(f, FT_SERVER_INFO,
                    nonce("si-n2-f") + make_data("si-n2-f", 32))
        write_frame(f, FT_WATCH_CONNS, b"")
        write_frame(f, FT_PEER_PRESENT,
                    key("echo") + ipv4_to_16("100.64.1.5")
                    + struct.pack(">H", 41641) + b"\x01")
        write_frame(f, FT_PEER_PRESENT, key("delta"))  # old format, key only
        write_frame(f, FT_FORWARD_PACKET,
                    key("delta") + key("echo") + make_data("pkt-f1", 250))
        write_frame(f, FT_RECV_PACKET,
                    key("echo") + make_data("pkt-f2", 150))
        write_frame(f, FT_PEER_GONE, key("echo") + b"\x00")

        # Session G: alpha on node2 — NODE POLICY VIOLATION
        write_frame(f, FT_SERVER_KEY, MAGIC + key("server2"))
        write_frame(f, FT_CLIENT_INFO,
                    key("alpha") + nonce("alpha-n2")
                    + make_data("ci-alpha-n2", 64))
        write_frame(f, FT_SERVER_INFO,
                    nonce("si-n2-g") + make_data("si-n2-g", 32))
        write_frame(f, FT_SEND_PACKET,
                    key("echo") + make_data("pkt-g1", 90))
        write_frame(f, FT_RECV_PACKET,
                    key("echo") + make_data("pkt-g2", 120))

        # Session H: delta (authorized admin, on node2) — legitimate
        write_frame(f, FT_SERVER_KEY, MAGIC + key("server2"))
        write_frame(f, FT_CLIENT_INFO,
                    key("delta") + nonce("delta") + make_data("ci-delta", 48))
        write_frame(f, FT_SERVER_INFO,
                    nonce("si-n2-h") + make_data("si-n2-h", 32))
        write_frame(f, FT_NOTE_PREFERRED, b"\x01")
        write_frame(f, FT_WATCH_CONNS, b"")
        write_frame(f, FT_CLOSE_PEER, key("echo"))
        write_frame(f, FT_HEALTH, b"maintenance window active")
        write_frame(f, FT_RESTARTING, struct.pack(">II", 3000, 10000))

    # ===== WireGuard peer configuration =====
    authorized = ["alpha", "bravo", "gamma", "delta", "echo"]
    wg_lines = [
        "[Interface]",
        f"PrivateKey = {peers['server1']['priv_b64']}",
        "ListenPort = 41641",
        "",
    ]
    for idx, name in enumerate(authorized):
        wg_lines.extend([
            "[Peer]",
            f"# {name}",
            f"PublicKey = {peers[name]['pub_b64']}",
            f"AllowedIPs = 100.64.1.{idx + 1}/32",
            "",
        ])
    with open("/app/wg_peers.conf", "w") as f:
        f.write("\n".join(wg_lines))

    # ===== Peer authorization policy =====
    policy = {
        "authorized_peers": {
            "alpha": {"role": "client", "allowed_nodes": ["node1"]},
            "bravo": {"role": "client", "allowed_nodes": ["node1", "node2"]},
            "gamma": {"role": "mesh", "allowed_nodes": ["node1", "node2"]},
            "delta": {"role": "admin", "allowed_nodes": ["node1", "node2"]},
            "echo": {"role": "client", "allowed_nodes": ["node2"]},
        },
        "role_permissions": {
            "client": ["SendPacket", "NotePreferred", "Ping", "Pong"],
            "mesh": [
                "SendPacket", "NotePreferred", "Ping", "Pong",
                "WatchConns", "ForwardPacket",
            ],
            "admin": [
                "SendPacket", "NotePreferred", "Ping", "Pong",
                "WatchConns", "ForwardPacket", "ClosePeer",
            ],
        },
    }
    with open("/app/peer_policy.json", "w") as f:
        json.dump(policy, f, indent=2)

    print("Generated DERP relay mesh forensics environment")


if __name__ == "__main__":
    generate()
