#!/usr/bin/env python3

"""
Protocol conformance and policy reconciliation tests for the Pest Control server.

Each test uses unique site IDs to avoid cross-test interference.
"""

import asyncio
import json
import os
import signal
import socket
import struct
import subprocess
import time

import pytest

HOST = "127.0.0.1"
PORT = 9000
AUTH_PORT = 20547
STATE_FILE = "/tmp/authority_state.json"
SETTLE_TIME = 2.5


# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------

def compute_checksum(data):
    return (256 - sum(data) % 256) % 256


def verify_checksum(data):
    return sum(data) % 256 == 0


def build_msg(msg_type, content):
    total_len = 1 + 4 + len(content) + 1
    header = struct.pack("!BI", msg_type, total_len)
    body = header + content
    return body + bytes([compute_checksum(body)])


async def read_n(reader, n, timeout=10.0):
    data = b""
    deadline = asyncio.get_event_loop().time() + timeout
    while len(data) < n:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        chunk = await asyncio.wait_for(reader.read(n - len(data)), timeout=remaining)
        if not chunk:
            raise ConnectionError("EOF")
        data += chunk
    return data


async def read_message(reader, timeout=10.0):
    type_byte = await read_n(reader, 1, timeout)
    length_bytes = await read_n(reader, 4, timeout)
    total_length = struct.unpack("!I", length_bytes)[0]
    rest = await read_n(reader, total_length - 5, timeout)
    full = type_byte + length_bytes + rest
    assert verify_checksum(full), "Bad checksum in received message"
    return type_byte[0], rest[:-1]


class PestClient:
    """Speaks the Pest Control binary protocol as a site visitor client."""

    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

    async def send_hello(self):
        proto = b"pestcontrol"
        content = struct.pack("!I", len(proto)) + proto + struct.pack("!I", 1)
        self.writer.write(build_msg(0x50, content))
        await self.writer.drain()

    async def read_hello(self, timeout=10.0):
        msg_type, content = await read_message(self.reader, timeout)
        assert msg_type == 0x50, f"Expected Hello (0x50), got 0x{msg_type:02x}"

    async def send_site_visit(self, site, populations):
        """populations: list of (species_str, count_int)."""
        c = struct.pack("!II", site, len(populations))
        for species, count in populations:
            sb = species.encode("ascii")
            c += struct.pack("!I", len(sb)) + sb + struct.pack("!I", count)
        self.writer.write(build_msg(0x58, c))
        await self.writer.drain()

    async def read_error(self, timeout=10.0):
        msg_type, content = await read_message(self.reader, timeout)
        assert msg_type == 0x51, f"Expected Error (0x51), got 0x{msg_type:02x}"
        mlen = struct.unpack_from("!I", content, 0)[0]
        return content[4:4 + mlen].decode("ascii")

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def connect():
    r, w = await asyncio.open_connection(HOST, PORT)
    return PestClient(r, w)


def get_policies(site_id):
    """Read current policies for a site from the authority state file."""
    with open(STATE_FILE) as f:
        state = json.load(f)
    site_key = str(site_id)
    if site_key not in state:
        return {}
    return {pd["species"]: pd["action"] for pd in state[site_key].values()}


def get_raw_policies(site_id):
    """Read raw policy list (with IDs) for duplicate checking."""
    with open(STATE_FILE) as f:
        state = json.load(f)
    site_key = str(site_id)
    return state.get(site_key, {})


