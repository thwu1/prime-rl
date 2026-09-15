#!/usr/bin/env python3
"""Tests for Pest Control Server.

Verifies the server correctly implements the Pest Control binary protocol:
accepts SiteVisit messages from clients, connects to the Authority Server,
and reconciles population control policies.
"""

import json
import os
import signal
import socket
import struct
import subprocess
import time
import urllib.request

import pytest

SERVER_PORT = 9000
AUTH_BIN_PORT = 20547
AUTH_HTTP_PORT = 20548
STARTUP_TIMEOUT = 12

# ========== Binary protocol helpers ==========

def _u8(v):
    return struct.pack('>B', v)

def _u32(v):
    return struct.pack('>I', v)

def _bstr(s):
    b = s.encode('ascii')
    return _u32(len(b)) + b

def _checksum(data):
    return (256 - sum(data) % 256) % 256

def _frame(mt, payload):
    ln = 1 + 4 + len(payload) + 1
    raw = _u8(mt) + _u32(ln) + payload
    return raw + _u8(_checksum(raw))

def make_hello():
    return _frame(0x50, _bstr("pestcontrol") + _u32(1))

def make_site_visit(site, pops):
    """pops is list of (species_str, count_int) tuples."""
    body = _u32(site) + _u32(len(pops))
    for species, count in pops:
        body += _bstr(species) + _u32(count)
    return _frame(0x58, body)

def _recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf

def recv_msg(sock):
    """Read one framed message. Asserts valid checksum."""
    t = _recv_exact(sock, 1)
    lb = _recv_exact(sock, 4)
    total = struct.unpack('>I', lb)[0]
    rest = _recv_exact(sock, total - 5)
    full = t + lb + rest
    assert sum(full) % 256 == 0, f"bad checksum (sum={sum(full) % 256})"
    return t[0], rest[:-1]

def _pu32(data, off):
    return struct.unpack('>I', data[off:off+4])[0], off + 4

def _pstr(data, off):
    n, off = _pu32(data, off)
    return data[off:off+n].decode('ascii'), off + n

# ========== HTTP helpers ==========

def _http_reset():
    urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:{AUTH_HTTP_PORT}/reset", method='POST'), timeout=5)

def _http_policies(site=None):
    url = f"http://127.0.0.1:{AUTH_HTTP_PORT}/policies"
    if site is not None:
        url += f"/{site}"
    return json.loads(urllib.request.urlopen(url, timeout=5).read())

def _wait_for_state(site, expected_set, timeout=12.0):
    """Poll until policies == {(species, action), ...}."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        ps = _http_policies(site)
        got = {(p["species"], p["action"]) for p in ps}
        if got == expected_set:
            return ps
        time.sleep(0.3)
    return _http_policies(site)

def _wait_for_count(site, count, timeout=12.0):
    """Poll until len(policies) == count."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        ps = _http_policies(site)
        if len(ps) == count:
            return ps
        time.sleep(0.3)
    return _http_policies(site)

# ========== Client helper ==========

def _connect_and_visit(site, pops):
    """Open TCP, Hello handshake, send SiteVisit. Returns the socket."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(8.0)
    s.connect(("127.0.0.1", SERVER_PORT))
    s.sendall(make_hello())
    mt, _ = recv_msg(s)
    assert mt == 0x50, f"expected Hello (0x50), got 0x{mt:02x}"
    s.sendall(make_site_visit(site, pops))
    return s

# ========== Fixtures ==========

@pytest.fixture(scope="module")
def auth_server():
    """Start the Authority Server once for all tests in this module."""
    proc = subprocess.Popen(
        ["python3", "/app/authority_server.py"],
        preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{AUTH_HTTP_PORT}/policies", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
        pytest.fail("Authority server did not start")
    yield proc
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=5)
        except Exception:
            pass


@pytest.fixture(autouse=True)
def solver_server(auth_server):
    """Start the solver's server for each test; reset authority state."""
    _http_reset()
    proc = subprocess.Popen(
        ["bash", "/app/run.sh"],
        preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect(("127.0.0.1", SERVER_PORT))
            s.close()
            break
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.2)
    else:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
        pytest.fail("Solver server did not start")
    time.sleep(0.3)
    yield proc
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=5)
        except Exception:
            pass

# ========== Tests: Hello handshake ==========

class TestHello:
    def test_hello_exchange(self):
        """Server accepts Hello and responds with valid Hello."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect(("127.0.0.1", SERVER_PORT))
        s.sendall(make_hello())
        mt, content = recv_msg(s)
        assert mt == 0x50, f"expected Hello (0x50), got 0x{mt:02x}"
        proto, off = _pstr(content, 0)
        ver, off = _pu32(content, off)
        assert proto == "pestcontrol"
        assert ver == 1
        s.close()

    def test_hello_checksum_valid(self):
        """Server's Hello message passes checksum validation."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect(("127.0.0.1", SERVER_PORT))
        s.sendall(make_hello())
        # recv_msg asserts checksum == 0 mod 256
        mt, _ = recv_msg(s)
        assert mt == 0x50
        s.close()

# ========== Tests: Cull policies ==========

