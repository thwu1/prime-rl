#!/bin/bash

set -euo pipefail

# Deploy the implementation by reading system capabilities and writing
# the connectx module, then verify through computational testing.
cd /app

python3 <<'DEPLOY_AND_VERIFY'
import shutil
import socket
import struct
import sys
import os

# ---- Step 1: Probe system capabilities ----
print("=== System capability probe ===")

# Read ephemeral range
with open("/proc/sys/net/ipv4/ip_local_port_range") as f:
    eph_lo, eph_hi = map(int, f.read().split())
print(f"Ephemeral port range: {eph_lo}-{eph_hi} ({eph_hi - eph_lo + 1} ports)")

# Check netlink SOCK_DIAG support
try:
    nl = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, 4)
    nl.close()
    print("Netlink SOCK_DIAG: available")
except OSError as e:
    print(f"Netlink SOCK_DIAG: unavailable ({e}), will rely on /proc fallback")

# Check SO_COOKIE support
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cookie = s.getsockopt(socket.SOL_SOCKET, 57, 8)
    s.close()
    print(f"SO_COOKIE: available (cookie length: {len(cookie)} bytes)")
except OSError as e:
    print(f"SO_COOKIE: unavailable ({e})")

# ---- Step 2: Deploy implementation ----
print("\n=== Deploying connectx.py ===")
shutil.copy("/solution/connectx_impl.py", "/app/connectx.py")
print("Written /app/connectx.py")

# ---- Step 3: Computational verification ----
print("\n=== Verification ===")
sys.path.insert(0, "/app")
import connectx

# Verify ephemeral range reading
lo, hi = connectx.get_ephemeral_range()
assert 1024 <= lo < hi <= 65535, f"Invalid range: {lo}-{hi}"
print(f"[PASS] get_ephemeral_range() -> ({lo}, {hi})")

# Verify basic connection
s = connectx.udp_connectx(None, 0, "127.0.0.1", 59000)
assert s.getpeername() == ("127.0.0.1", 59000)
s.close()
print("[PASS] Basic auto-source connection")

# Verify source port reuse
socks = []
for i in range(10):
    s = connectx.udp_connectx("127.0.0.1", 59001, "127.0.0.1", 59100 + i)
    socks.append(s)
assert all(s.getsockname()[1] == 59001 for s in socks), "Source port reuse failed"
for s in socks:
    s.close()
print("[PASS] Source port reuse (10 connections on port 59001)")

# Verify overshadowing prevention
s1 = connectx.udp_connectx("127.0.0.1", 59002, "127.0.0.1", 59200)
try:
    s2 = connectx.udp_connectx("127.0.0.1", 59002, "127.0.0.1", 59200)
    s2.close()
    raise AssertionError("Should have raised OSError for duplicate 4-tuple")
except OSError:
    pass  # Expected
s1.close()
print("[PASS] Overshadowing prevention (duplicate 4-tuple rejected)")

# Verify socket lookup
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 59003))
s.connect(("127.0.0.1", 59300))
result = connectx.udp_socket_lookup(
    socket.AF_INET, ("127.0.0.1", 59003), ("127.0.0.1", 59300)
)
assert result is not None, "Socket lookup failed to find connected socket"
s.close()
print("[PASS] Socket lookup finds connected socket")

# Verify lookup does NOT false-positive on server sockets
srv_test = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
srv_test.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv_test.bind(("127.0.0.1", 59401))
result = connectx.udp_socket_lookup(
    socket.AF_INET, ("127.0.0.1", 59005), ("127.0.0.1", 59401)
)
assert result is None, "Lookup false-positive on server socket bound to dst port"
srv_test.close()
print("[PASS] Lookup correctly ignores server socket on destination port")

# Verify data transfer with a real server socket present
srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 59400))
srv.settimeout(3)
cli = connectx.udp_connectx("127.0.0.1", 0, "127.0.0.1", 59400)
cli.settimeout(3)
cli.send(b"ping")
data, addr = srv.recvfrom(64)
assert data == b"ping"
srv.sendto(b"pong", addr)
resp = cli.recv(64)
assert resp == b"pong"
cli.close()
srv.close()
print("[PASS] Data transfer roundtrip")

print("\n=== All verifications passed ===")
DEPLOY_AND_VERIFY