# ---------------------------------------------------------------------------
# Session fixtures: start authority + solver
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def authority_proc():
    proc = subprocess.Popen(
        ["python3", "/app/authority_server.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ready = False
    for _ in range(50):
        try:
            s = socket.create_connection((HOST, AUTH_PORT), timeout=0.2)
            s.close()
            ready = True
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.2)
    if not ready:
        proc.kill()
        pytest.fail("Authority server did not start within 10 seconds")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session", autouse=True)
def server_proc(authority_proc):
    proc = subprocess.Popen(
        ["bash", "/app/run.sh"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )
    ready = False
    for _ in range(100):
        try:
            s = socket.create_connection((HOST, PORT), timeout=0.2)
            s.close()
            ready = True
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.2)
    if not ready:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        pytest.fail("Solver server did not start within 20 seconds")
    yield proc
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ===========================================================================
# Basic policy creation
# ===========================================================================

def test_basic_cull():
    """Species above target max must produce a cull policy."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # site 1001: dog [1, 5] — send count 10 (too many)
        await c.send_site_visit(1001, [("dog", 10)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1001)
        assert p.get("dog") == "cull", f"Expected cull for dog, got {p}"
        await c.close()
    asyncio.run(_run())


def test_basic_conserve():
    """Species below target min must produce a conserve policy."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # site 1002: cat [5, 10] — send count 2 (too few)
        await c.send_site_visit(1002, [("cat", 2)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1002)
        assert p.get("cat") == "conserve", f"Expected conserve for cat, got {p}"
        await c.close()
    asyncio.run(_run())


def test_within_range_no_policy():
    """Species within target range must have no policy."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # site 1003: bird [3, 8] — send count 5 (within range)
        await c.send_site_visit(1003, [("bird", 5)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1003)
        assert "bird" not in p, f"Expected no policy for bird, got {p}"
        await c.close()
    asyncio.run(_run())


# ===========================================================================
# Edge cases: zero count, uncontrolled species
# ===========================================================================

def test_missing_species_zero_count():
    """Unobserved controlled species has implicit count 0."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # site 1004: deer [5, 20] — send empty visit (deer not observed = count 0)
        await c.send_site_visit(1004, [])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1004)
        assert p.get("deer") == "conserve", f"Expected conserve for unobserved deer, got {p}"
        await c.close()
    asyncio.run(_run())


def test_uncontrolled_species_ignored():
    """Species not in target populations must have no policy created."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # site 1005: bee [100, 500] — send bee=200 (in range) + elephant (uncontrolled)
        await c.send_site_visit(1005, [("bee", 200), ("elephant", 50)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1005)
        assert "bee" not in p, f"Expected no policy for in-range bee, got {p}"
        assert "elephant" not in p, f"Expected no policy for uncontrolled elephant, got {p}"
        await c.close()
    asyncio.run(_run())


# ===========================================================================
# Multi-species reconciliation
# ===========================================================================

def test_multi_species_reconciliation():
    """Multiple species with different states must each get the correct policy."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # site 1006: rat [0,10], sparrow [5,15], fish [2,7]
        await c.send_site_visit(1006, [("rat", 15), ("sparrow", 3), ("fish", 5)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1006)
        assert p.get("rat") == "cull", f"rat 15>10 should be cull, got {p}"
        assert p.get("sparrow") == "conserve", f"sparrow 3<5 should be conserve, got {p}"
        assert "fish" not in p, f"fish 5 in [2,7] should have no policy, got {p}"
        await c.close()
    asyncio.run(_run())


# ===========================================================================
# Policy updates on subsequent visits
# ===========================================================================

def test_policy_update_into_range():
    """Policy must be deleted when species comes into range on a new visit."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # site 1007: wolf [3, 7]
        # First visit: wolf=10 (cull)
        await c.send_site_visit(1007, [("wolf", 10)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1007)
        assert p.get("wolf") == "cull", f"Expected cull after first visit, got {p}"

        # Second visit: wolf=5 (within range — policy should be removed)
        await c.send_site_visit(1007, [("wolf", 5)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1007)
        assert "wolf" not in p, f"Expected no policy after wolf enters range, got {p}"
        await c.close()
    asyncio.run(_run())


def test_policy_flip_cull_to_conserve():
    """Policy must flip from cull to conserve when population changes dramatically."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # site 1014: elk [10, 20]
        # First visit: elk=25 (cull)
        await c.send_site_visit(1014, [("elk", 25)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1014)
        assert p.get("elk") == "cull", f"Expected cull after first visit, got {p}"

        # Second visit: elk=5 (conserve)
        await c.send_site_visit(1014, [("elk", 5)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1014)
        assert p.get("elk") == "conserve", f"Expected conserve after flip, got {p}"
        await c.close()
    asyncio.run(_run())


def test_policy_deletion_into_range():
    """Existing conserve policy must be deleted when species returns to range."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # site 1012: snake [5, 15]
        # First visit: snake=2 (conserve)
        await c.send_site_visit(1012, [("snake", 2)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1012)
        assert p.get("snake") == "conserve", f"Expected conserve, got {p}"

        # Second visit: snake=10 (within range)
        await c.send_site_visit(1012, [("snake", 10)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1012)
        assert "snake" not in p, f"Expected no policy for in-range snake, got {p}"
        await c.close()
    asyncio.run(_run())


# ===========================================================================
# Concurrent handling
# ===========================================================================

def test_concurrent_sites():
    """Multiple sites handled concurrently through different client connections."""
    async def _run():
        c1 = await connect()
        await c1.send_hello()
        await c1.read_hello()
        c2 = await connect()
        await c2.send_hello()
        await c2.read_hello()

        # site 1009: fox [1, 5]; site 1010: bear [0, 3]
        await c1.send_site_visit(1009, [("fox", 10)])
        await c2.send_site_visit(1010, [("bear", 5)])
        await asyncio.sleep(SETTLE_TIME)

        p1 = get_policies(1009)
        p2 = get_policies(1010)
        assert p1.get("fox") == "cull", f"fox 10>5 should be cull, got {p1}"
        assert p2.get("bear") == "cull", f"bear 5>3 should be cull, got {p2}"
        await c1.close()
        await c2.close()
    asyncio.run(_run())


# ===========================================================================
# Duplicate policy prevention
# ===========================================================================

def test_no_duplicate_policies():
    """At settlement, at most one policy per species must exist."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # site 1011: owl [2, 8]
        await c.send_site_visit(1011, [("owl", 15)])
        await asyncio.sleep(SETTLE_TIME)
        raw = get_raw_policies(1011)
        species_list = [pd["species"] for pd in raw.values()]
        assert len(species_list) == len(set(species_list)), (
            f"Duplicate policies detected: {species_list}"
        )
        assert any(pd["species"] == "owl" for pd in raw.values()), (
            f"Expected owl policy, got {raw}"
        )
        await c.close()
    asyncio.run(_run())


# ===========================================================================
# SiteVisit validation: duplicate species
# ===========================================================================

def test_conflicting_duplicate_species():
    """SiteVisit with conflicting counts for same species must trigger error."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # Conflicting: ant appears with count 20 and count 30
        await c.send_site_visit(9001, [("ant", 20), ("ant", 30)])
        msg = await c.read_error(timeout=10.0)
        assert len(msg) > 0
        await c.close()
    asyncio.run(_run())


def test_nonconflicting_duplicate_species():
    """SiteVisit with identical counts for same species must NOT be an error."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # site 1008: ant [10, 50] — non-conflicting duplicate (both 60)
        await c.send_site_visit(1008, [("ant", 60), ("ant", 60)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1008)
        assert p.get("ant") == "cull", f"ant 60>50 should be cull, got {p}"
        await c.close()
    asyncio.run(_run())


# ===========================================================================
# Empty target populations
# ===========================================================================

def test_empty_target_populations():
    """Site with no controlled species — no policies regardless of observations."""
    async def _run():
        c = await connect()
        await c.send_hello()
        await c.read_hello()
        # site 1013: empty targets
        await c.send_site_visit(1013, [("parrot", 100)])
        await asyncio.sleep(SETTLE_TIME)
        p = get_policies(1013)
        assert len(p) == 0, f"Expected no policies for empty-target site, got {p}"
        await c.close()
    asyncio.run(_run())


# ===========================================================================
# Checksum and protocol enforcement
# ===========================================================================

def test_checksum_validation():
    """Server must reject messages with invalid checksums."""
    async def _run():
        r, w = await asyncio.open_connection(HOST, PORT)
        # Build Hello with intentionally wrong checksum
        proto = b"pestcontrol"
        content = struct.pack("!I", len(proto)) + proto + struct.pack("!I", 1)
        total_len = 1 + 4 + len(content) + 1
        header = struct.pack("!BI", 0x50, total_len)
        body = header + content
        good_cs = compute_checksum(body)
        bad_cs = (good_cs + 1) % 256
        w.write(body + bytes([bad_cs]))
        await w.drain()

        # Server must NOT respond with Hello — expect error or disconnect
        try:
            data = await asyncio.wait_for(r.read(1), timeout=5.0)
            if data:
                assert data[0] != 0x50, "Server accepted message with bad checksum"
        except (asyncio.TimeoutError, ConnectionError):
            pass  # disconnect is acceptable
        w.close()
    asyncio.run(_run())


def test_hello_must_be_first():
    """Non-Hello message before Hello must trigger error or disconnect."""
    async def _run():
        r, w = await asyncio.open_connection(HOST, PORT)
        # Send a SiteVisit (0x58) before Hello
        content = struct.pack("!II", 9999, 0)
        msg = build_msg(0x58, content)
        w.write(msg)
        await w.drain()

        try:
            data = await asyncio.wait_for(r.read(1), timeout=5.0)
            if data:
                assert data[0] == 0x51, f"Expected Error (0x51), got 0x{data[0]:02x}"
        except (asyncio.TimeoutError, ConnectionError):
            pass  # disconnect is acceptable
        w.close()
    asyncio.run(_run())
