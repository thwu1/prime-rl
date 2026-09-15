
import pytest
import subprocess
import socket
import struct
import time
import os
import signal


# ─── Binary protocol client ─────────────────────────────────────────────────

TAG_NIL = 0
TAG_ERR = 1
TAG_STR = 2
TAG_INT = 3
TAG_DBL = 4
TAG_ARR = 5


class Client:
    """Minimal client for the mini-Redis binary protocol."""

    def __init__(self, host="127.0.0.1", port=1234):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect((host, port))

    def close(self):
        self.sock.close()

    def cmd(self, *args):
        self._send(args)
        return self._recv()

    # ── wire helpers ──

    def _send(self, args):
        body = struct.pack("<I", len(args))
        for a in args:
            s = a.encode("utf-8") if isinstance(a, str) else a
            body += struct.pack("<I", len(s)) + s
        self.sock.sendall(struct.pack("<I", len(body)) + body)

    def _recv(self):
        hdr = self._recv_exact(4)
        length = struct.unpack("<I", hdr)[0]
        data = self._recv_exact(length)
        val, pos = self._parse(data, 0)
        assert pos == length, f"parse consumed {pos}, expected {length}"
        return val

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("connection closed")
            buf += chunk
        return buf

    def _parse(self, data, pos):
        tag = data[pos]
        pos += 1
        if tag == TAG_NIL:
            return None, pos
        if tag == TAG_ERR:
            code = struct.unpack_from("<i", data, pos)[0]; pos += 4
            slen = struct.unpack_from("<I", data, pos)[0]; pos += 4
            msg = data[pos:pos + slen].decode(); pos += slen
            return ("ERR", code, msg), pos
        if tag == TAG_STR:
            slen = struct.unpack_from("<I", data, pos)[0]; pos += 4
            s = data[pos:pos + slen].decode(); pos += slen
            return s, pos
        if tag == TAG_INT:
            val = struct.unpack_from("<q", data, pos)[0]; pos += 8
            return val, pos
        if tag == TAG_DBL:
            val = struct.unpack_from("<d", data, pos)[0]; pos += 8
            return val, pos
        if tag == TAG_ARR:
            count = struct.unpack_from("<I", data, pos)[0]; pos += 4
            items = []
            for _ in range(count):
                item, pos = self._parse(data, pos)
                items.append(item)
            return items, pos
        raise ValueError(f"unknown tag {tag}")


# ─── SCAN helper ─────────────────────────────────────────────────────────────

