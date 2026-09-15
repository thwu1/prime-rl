"""

Tests for multi-tenant TCP proxy port allocation.
Verifies actual TCP connection state at the kernel level using ss,
rather than trusting proxy-generated output.
"""

import os
import re
import signal
import socket
import subprocess
import time

import pytest


BACKENDS = [
    ("127.0.0.1", 8001),  # Service A
    ("127.0.0.1", 8002),  # Service B
    ("127.0.0.1", 8003),  # Service C
]

POOL_LO = 40000
POOL_HI = 40099
SVC_C_PORT_LO = 40050
SVC_C_PORT_HI = 40059


def _parse_ss_established():
    """Parse ss output and return list of established connections."""
    result = subprocess.run(
        ["ss", "-tn"],
        capture_output=True, text=True, timeout=10,
    )
    conns = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if len(parts) < 5:
            continue
        if parts[0] != "ESTAB":
            continue
        local_str = parts[3]
        peer_str = parts[4]
        lm = re.match(r"^(.+):(\d+)$", local_str)
        pm = re.match(r"^(.+):(\d+)$", peer_str)
        if lm and pm:
            conns.append({
                "lip": lm.group(1),
                "lport": int(lm.group(2)),
                "pip": pm.group(1),
                "pport": int(pm.group(2)),
            })
    return conns


def _proxy_connections():
    """Return only the proxy's outbound connections to known backends.
    Identifies proxy connections by local port in the source pool range
    (40000-40099) and peer matching a known backend address."""
    backend_set = set(BACKENDS)
    out = []
    for c in _parse_ss_established():
        if not (POOL_LO <= c["lport"] <= POOL_HI):
            continue
        if (c["pip"], c["pport"]) in backend_set:
            out.append(c)
    return out


def _wait_for_port(ip, port, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect((ip, port))
            s.close()
            return True
        except OSError:
            time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def live_connections():
    """Start backends, run the proxy, wait for connections to stabilise,
    then return the kernel-level connection snapshot from ss."""

    for f in ("/app/proxy_results.json",):
        try:
            os.unlink(f)
        except FileNotFoundError:
            pass

    backend_procs = []
    for ip, port in BACKENDS:
        p = subprocess.Popen(
            ["python3", "/app/backend.py", ip, str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        backend_procs.append(p)

    for ip, port in BACKENDS:
        assert _wait_for_port(ip, port, timeout=15), \
            f"Backend {ip}:{port} did not start"

    proxy_proc = subprocess.Popen(
        ["python3", "/app/proxy.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Poll ss until the connection count stabilises or we time out.
    deadline = time.time() + 60
    prev_count = 0
    stable = 0
    while time.time() < deadline:
        count = len(_proxy_connections())
        if count > 100 and count == prev_count:
            stable += 1
            if stable >= 6:  # unchanged for 3 s
                break
        else:
            stable = 0
        prev_count = count
        time.sleep(0.5)

    time.sleep(1)  # small grace period
    snapshot = _proxy_connections()

    yield snapshot

    proxy_proc.send_signal(signal.SIGTERM)
    try:
        proxy_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proxy_proc.kill()
    for p in backend_procs:
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def _to_backend(conns, ip, port):
    return [c for c in conns if c["pip"] == ip and c["pport"] == port]


# ── Service A ──────────────────────────────────────────────────────

class TestServiceA:
    def test_connection_count(self, live_connections):
        svc = _to_backend(live_connections, "127.0.0.1", 8001)
        assert len(svc) >= 90, (
            f"Service A: {len(svc)} connections, need >= 90"
        )

    def test_ports_in_pool(self, live_connections):
        for c in _to_backend(live_connections, "127.0.0.1", 8001):
            assert POOL_LO <= c["lport"] <= POOL_HI, (
                f"Service A uses port {c['lport']} outside 40000-40099"
            )


# ── Service B ──────────────────────────────────────────────────────

class TestServiceB:
    def test_connection_count(self, live_connections):
        svc = _to_backend(live_connections, "127.0.0.1", 8002)
        assert len(svc) >= 90, (
            f"Service B: {len(svc)} connections, need >= 90"
        )

    def test_ports_in_pool(self, live_connections):
        for c in _to_backend(live_connections, "127.0.0.1", 8002):
            assert POOL_LO <= c["lport"] <= POOL_HI, (
                f"Service B uses port {c['lport']} outside 40000-40099"
            )


# ── Service C ──────────────────────────────────────────────────────

class TestServiceC:
    def test_connection_count(self, live_connections):
        svc = _to_backend(live_connections, "127.0.0.1", 8003)
        assert len(svc) >= 8, (
            f"Service C: {len(svc)} connections, need >= 8"
        )

    def test_uses_reserved_ports(self, live_connections):
        svc = _to_backend(live_connections, "127.0.0.1", 8003)
        assert len(svc) >= 8, (
            f"Service C: only {len(svc)} connections"
        )
        for c in svc:
            assert SVC_C_PORT_LO <= c["lport"] <= SVC_C_PORT_HI, (
                f"Service C uses port {c['lport']}, expected {SVC_C_PORT_LO}-{SVC_C_PORT_HI}"
            )


# ── System-wide ────────────────────────────────────────────────────

class TestOverallSystem:
    def test_total_connections(self, live_connections):
        assert len(live_connections) >= 190, (
            f"Total: {len(live_connections)} connections, need >= 190"
        )

    def test_all_ports_in_pool(self, live_connections):
        for c in live_connections:
            assert POOL_LO <= c["lport"] <= POOL_HI, (
                f"Connection uses port {c['lport']} outside 40000-40099"
            )

    def test_port_reuse_across_destinations(self, live_connections):
        """With only 100 ports but 190+ connections to 3 backends,
        source ports MUST be reused across different destinations."""
        ports_by_dest = {}
        for c in live_connections:
            key = (c["pip"], c["pport"])
            ports_by_dest.setdefault(key, set()).add(c["lport"])

        assert len(ports_by_dest) >= 2, (
            "Expected connections to at least 2 different destinations"
        )

        sets = list(ports_by_dest.values())
        shared = set()
        for i in range(len(sets)):
            for j in range(i + 1, len(sets)):
                shared |= sets[i] & sets[j]

        assert len(shared) > 0, (
            "No source ports are reused across destinations. "
            "With 100 ports and 190+ connections to different backends, "
            "source ports must be shared via 4-tuple-aware allocation."
        )
