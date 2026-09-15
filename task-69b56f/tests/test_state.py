"""SOCKS5 conformance audit and proxy implementation tests.

"""

import concurrent.futures
import json
import os
import socket
import struct
import subprocess
import time

import pytest

PROXY_PORT = 1080
HTTP_PORT = 18080


def wait_for_port(port, host="127.0.0.1", timeout=10):
    """Block until a TCP port is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.2)
    return False


# ═══════════════════════════════════════════════════════════════════
# PART 1: Conformance report validation
# ═══════════════════════════════════════════════════════════════════


class TestConformanceReport:
    """Verify the conformance report identifies protocol violations."""

    @pytest.fixture(autouse=True)
    def load_report(self):
        path = "/app/conformance_report.json"
        assert os.path.exists(path), f"Conformance report not found at {path}"
        with open(path) as f:
            self.report = json.load(f)
        assert isinstance(self.report, list), "Report must be a JSON array"

    def _desc(self, entry):
        """Combine text fields for keyword matching."""
        parts = []
        for key in ("description", "section", "rfc", "details", "violation"):
            val = entry.get(key, "")
            if val is not None:
                parts.append(str(val))
        return " ".join(parts).lower()

    def _any_match(self, predicate):
        return any(predicate(e) for e in self.report)

    def test_report_structure(self):
        """Report must be a non-empty JSON array with required fields."""
        assert len(self.report) >= 3, (
            f"Report has only {len(self.report)} entries — expected more violations"
        )
        for i, entry in enumerate(self.report):
            assert "rfc" in entry, f"Entry {i} missing 'rfc' field"
            assert "description" in entry, f"Entry {i} missing 'description' field"

    def test_minimum_violations_identified(self):
        """Report must identify at least 4 of 6 violation categories."""

        matchers = {
            "rsv_byte": lambda e: (
                "rsv" in self._desc(e) or "reserved" in self._desc(e)
            ),
            "auth_version": lambda e: (
                ("auth" in self._desc(e) or "1929" in self._desc(e)
                 or "subneg" in self._desc(e) or "sub-neg" in self._desc(e)
                 or "credential" in self._desc(e))
                and ("version" in self._desc(e) or "ver" in self._desc(e)
                     or "0x01" in self._desc(e) or "0x05" in self._desc(e)
                     or "reject" in self._desc(e))
            ),
            "ipv6_parsing": lambda e: (
                "ipv6" in self._desc(e) or "v6" in self._desc(e)
                or ("16" in self._desc(e)
                    and ("byte" in self._desc(e) or "octet" in self._desc(e)))
                or ("atyp" in self._desc(e) and "0x04" in self._desc(e))
                or ("address" in self._desc(e) and "length" in self._desc(e)
                    and "4" in self._desc(e))
            ),
            "command_code": lambda e: (
                ("command" in self._desc(e) or "bind" in self._desc(e)
                 or "udp" in self._desc(e) or "cmd" in self._desc(e))
                and ("0x07" in self._desc(e) or "not supported" in self._desc(e)
                     or "unsupported" in self._desc(e)
                     or "general" in self._desc(e)
                     or "reply" in self._desc(e) or "rep" in self._desc(e)
                     or "error code" in self._desc(e) or "wrong" in self._desc(e))
            ),
            "acl_domain": lambda e: (
                ("domain" in self._desc(e) or "dns" in self._desc(e)
                 or "fqdn" in self._desc(e) or "hostname" in self._desc(e)
                 or "name" in self._desc(e) or "atyp" in self._desc(e))
                and ("acl" in self._desc(e) or "access" in self._desc(e)
                     or "bypass" in self._desc(e) or "denied" in self._desc(e)
                     or "enforce" in self._desc(e) or "policy" in self._desc(e)
                     or "rule" in self._desc(e) or "allow" in self._desc(e)
                     or "filter" in self._desc(e) or "check" in self._desc(e))
            ),
            "bnd_fields": lambda e: (
                ("bnd" in self._desc(e) or "bound" in self._desc(e)
                 or "bind" in self._desc(e))
                and ("addr" in self._desc(e) or "port" in self._desc(e)
                     or "address" in self._desc(e) or "local" in self._desc(e)
                     or "ephemeral" in self._desc(e) or "target" in self._desc(e)
                     or "outbound" in self._desc(e))
            ),
        }

        matched = {
            name for name, matcher in matchers.items()
            if self._any_match(matcher)
        }
        assert len(matched) >= 4, (
            f"Only {len(matched)}/6 violation categories identified: {matched}. "
            f"Need at least 4 of: {set(matchers.keys())}"
        )


# ═══════════════════════════════════════════════════════════════════
# PART 2: New proxy conformance tests
# ═══════════════════════════════════════════════════════════════════


class TestProxyConformance:
    """Verify /app/proxy.py is a conformant SOCKS5 implementation."""

    @classmethod
    def setup_class(cls):
        """Start HTTP target server and the new SOCKS5 proxy."""
        # Kill anything on the test ports
        subprocess.run(
            ["fuser", "-k", f"{PROXY_PORT}/tcp"],
            capture_output=True, timeout=5,
        )
        subprocess.run(
            ["fuser", "-k", f"{HTTP_PORT}/tcp"],
            capture_output=True, timeout=5,
        )
        time.sleep(1)

        os.makedirs("/tmp/test_www", exist_ok=True)
        with open("/tmp/test_www/hello.txt", "w") as f:
            f.write("Hello, SOCKS5 World!")

        cls.http_proc = subprocess.Popen(
            [
                "python3", "-m", "http.server", str(HTTP_PORT),
                "--bind", "127.0.0.1", "--directory", "/tmp/test_www",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        proxy_script = "/app/proxy.py"
        assert os.path.exists(proxy_script), f"Proxy not found at {proxy_script}"

        cls.proxy_proc = subprocess.Popen(
            ["python3", proxy_script],
            stdout=subprocess.DEVNULL,
            stderr=open("/tmp/proxy_stderr.log", "w"),
        )

        assert wait_for_port(HTTP_PORT, timeout=10), "HTTP server did not start"
        assert wait_for_port(PROXY_PORT, timeout=10), (
            "SOCKS5 proxy did not start on port 1080"
        )

    @classmethod
    def teardown_class(cls):
        """Terminate helper processes."""
        for proc in (cls.proxy_proc, cls.http_proc):
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

    # ── Wire-format conformance (RFC 1928 Section 6) ──

    def test_reply_wire_format(self):
        """Reply must have VER=0x05 and RSV=0x00."""
        with socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=10) as s:
            s.settimeout(10)
            s.sendall(b"\x05\x01\x00")
            assert s.recv(2) == b"\x05\x00"
            req = struct.pack("BBBB", 0x05, 0x01, 0x00, 0x01)
            req += socket.inet_aton("127.0.0.1") + struct.pack("!H", HTTP_PORT)
            s.sendall(req)
            resp = s.recv(256)

        assert len(resp) >= 10, f"Reply too short ({len(resp)} bytes)"
        ver, rep, rsv, atyp = struct.unpack("BBBB", resp[:4])
        assert ver == 0x05, f"VER must be 0x05, got {ver:#x}"
        assert rep == 0x00, f"REP must be 0x00 (success), got {rep:#x}"
        assert rsv == 0x00, f"RSV must be 0x00, got {rsv:#x}"
        assert atyp in (0x01, 0x04), f"ATYP must be IPv4 or IPv6, got {atyp:#x}"

    def test_bnd_port_is_ephemeral(self):
        """BND.PORT must be the proxy's outbound local port, not the target."""
        with socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=10) as s:
            s.settimeout(10)
            s.sendall(b"\x05\x01\x00")
            assert s.recv(2) == b"\x05\x00"
            req = struct.pack("BBBB", 0x05, 0x01, 0x00, 0x01)
            req += socket.inet_aton("127.0.0.1") + struct.pack("!H", HTTP_PORT)
            s.sendall(req)
            resp = s.recv(256)

        assert len(resp) >= 10
        atyp = resp[3]
        if atyp == 0x01:
            bnd_port = struct.unpack("!H", resp[8:10])[0]
        else:
            bnd_port = struct.unpack("!H", resp[20:22])[0]
        assert bnd_port != HTTP_PORT, (
            f"BND.PORT={bnd_port} equals target port {HTTP_PORT}"
        )
        assert bnd_port > 0, f"BND.PORT must be non-zero, got {bnd_port}"

    # ── Authentication (RFC 1929) ──

    def test_auth_subneg_works(self):
        """Auth sub-negotiation with VER=0x01 must succeed for valid creds."""
        with socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=5) as s:
            s.settimeout(5)
            s.sendall(b"\x05\x01\x02")
            assert s.recv(2) == b"\x05\x02"
            user, pw = b"alice", b"wonderland99"
            s.sendall(
                struct.pack("BB", 0x01, len(user)) + user
                + struct.pack("B", len(pw)) + pw
            )
            resp = s.recv(2)
        assert resp == b"\x01\x00", (
            f"Expected auth success (01 00), got {resp.hex()}"
        )

    def test_auth_bad_credentials(self):
        """Wrong password must return auth status != 0x00."""
        with socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=5) as s:
            s.settimeout(5)
            s.sendall(b"\x05\x01\x02")
            assert s.recv(2) == b"\x05\x02"
            user, pw = b"alice", b"wrongpass"
            s.sendall(
                struct.pack("BB", 0x01, len(user)) + user
                + struct.pack("B", len(pw)) + pw
            )
            resp = s.recv(2)
        assert len(resp) == 2 and resp[0] == 0x01 and resp[1] != 0x00, (
            f"Expected auth failure, got {resp.hex()}"
        )

    # ── Command handling ──

    def test_bind_returns_cmd_not_supported(self):
        """BIND (CMD=0x02) must return REP=0x07."""
        with socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=5) as s:
            s.settimeout(5)
            s.sendall(b"\x05\x01\x00")
            s.recv(2)
            req = struct.pack("BBBB", 0x05, 0x02, 0x00, 0x01)
            req += socket.inet_aton("127.0.0.1") + struct.pack("!H", HTTP_PORT)
            s.sendall(req)
            resp = s.recv(10)
        assert len(resp) >= 2, "Reply too short"
        assert resp[1] == 0x07, (
            f"Expected REP=0x07 (CMD_NOT_SUPPORTED), got {resp[1]:#x}"
        )

    def test_udp_assoc_returns_cmd_not_supported(self):
        """UDP ASSOCIATE (CMD=0x03) must return REP=0x07."""
        with socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=5) as s:
            s.settimeout(5)
            s.sendall(b"\x05\x01\x00")
            s.recv(2)
            req = struct.pack("BBBB", 0x05, 0x03, 0x00, 0x01)
            req += socket.inet_aton("0.0.0.0") + struct.pack("!H", 0)
            s.sendall(req)
            resp = s.recv(10)
        assert len(resp) >= 2, "Reply too short"
        assert resp[1] == 0x07, (
            f"Expected REP=0x07 (CMD_NOT_SUPPORTED), got {resp[1]:#x}"
        )

    # ── ACL enforcement ──

    def test_acl_deny_ipv4(self):
        """CONNECT to 10.0.0.1 (denied by ACL) must return REP=0x02."""
        with socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=5) as s:
            s.settimeout(5)
            s.sendall(b"\x05\x01\x00")
            s.recv(2)
            req = struct.pack("BBBB", 0x05, 0x01, 0x00, 0x01)
            req += socket.inet_aton("10.0.0.1") + struct.pack("!H", 80)
            s.sendall(req)
            resp = s.recv(10)
        assert len(resp) >= 2, "Reply too short"
        assert resp[1] == 0x02, f"Expected REP=0x02, got {resp[1]:#x}"

    def test_acl_deny_via_domain(self):
        """Domain resolving to a denied IP must be rejected by ACL."""
        hosts_line = "10.255.255.1 denied-host.test\n"
        with open("/etc/hosts", "a") as f:
            f.write(hosts_line)

        try:
            with socket.create_connection(
                ("127.0.0.1", PROXY_PORT), timeout=15
            ) as s:
                s.settimeout(15)
                s.sendall(b"\x05\x01\x00")
                s.recv(2)
                domain = b"denied-host.test"
                req = struct.pack("BBBB", 0x05, 0x01, 0x00, 0x03)
                req += struct.pack("B", len(domain)) + domain
                req += struct.pack("!H", 39999)
                s.sendall(req)
                resp = s.recv(10)
            assert len(resp) >= 2, "Reply too short"
            assert resp[1] == 0x02, (
                f"Expected REP=0x02 (NOT_ALLOWED) for denied domain, "
                f"got {resp[1]:#x}"
            )
        finally:
            with open("/etc/hosts", "r") as f:
                lines = f.readlines()
            with open("/etc/hosts", "w") as f:
                for line in lines:
                    if "denied-host.test" not in line:
                        f.write(line)

    # ── Address types ──

    def test_ipv6_atyp_parsed(self):
        """CONNECT with ATYP=0x04 (IPv6) must handle 16-byte address."""
        with socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=10) as s:
            s.settimeout(10)
            s.sendall(b"\x05\x01\x00")
            resp = s.recv(2)
            assert resp == b"\x05\x00", f"Handshake failed: {resp.hex()}"
            ipv6_addr = socket.inet_pton(socket.AF_INET6, "::1")
            assert len(ipv6_addr) == 16
            req = struct.pack("BBBB", 0x05, 0x01, 0x00, 0x04)
            req += ipv6_addr + struct.pack("!H", HTTP_PORT)
            s.sendall(req)
            resp = s.recv(256)

        assert len(resp) >= 4, (
            f"Reply too short ({len(resp)} bytes) — proxy likely crashed "
            f"parsing IPv6 address"
        )
        ver, rep = resp[0], resp[1]
        assert ver == 0x05, f"VER must be 0x05, got {ver:#x}"
        # Connection to ::1 may succeed or fail depending on IPv6 support,
        # but must NOT be a general server failure from a parsing crash
        assert rep in (0x00, 0x03, 0x04, 0x05), (
            f"Expected valid REP for IPv6 CONNECT, got {rep:#x}"
        )

    # ── End-to-end relay ──

    def test_relay_ipv4(self):
        """Basic HTTP fetch through SOCKS5 proxy (IPv4, NO AUTH)."""
        r = subprocess.run(
            [
                "curl", "-s", "--socks5", f"127.0.0.1:{PROXY_PORT}",
                f"http://127.0.0.1:{HTTP_PORT}/hello.txt", "--max-time", "10",
            ],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"curl failed: {r.stderr}"
        assert r.stdout.strip() == "Hello, SOCKS5 World!"

    def test_relay_domain(self):
        """HTTP fetch through SOCKS5 proxy with domain name resolution."""
        r = subprocess.run(
            [
                "curl", "-s", "--socks5-hostname",
                f"127.0.0.1:{PROXY_PORT}",
                f"http://localhost:{HTTP_PORT}/hello.txt", "--max-time", "10",
            ],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"curl failed: {r.stderr}"
        assert r.stdout.strip() == "Hello, SOCKS5 World!"

    def test_relay_authenticated(self):
        """HTTP fetch through SOCKS5 proxy with USERNAME/PASSWORD auth."""
        r = subprocess.run(
            [
                "curl", "-s", "--socks5", f"127.0.0.1:{PROXY_PORT}",
                "--proxy-user", "bob:builder42",
                f"http://127.0.0.1:{HTTP_PORT}/hello.txt", "--max-time", "10",
            ],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"curl failed: {r.stderr}"
        assert r.stdout.strip() == "Hello, SOCKS5 World!"

    # ── Concurrency ──

    def test_concurrent_connections(self):
        """Five simultaneous HTTP fetches through the proxy must all succeed."""
        def fetch(_):
            r = subprocess.run(
                [
                    "curl", "-s", "--socks5", f"127.0.0.1:{PROXY_PORT}",
                    f"http://127.0.0.1:{HTTP_PORT}/hello.txt",
                    "--max-time", "15",
                ],
                capture_output=True, text=True,
            )
            return r.stdout.strip()

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(fetch, range(5)))

        assert all(r == "Hello, SOCKS5 World!" for r in results), (
            f"Some concurrent requests failed: {results}"
        )