def scan_all(client, count=10, max_iters=200000):
    """Run SCAN until cursor returns to 0; return collected keys."""
    cursor = 0
    keys = []
    iters = 0
    while True:
        result = client.cmd("scan", str(cursor), "count", str(count))
        assert isinstance(result, list) and len(result) == 2, \
            f"SCAN must return [cursor, keys_array], got {result!r}"
        cursor = result[0]
        assert isinstance(cursor, int), f"cursor must be int, got {type(cursor)}"
        batch = result[1]
        assert isinstance(batch, list), f"keys must be array, got {type(batch)}"
        keys.extend(batch)
        iters += 1
        if cursor == 0:
            break
        assert iters < max_iters, "SCAN did not terminate"
    return keys


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def server_process():
    """Start a fresh server for each test; kill it afterwards."""
    proc = subprocess.Popen(
        ["/app/server"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # wait for the server to accept connections
    for _ in range(100):
        try:
            s = socket.create_connection(("127.0.0.1", 1234), timeout=0.1)
            s.close()
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.05)
    else:
        proc.kill()
        proc.wait()
        pytest.fail("server did not start within 5 s")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestScan:

    def test_empty_database(self):
        """SCAN on an empty database returns cursor 0 and no keys."""
        c = Client()
        result = c.cmd("scan", "0")
        assert isinstance(result, list) and len(result) == 2
        assert result[0] == 0, "cursor should be 0 for empty db"
        assert result[1] == [], "keys should be empty for empty db"
        c.close()

    def test_single_key(self):
        """SCAN finds the only key in the database."""
        c = Client()
        c.cmd("set", "only_key", "hello")
        keys = scan_all(c)
        assert sorted(keys) == ["only_key"]
        c.close()

    def test_small_dataset(self):
        """SCAN returns all 20 keys (fits within initial table, no rehashing)."""
        c = Client()
        expected = set()
        for i in range(20):
            k = f"sk:{i:04d}"
            c.cmd("set", k, "v")
            expected.add(k)
        keys = scan_all(c, count=5)
        assert set(keys) == expected, f"missing: {expected - set(keys)}"
        c.close()

    def test_large_dataset(self):
        """SCAN returns all 500 keys (multiple rehash cycles during insert)."""
        c = Client()
        expected = set()
        for i in range(500):
            k = f"lk:{i:04d}"
            c.cmd("set", k, "v")
            expected.add(k)
        keys = scan_all(c, count=50)
        found = set(keys)
        assert expected.issubset(found), \
            f"missing {len(expected - found)} keys"
        c.close()

    def test_scan_terminates(self):
        """SCAN always reaches cursor 0 regardless of dataset size."""
        c = Client()
        for i in range(100):
            c.cmd("set", f"t:{i:03d}", "v")
        keys = scan_all(c, count=3)
        assert len(keys) >= 100
        c.close()

    def test_count_hint(self):
        """COUNT influences batch size (but is only advisory)."""
        c = Client()
        for i in range(200):
            c.cmd("set", f"ch:{i:04d}", "v")

        # With count=1, the first batch should not return all 200 keys
        result = c.cmd("scan", "0", "count", "1")
        assert isinstance(result, list) and len(result) == 2
        batch = result[1]
        # Allow some slack — count is a hint — but 200 in one batch with
        # count=1 means the hint is completely ignored
        assert len(batch) < 100, \
            f"count=1 returned {len(batch)} keys; hint seems ignored"
        c.close()

    def test_mixed_key_types(self):
        """SCAN returns both string keys and sorted-set keys."""
        c = Client()
        c.cmd("set", "str_key1", "hello")
        c.cmd("set", "str_key2", "world")
        c.cmd("zadd", "zs_key1", "1.0", "member_a")
        c.cmd("zadd", "zs_key2", "2.5", "member_b")
        keys = scan_all(c)
        assert set(keys) == {"str_key1", "str_key2", "zs_key1", "zs_key2"}
        c.close()

    def test_during_rehashing(self):
        """Keys are not lost when rehashing occurs between SCAN calls.

        Strategy:
          1. Insert 2048 keys — the last insert triggers rehash (256 → 512
             slots) and migrates only 128 of the 2048 keys.
          2. Immediately start scanning with a small count so many SCAN calls
             are needed.
          3. Interleave SET commands between SCAN calls; each SET triggers
             hm_help_rehashing and migrates 128 more keys, gradually
             completing the rehash while the SCAN is in progress.
          4. Verify every original key appears at least once.
        """
        c = Client()
        N = 2048
        expected = set()
        for i in range(N):
            k = f"rh:{i:04d}"
            c.cmd("set", k, "v")
            expected.add(k)

        cursor = 0
        found = []
        step = 0
        while True:
            result = c.cmd("scan", str(cursor), "count", "10")
            assert isinstance(result, list) and len(result) == 2
            cursor = result[0]
            found.extend(result[1])

            # interleave SET to advance rehashing
            if step < 30:
                c.cmd("set", f"extra:{step:04d}", "v")
            step += 1

            if cursor == 0:
                break

        found_set = set(found)
        missing = expected - found_set
        assert not missing, \
            f"missing {len(missing)} of {N} keys during rehash scan"
        c.close()

    def test_invalid_arguments(self):
        """Bad arguments produce an error response."""
        c = Client()
        # 'scan' with no cursor → falls through to unknown command
        result = c.cmd("scan")
        assert isinstance(result, tuple) and result[0] == "ERR"

        # non-numeric cursor
        result = c.cmd("scan", "abc")
        assert isinstance(result, tuple) and result[0] == "ERR"
        c.close()
