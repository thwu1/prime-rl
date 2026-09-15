"""
Tests for TCP Load Balancer — verifies correct behavior after bug fixes.

"""
import pytest
import subprocess
import socket
import time
import json
import signal
import sys
import threading
from collections import Counter

# ---------------------------------------------------------------------------
# Global state managed by the module-scoped fixture
# ---------------------------------------------------------------------------
_backend_procs = {}
_lb_proc = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait_for_port(port, host="127.0.0.1", timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=1)
            s.close()
            return True
        except (ConnectionRefusedError, OSError, socket.timeout):
            time.sleep(0.15)
    return False


def start_backend(port):
    proc = subprocess.Popen(
        [sys.executable, "/app/backends/echo_server.py", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert wait_for_port(port, timeout=8), f"Echo backend on port {port} failed to start"
    return proc


def tcp_exchange(port, data, host="127.0.0.1", timeout=5):
    """Connect, send *data*, half-close write, read JSON response."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((host, port))
    s.sendall(data.encode() if isinstance(data, str) else data)
    s.shutdown(socket.SHUT_WR)
    resp = b""
    try:
        while True:
            chunk = s.recv(8192)
            if not chunk:
                break
            resp += chunk
    except socket.timeout:
        pass
    s.close()
    if not resp:
        return None
    return json.loads(resp.decode("utf-8", errors="replace"))


def admin_request(method, path, body=None, port=8090):
    """Raw HTTP request to the admin API.  Returns (status_code, parsed_json)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect(("127.0.0.1", port))

    if body is not None:
        body_bytes = json.dumps(body).encode()
        req = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode() + body_bytes
    else:
        req = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode()

    s.sendall(req)
    resp = b""
    try:
        while True:
            chunk = s.recv(8192)
            if not chunk:
                break
            resp += chunk
    except socket.timeout:
        pass
    s.close()

    resp_str = resp.decode("utf-8", errors="replace")
    header_end = resp_str.find("\r\n\r\n")
    if header_end < 0:
        return None, None
    status_code = int(resp_str.split("\r\n")[0].split(" ")[1])
    body_str = resp_str[header_end + 4:]
    try:
        return status_code, json.loads(body_str)
    except (json.JSONDecodeError, ValueError):
        return status_code, body_str


# ---------------------------------------------------------------------------
# Fixture — starts echo backends + load balancer once per module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def setup_environment():
    global _backend_procs, _lb_proc

    # Start echo backends on ports 9001-9007
    for port in [9001, 9002, 9003, 9004, 9005, 9006, 9007]:
        _backend_procs[port] = start_backend(port)

    # Start load balancer
    _lb_proc = subprocess.Popen(
        [sys.executable, "/app/lb.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Verify LB didn't crash
    time.sleep(1)
    if _lb_proc.poll() is not None:
        stderr = _lb_proc.stderr.read(4096).decode() if _lb_proc.stderr else ""
        pytest.fail(f"LB exited immediately (rc={_lb_proc.returncode}). stderr: {stderr}")

    # Wait for frontend + admin ports
    for port in [8080, 8081, 8082, 8083, 8090]:
        ok = wait_for_port(port, timeout=15)
        if not ok:
            stderr = _lb_proc.stderr.read(4096).decode() if _lb_proc.stderr else ""
            pytest.fail(f"LB port {port} not available. stderr: {stderr}")

    # Let health checks stabilise
    time.sleep(8)

    yield

    # Tear down
    if _lb_proc and _lb_proc.poll() is None:
        _lb_proc.send_signal(signal.SIGTERM)
        try:
            _lb_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _lb_proc.kill()
            _lb_proc.wait()

    for proc in _backend_procs.values():
        if proc.poll() is None:
            proc.kill()
            proc.wait()


# ===================================================================
# Non-destructive tests (run first)
# ===================================================================

class TestWeightedRoundRobin:
    """Frontend 8080: WRR with backends 9001 (w=3) and 9002 (w=2)."""

    def test_both_backends_receive_traffic(self):
        ports = set()
        for i in range(20):
            resp = tcp_exchange(8080, f"wrr_check_{i}")
            assert resp is not None, "LB must return a proxied response"
            ports.add(resp["backend_port"])
        assert ports == {9001, 9002}, f"Both backends must receive traffic: {ports}"

    def test_weight_distribution(self):
        counts = Counter()
        for i in range(100):
            resp = tcp_exchange(8080, f"wrr_dist_{i}")
            assert resp is not None
            counts[resp["backend_port"]] += 1

        ratio = counts[9001] / max(counts[9002], 1)
        assert 1.0 <= ratio <= 2.5, (
            f"Expected ~1.5:1 ratio (weights 3:2), got {ratio:.2f} "
            f"(9001={counts[9001]}, 9002={counts[9002]})"
        )

    def test_smooth_interleaving(self):
        """Smooth WRR must interleave, not batch-schedule."""
        ports = []
        for i in range(50):
            resp = tcp_exchange(8080, f"wrr_smooth_{i}")
            assert resp is not None
            ports.append(resp["backend_port"])

        # Check max consecutive run to the same backend
        max_run = 1
        current_run = 1
        for i in range(1, len(ports)):
            if ports[i] == ports[i - 1]:
                current_run += 1
                max_run = max(max_run, current_run)
            else:
                current_run = 1

        # With weights 3:2 (total 5), smooth WRR interleaves A,B,A,B,A
        # Max consecutive across cycle boundaries is 2.
        # Batch scheduling would produce A,A,A,B,B with max consecutive = 3.
        assert max_run <= 2, (
            f"Max consecutive run = {max_run}, suggesting batch scheduling. "
            f"Smooth WRR with weights 3:2 should interleave (max run <= 2). "
            f"First 20: {ports[:20]}"
        )


class TestLeastConnections:
    """Frontend 8081: least-connections with 9003, 9004, 9005."""

    def test_all_backends_receive_traffic(self):
        ports = set()
        for i in range(30):
            resp = tcp_exchange(8081, f"lc_{i}")
            assert resp is not None
            ports.add(resp["backend_port"])
        assert ports == {9003, 9004, 9005}, f"All 3 backends must receive traffic: {ports}"


class TestIPHash:
    """Frontend 8082: ip_hash with 9006, 9007."""

    def test_same_client_ip_is_sticky(self):
        first_port = None
        for i in range(20):
            resp = tcp_exchange(8082, f"hash_{i}")
            assert resp is not None
            if first_port is None:
                first_port = resp["backend_port"]
            assert resp["backend_port"] == first_port, (
                f"IP hash not consistent: expected {first_port}, "
                f"got {resp['backend_port']} on iteration {i}"
            )


class TestProxyProtocol:
    """PROXY protocol v1 header injection."""

    def test_proxy_header_present(self):
        resp = tcp_exchange(8080, "proxy_verify")
        assert resp is not None
        hdr = resp.get("proxy_header")
        assert hdr is not None, "Backend should receive a PROXY header"
        assert hdr.startswith("PROXY TCP4 "), f"Bad PROXY header: {hdr}"
        parts = hdr.split(" ")
        assert len(parts) == 6, f"PROXY header must have 6 space-separated fields: {hdr}"
        assert parts[2] == "127.0.0.1", f"Source IP should be 127.0.0.1, got {parts[2]}"

    def test_proxy_header_port_order(self):
        """PROXY v1: PROXY TCP4 <src_ip> <dst_ip> <src_port> <dst_port>
        src_port is the client ephemeral port (>1024), dst_port is the frontend port (8080)."""
        resp = tcp_exchange(8080, "proxy_port_order_check")
        assert resp is not None
        hdr = resp.get("proxy_header")
        assert hdr is not None, "No PROXY header received"
        parts = hdr.split(" ")
        assert len(parts) == 6

        src_port_val = int(parts[4])
        dst_port_val = int(parts[5])
        assert dst_port_val == 8080, (
            f"PROXY header field 6 (dst_port) should be the frontend port 8080, "
            f"got {dst_port_val}. Fields may be swapped."
        )
        assert src_port_val > 1024, (
            f"PROXY header field 5 (src_port) should be ephemeral (>1024), "
            f"got {src_port_val}. Fields may be swapped."
        )

    def test_payload_forwarded(self):
        resp = tcp_exchange(8080, "payload_check_xyz")
        assert resp is not None
        assert "payload_check_xyz" in resp["data"], f"Payload not forwarded: {resp['data']}"


class TestAdminAPI:
    """Admin HTTP API on port 8090."""

    def test_stats_returns_json(self):
        # Generate traffic first
        for i in range(5):
            tcp_exchange(8080, f"stats_gen_{i}")

        status, data = admin_request("GET", "/stats")
        assert status == 200, f"/stats returned {status}"
        assert isinstance(data, dict), f"/stats must return JSON object, got {type(data)}"

    def test_stats_bytes_received(self):
        """After traffic, bytes_received must be tracked (>0) for backends."""
        for i in range(10):
            tcp_exchange(8080, f"bytes_rx_{i}")

        time.sleep(0.5)
        status, data = admin_request("GET", "/stats")
        assert status == 200

        total_received = 0
        for pool_stats in data.values():
            if isinstance(pool_stats, list):
                for b in pool_stats:
                    total_received += b.get("bytes_received", 0)

        assert total_received > 0, (
            "bytes_received should be > 0 after traffic — "
            "b2c direction byte counting may be missing"
        )

    def test_backends_lists_all(self):
        status, data = admin_request("GET", "/backends")
        assert status == 200, f"/backends returned {status}"
        assert data is not None

        all_ports = set()
        if isinstance(data, dict):
            for pool_backends in data.values():
                if isinstance(pool_backends, list):
                    for b in pool_backends:
                        all_ports.add(b.get("port"))
        elif isinstance(data, list):
            for b in data:
                all_ports.add(b.get("port"))

        expected = {9001, 9002, 9003, 9004, 9005, 9006, 9007}
        assert expected.issubset(all_ports), (
            f"All backend ports must appear. Expected {expected}, got {all_ports}"
        )

    def test_backends_all_healthy(self):
        status, data = admin_request("GET", "/backends")
        assert status == 200

        unhealthy = []
        if isinstance(data, dict):
            for pool_name, pool_backends in data.items():
                if isinstance(pool_backends, list):
                    for b in pool_backends:
                        if not b.get("healthy", False):
                            unhealthy.append(f"{pool_name}/{b.get('port')}")
        elif isinstance(data, list):
            for b in data:
                if not b.get("healthy", False):
                    unhealthy.append(str(b.get("port")))

        assert not unhealthy, f"All backends should be healthy; unhealthy: {unhealthy}"


# ===================================================================
# Rate limiting (semi-destructive — uses a dedicated frontend)
# ===================================================================

class TestRateLimiting:
    """Frontend 8083: WRR + rate limit 5/sec."""

    def test_excess_connections_rejected(self):
        results = {"success": 0, "failed": 0}
        lock = threading.Lock()

        def connect(i):
            try:
                resp = tcp_exchange(8083, f"rl_{i}", timeout=3)
                with lock:
                    if resp and "backend_port" in resp:
                        results["success"] += 1
                    else:
                        results["failed"] += 1
            except (ConnectionRefusedError, ConnectionResetError,
                    BrokenPipeError, socket.timeout, OSError,
                    json.JSONDecodeError, ValueError):
                with lock:
                    results["failed"] += 1

        threads = [threading.Thread(target=connect, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert results["success"] >= 2, (
            f"Some connections must succeed: {results}"
        )
        assert results["failed"] >= 3, (
            f"Rate limiting must reject excess connections: {results}"
        )


# ===================================================================
# Destructive tests (run last)
# ===================================================================

class TestHealthChecks:
    """Kill a backend, verify health checks remove it from rotation."""

    def test_unhealthy_backend_removed(self):
        global _backend_procs

        # Kill backend 9002
        _backend_procs[9002].kill()
        _backend_procs[9002].wait()

        # Wait for unhealthy detection: interval=2s * unhealthy_threshold=3 + margin
        time.sleep(10)

        # All WRR traffic on 8080 should go to 9001 only
        ports = set()
        for i in range(10):
            resp = tcp_exchange(8080, f"hc_verify_{i}")
            assert resp is not None, "Healthy backend must still respond"
            ports.add(resp["backend_port"])

        assert ports == {9001}, (
            f"Only healthy backend should receive traffic after 9002 dies: {ports}"
        )

        # Admin API should reflect unhealthy status
        status, data = admin_request("GET", "/backends")
        assert status == 200
        if isinstance(data, dict) and "web_backends" in data:
            for b in data["web_backends"]:
                if b.get("port") == 9002:
                    assert not b.get("healthy", True), (
                        f"Backend 9002 must be unhealthy in admin API: {b}"
                    )

    def test_healthy_threshold_respected(self):
        """After restart, backend must not be restored until
        healthy_threshold (4) consecutive successes are reached."""
        global _backend_procs

        # Restart backend 9002
        _backend_procs[9002] = start_backend(9002)

        # Wait slightly more than one health check interval (2s).
        # At most 1-2 successful probes have occurred; healthy_threshold=4 not met.
        time.sleep(3)

        status, data = admin_request("GET", "/backends")
        assert status == 200
        web_backends = data.get("web_backends", [])
        found = False
        for b in web_backends:
            if b.get("port") == 9002:
                found = True
                assert not b.get("healthy", True), (
                    "Backend 9002 was restored too quickly — "
                    "healthy_threshold (4) not respected. "
                    "Only 1-2 successful probes should have occurred."
                )
        assert found, "Backend 9002 not found in admin /backends response"

        # Now wait for full recovery: 4 successes * 2s interval + margin
        time.sleep(12)

        status, data = admin_request("GET", "/backends")
        assert status == 200
        web_backends = data.get("web_backends", [])
        for b in web_backends:
            if b.get("port") == 9002:
                assert b.get("healthy", False), (
                    "Backend 9002 should be healthy after threshold met"
                )


class TestDraining:
    """POST /backends/drain removes a backend from new-connection rotation."""

    def test_drain_stops_new_connections(self):
        # Determine which cache backend IP-hash currently selects
        resp = tcp_exchange(8082, "drain_pre")
        assert resp is not None
        original_port = resp["backend_port"]
        other_port = 9006 if original_port == 9007 else 9007

        # Drain the selected backend
        status, body = admin_request("POST", "/backends/drain", {
            "pool": "cache_backends",
            "address": "127.0.0.1",
            "port": original_port,
        })
        assert status == 200, f"Drain request failed: {status} {body}"

        time.sleep(1)

        # Traffic should now go to the other backend
        for i in range(5):
            resp = tcp_exchange(8082, f"drain_post_{i}")
            assert resp is not None
            assert resp["backend_port"] == other_port, (
                f"Drained backend {original_port} should not receive traffic; "
                f"got {resp['backend_port']}"
            )