class TestCull:
    def test_count_above_max(self):
        """Species count > max triggers a cull policy."""
        # Site 12345: "long-tailed rat" min=0, max=10
        sock = _connect_and_visit(12345, [
            ("long-tailed rat", 20),
            ("common dog", 2),
            ("blue whale", 10),
        ])
        ps = _wait_for_state(12345, {("long-tailed rat", "cull")})
        got = {(p["species"], p["action"]) for p in ps}
        assert ("long-tailed rat", "cull") in got
        assert not any(p["species"] == "common dog" for p in ps)
        assert not any(p["species"] == "blue whale" for p in ps)
        sock.close()

    def test_max_zero_edge(self):
        """Species with max=0: any count > 0 requires cull."""
        # Site 11111: "grey squirrel" min=0, max=0
        sock = _connect_and_visit(11111, [
            ("pine marten", 5),
            ("red fox", 3),
            ("grey squirrel", 1),
        ])
        ps = _wait_for_state(11111, {("grey squirrel", "cull")})
        got = {(p["species"], p["action"]) for p in ps}
        assert ("grey squirrel", "cull") in got
        sock.close()

# ========== Tests: Conserve policies ==========

class TestConserve:
    def test_count_below_min(self):
        """Species count < min triggers a conserve policy."""
        # Site 12345: "blue whale" min=5, max=20
        sock = _connect_and_visit(12345, [
            ("long-tailed rat", 5),
            ("common dog", 2),
            ("blue whale", 2),
        ])
        ps = _wait_for_state(12345, {("blue whale", "conserve")})
        got = {(p["species"], p["action"]) for p in ps}
        assert ("blue whale", "conserve") in got
        sock.close()

    def test_missing_species_is_zero(self):
        """Unmentioned species has count 0; if min > 0, conserve."""
        # Site 12345: "common dog" min=1 -- not mentioned => count=0 => conserve
        # "blue whale" min=5 -- not mentioned => conserve
        sock = _connect_and_visit(12345, [
            ("long-tailed rat", 5),
        ])
        expected = {("common dog", "conserve"), ("blue whale", "conserve")}
        ps = _wait_for_state(12345, expected)
        got = {(p["species"], p["action"]) for p in ps}
        assert ("common dog", "conserve") in got
        assert ("blue whale", "conserve") in got
        sock.close()

# ========== Tests: In-range (no policy) ==========

class TestInRange:
    def test_all_in_range(self):
        """All species in range => no policies created."""
        sock = _connect_and_visit(12345, [
            ("long-tailed rat", 5),
            ("common dog", 2),
            ("blue whale", 10),
        ])
        time.sleep(4)
        ps = _http_policies(12345)
        assert len(ps) == 0, f"Expected no policies, got {ps}"
        sock.close()

    def test_at_boundaries(self):
        """Counts exactly at min and max are within range."""
        # Site 67890: "northern pike" min=2, max=8; "river otter" min=0, max=5
        sock = _connect_and_visit(67890, [
            ("northern pike", 2),   # exactly min
            ("river otter", 5),     # exactly max
        ])
        time.sleep(4)
        ps = _http_policies(67890)
        assert len(ps) == 0, f"Expected no policies, got {ps}"
        sock.close()

# ========== Tests: Policy reconciliation ==========

class TestReconciliation:
    def test_update_conserve_to_cull(self):
        """Population change switches policy from conserve to cull."""
        # Site 22222: "alpha" min=10, max=20
        s1 = _connect_and_visit(22222, [("alpha", 5)])  # < 10 => conserve
        _wait_for_state(22222, {("alpha", "conserve")})
        s1.close()
        time.sleep(0.5)

        s2 = _connect_and_visit(22222, [("alpha", 25)])  # > 20 => cull
        ps = _wait_for_state(22222, {("alpha", "cull")})
        got = {(p["species"], p["action"]) for p in ps}
        assert got == {("alpha", "cull")}
        s2.close()

    def test_remove_policy_when_in_range(self):
        """Policy is deleted when population returns to range."""
        s1 = _connect_and_visit(22222, [("alpha", 5)])  # conserve
        _wait_for_state(22222, {("alpha", "conserve")})
        s1.close()
        time.sleep(0.5)

        s2 = _connect_and_visit(22222, [("alpha", 15)])  # in range
        ps = _wait_for_count(22222, 0)
        assert len(ps) == 0
        s2.close()

    def test_no_duplicate_policies(self):
        """After settling, at most one policy per species."""
        s1 = _connect_and_visit(12345, [
            ("long-tailed rat", 20), ("common dog", 0), ("blue whale", 2),
        ])
        expected = {("long-tailed rat", "cull"), ("blue whale", "conserve")}
        _wait_for_state(12345, expected)
        s1.close()
        time.sleep(0.5)

        # Second visit with same data
        s2 = _connect_and_visit(12345, [
            ("long-tailed rat", 20), ("common dog", 0), ("blue whale", 2),
        ])
        time.sleep(4)
        ps = _http_policies(12345)
        species_counts = {}
        for p in ps:
            species_counts[p["species"]] = species_counts.get(p["species"], 0) + 1
        for sp, cnt in species_counts.items():
            assert cnt == 1, f"Species '{sp}' has {cnt} policies (expected 1)"
        s2.close()

# ========== Tests: Mixed actions ==========

class TestMixedActions:
    def test_multiple_species_different_actions(self):
        """Visit with species needing cull, conserve, and nothing."""
        # Site 12345: rat(0-10), dog(1-3), whale(5-20)
        sock = _connect_and_visit(12345, [
            ("long-tailed rat", 20),  # >10 => cull
            ("common dog", 0),        # <1  => conserve
            ("blue whale", 10),       # in range
        ])
        expected = {("long-tailed rat", "cull"), ("common dog", "conserve")}
        ps = _wait_for_state(12345, expected)
        got = {(p["species"], p["action"]) for p in ps}
        assert got == expected
        sock.close()

    def test_four_species_site(self):
        """Site with 4 controlled species, mixed outcomes."""
        # Site 44444: spotted newt(1-5), brown hare(0-100),
        #             marsh warbler(10-50), water vole(5-15)
        sock = _connect_and_visit(44444, [
            ("spotted newt", 0),      # <1  => conserve
            ("brown hare", 50),       # in range
            ("marsh warbler", 60),    # >50 => cull
            ("water vole", 10),       # in range
        ])
        expected = {("spotted newt", "conserve"), ("marsh warbler", "cull")}
        ps = _wait_for_state(44444, expected)
        got = {(p["species"], p["action"]) for p in ps}
        assert got == expected
        sock.close()

# ========== Tests: Edge cases ==========

class TestEdgeCases:
    def test_uncontrolled_species_ignored(self):
        """Species not in targets requires no policy."""
        sock = _connect_and_visit(12345, [
            ("long-tailed rat", 5),
            ("common dog", 2),
            ("blue whale", 10),
            ("unknown animal", 999),
        ])
        time.sleep(4)
        ps = _http_policies(12345)
        assert not any(p["species"] == "unknown animal" for p in ps)
        sock.close()

    def test_empty_targets_site(self):
        """Site with no controlled species => no policies."""
        sock = _connect_and_visit(33333, [
            ("some animal", 100),
        ])
        time.sleep(4)
        ps = _http_policies(33333)
        assert len(ps) == 0
        sock.close()

    def test_non_conflicting_duplicates(self):
        """Duplicate species with identical count is allowed."""
        sock = _connect_and_visit(12345, [
            ("long-tailed rat", 20),
            ("long-tailed rat", 20),  # duplicate but same count
            ("common dog", 2),
            ("blue whale", 10),
        ])
        ps = _wait_for_state(12345, {("long-tailed rat", "cull")})
        got = {(p["species"], p["action"]) for p in ps}
        assert ("long-tailed rat", "cull") in got
        sock.close()

    def test_species_at_zero_with_min_zero(self):
        """Count=0 with min=0 is in range; no policy needed."""
        # Site 11111: grey squirrel(0-0), red fox(0-6), pine marten(3-12)
        # All species absent => count 0 for each
        # pine marten: 0 < 3 => conserve
        # grey squirrel: 0 in [0,0] => ok
        # red fox: 0 in [0,6] => ok
        sock = _connect_and_visit(11111, [])
        ps = _wait_for_state(11111, {("pine marten", "conserve")})
        got = {(p["species"], p["action"]) for p in ps}
        assert ("pine marten", "conserve") in got
        assert not any(p["species"] == "grey squirrel" for p in ps)
        assert not any(p["species"] == "red fox" for p in ps)
        sock.close()

    def test_concurrent_sites(self):
        """Different sites are managed independently."""
        s1 = _connect_and_visit(12345, [
            ("long-tailed rat", 20), ("common dog", 2), ("blue whale", 10),
        ])
        s2 = _connect_and_visit(67890, [
            ("northern pike", 1), ("river otter", 3),
        ])
        _wait_for_state(12345, {("long-tailed rat", "cull")})
        _wait_for_state(67890, {("northern pike", "conserve")})

        ps1 = _http_policies(12345)
        ps2 = _http_policies(67890)
        assert {(p["species"], p["action"]) for p in ps1} == {("long-tailed rat", "cull")}
        assert {(p["species"], p["action"]) for p in ps2} == {("northern pike", "conserve")}
        s1.close()
        s2.close()

    def test_conflicting_duplicates_error(self):
        """SiteVisit with conflicting counts for same species => error."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect(("127.0.0.1", SERVER_PORT))
        s.sendall(make_hello())
        mt, _ = recv_msg(s)
        assert mt == 0x50

        # conflicting: "long-tailed rat" appears with count 5 and 10
        s.sendall(make_site_visit(12345, [
            ("long-tailed rat", 5),
            ("long-tailed rat", 10),
        ]))

        # server should send Error or close
        try:
            mt, _ = recv_msg(s)
            assert mt == 0x51, f"expected Error (0x51), got 0x{mt:02x}"
        except ConnectionError:
            pass  # closing is also acceptable

        time.sleep(1)
        ps = _http_policies(12345)
        assert len(ps) == 0, "No policies should exist after error"
        s.close()
