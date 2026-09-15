
import pytest
import struct
import socket
import time
import subprocess
import os
import signal


TAG_NIL = 0
TAG_ERR = 1
TAG_STR = 2
TAG_INT = 3
TAG_DBL = 4
TAG_ARR = 5


class RedisClient:
    """Client that speaks the server's length-prefixed binary protocol."""

    def __init__(self, host="127.0.0.1", port=1234):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)
        self.sock.connect((host, port))

    def close(self):
        self.sock.close()

    def send_command(self, *args):
        body = struct.pack("<I", len(args))
        for arg in args:
            s = str(arg).encode("utf-8")
            body += struct.pack("<I", len(s)) + s
        msg = struct.pack("<I", len(body)) + body
        self.sock.sendall(msg)

    def read_response(self):
        data = self._recv_exact(4)
        length = struct.unpack("<I", data)[0]
        body = self._recv_exact(length)
        result, _ = self._parse(body, 0)
        return result

    def _recv_exact(self, n):
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def _parse(self, data, off):
        tag = data[off]
        off += 1
        if tag == TAG_NIL:
            return (None, off)
        elif tag == TAG_ERR:
            code = struct.unpack_from("<I", data, off)[0]
            off += 4
            slen = struct.unpack_from("<I", data, off)[0]
            off += 4
            msg = data[off : off + slen].decode()
            off += slen
            return (("ERR", code, msg), off)
        elif tag == TAG_STR:
            slen = struct.unpack_from("<I", data, off)[0]
            off += 4
            s = data[off : off + slen].decode()
            off += slen
            return (s, off)
        elif tag == TAG_INT:
            val = struct.unpack_from("<q", data, off)[0]
            off += 8
            return (val, off)
        elif tag == TAG_DBL:
            val = struct.unpack_from("<d", data, off)[0]
            off += 8
            return (val, off)
        elif tag == TAG_ARR:
            n = struct.unpack_from("<I", data, off)[0]
            off += 4
            arr = []
            for _ in range(n):
                v, off = self._parse(data, off)
                arr.append(v)
            return (arr, off)
        raise ValueError(f"Unknown tag: {tag}")

    def execute(self, *args):
        self.send_command(*args)
        return self.read_response()


@pytest.fixture(scope="session")
def server():
    # Kill any lingering server process
    subprocess.run(["pkill", "-f", "/app/src/server"], capture_output=True)
    time.sleep(0.2)
    # Start server
    proc = subprocess.Popen(["/app/src/server"], stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    assert proc.poll() is None, "Server failed to start"
    yield proc
    proc.kill()
    proc.wait()


@pytest.fixture
def client(server):
    assert server.poll() is None, "Server process has died"
    c = RedisClient()
    yield c
    c.close()


# ── Basic GET/SET/DEL sanity ─────────────────────────────────────────────────


class TestBasicCommands:
    def test_set_get(self, client):
        assert client.execute("set", "basic_k1", "hello") is None
        assert client.execute("get", "basic_k1") == "hello"

    def test_del(self, client):
        client.execute("set", "basic_dk1", "v")
        assert client.execute("del", "basic_dk1") == 1
        assert client.execute("get", "basic_dk1") is None


# ── Sorted set basics ────────────────────────────────────────────────────────


class TestSortedSetBasic:
    def test_zscore_nonexistent_key(self, client):
        assert client.execute("zscore", "no_zset_x1", "n1") is None

    def test_zadd_new_member(self, client):
        result = client.execute("zadd", "zb1", "1.5", "alice")
        assert result == 1

    def test_zadd_and_zscore(self, client):
        client.execute("zadd", "zb2", "3.14", "pi_member")
        score = client.execute("zscore", "zb2", "pi_member")
        assert abs(score - 3.14) < 1e-9

    def test_zadd_update_returns_zero(self, client):
        client.execute("zadd", "zb3", "1.0", "m1")
        result = client.execute("zadd", "zb3", "2.0", "m1")
        assert result == 0

    def test_zadd_update_changes_score(self, client):
        client.execute("zadd", "zb4", "1.0", "m1")
        client.execute("zadd", "zb4", "5.5", "m1")
        score = client.execute("zscore", "zb4", "m1")
        assert abs(score - 5.5) < 1e-9

    def test_zrem_existing(self, client):
        client.execute("zadd", "zb5", "1.0", "to_remove")
        assert client.execute("zrem", "zb5", "to_remove") == 1
        assert client.execute("zscore", "zb5", "to_remove") is None

    def test_zrem_nonexistent(self, client):
        assert client.execute("zrem", "no_zset_y1", "nobody") == 0

    def test_multiple_members(self, client):
        client.execute("zadd", "zb6", "3.0", "c")
        client.execute("zadd", "zb6", "1.0", "a")
        client.execute("zadd", "zb6", "2.0", "b")
        assert client.execute("zscore", "zb6", "a") == 1.0
        assert client.execute("zscore", "zb6", "b") == 2.0
        assert client.execute("zscore", "zb6", "c") == 3.0


# ── ZQUERY range queries ─────────────────────────────────────────────────────


class TestZQuery:
    def test_zquery_empty_set(self, client):
        result = client.execute("zquery", "no_zset_zq1", "0", "", "0", "10")
        assert result == []

    def test_zquery_basic_order(self, client):
        client.execute("zadd", "zq1", "30.0", "charlie")
        client.execute("zadd", "zq1", "10.0", "alice")
        client.execute("zadd", "zq1", "20.0", "bob")
        result = client.execute("zquery", "zq1", "0", "", "0", "10")
        assert len(result) == 6
        assert result[0] == "alice"
        assert result[1] == 10.0
        assert result[2] == "bob"
        assert result[3] == 20.0
        assert result[4] == "charlie"
        assert result[5] == 30.0

    def test_zquery_seek_by_score(self, client):
        client.execute("zadd", "zq2", "1.0", "a")
        client.execute("zadd", "zq2", "2.0", "b")
        client.execute("zadd", "zq2", "3.0", "c")
        client.execute("zadd", "zq2", "4.0", "d")
        # Seek to score >= 2.5
        result = client.execute("zquery", "zq2", "2.5", "", "0", "10")
        assert len(result) == 4
        assert result[0] == "c"
        assert result[1] == 3.0
        assert result[2] == "d"
        assert result[3] == 4.0

    def test_zquery_with_offset(self, client):
        client.execute("zadd", "zq3", "1.0", "a")
        client.execute("zadd", "zq3", "2.0", "b")
        client.execute("zadd", "zq3", "3.0", "c")
        # Seek to score >= 1, offset 1 -> skip "a", start at "b"
        result = client.execute("zquery", "zq3", "1.0", "", "1", "10")
        assert len(result) == 4
        assert result[0] == "b"
        assert result[1] == 2.0
        assert result[2] == "c"
        assert result[3] == 3.0

    def test_zquery_with_limit(self, client):
        client.execute("zadd", "zq4", "1.0", "a")
        client.execute("zadd", "zq4", "2.0", "b")
        client.execute("zadd", "zq4", "3.0", "c")
        # limit=2 -> 1 pair (name + score)
        result = client.execute("zquery", "zq4", "0", "", "0", "2")
        assert len(result) == 2
        assert result[0] == "a"
        assert result[1] == 1.0

    def test_zquery_offset_beyond_end(self, client):
        client.execute("zadd", "zq5", "1.0", "a")
        client.execute("zadd", "zq5", "2.0", "b")
        # offset 5 -> beyond end
        result = client.execute("zquery", "zq5", "1.0", "", "5", "10")
        assert result == []

    def test_zquery_name_tiebreak(self, client):
        """When scores are equal, entries are ordered by name (memcmp)."""
        client.execute("zadd", "zq6", "1.0", "banana")
        client.execute("zadd", "zq6", "1.0", "apple")
        client.execute("zadd", "zq6", "1.0", "cherry")
        result = client.execute("zquery", "zq6", "0", "", "0", "10")
        assert len(result) == 6
        assert result[0] == "apple"
        assert result[2] == "banana"
        assert result[4] == "cherry"

    def test_zquery_after_score_update(self, client):
        """Score update should change ordering."""
        client.execute("zadd", "zq7", "1.0", "a")
        client.execute("zadd", "zq7", "2.0", "b")
        client.execute("zadd", "zq7", "3.0", "c")
        # Update "a" to have highest score
        client.execute("zadd", "zq7", "10.0", "a")
        result = client.execute("zquery", "zq7", "0", "", "0", "10")
        assert result[0] == "b"
        assert result[1] == 2.0
        assert result[2] == "c"
        assert result[3] == 3.0
        assert result[4] == "a"
        assert result[5] == 10.0

    def test_zquery_after_zrem(self, client):
        """ZREM should be reflected in subsequent queries."""
        client.execute("zadd", "zq8", "1.0", "a")
        client.execute("zadd", "zq8", "2.0", "b")
        client.execute("zadd", "zq8", "3.0", "c")
        client.execute("zrem", "zq8", "b")
        result = client.execute("zquery", "zq8", "0", "", "0", "10")
        assert len(result) == 4
        assert result[0] == "a"
        assert result[1] == 1.0
        assert result[2] == "c"
        assert result[3] == 3.0


# ── TTL operations ────────────────────────────────────────────────────────────


class TestTTL:
    def test_pexpire_pttl(self, client):
        client.execute("set", "ttl1", "value")
        result = client.execute("pexpire", "ttl1", "10000")
        assert result == 1
        ttl = client.execute("pttl", "ttl1")
        assert 5000 < ttl <= 10000

    def test_pttl_no_expiry(self, client):
        client.execute("set", "ttl2", "value")
        assert client.execute("pttl", "ttl2") == -1

    def test_pttl_nonexistent(self, client):
        assert client.execute("pttl", "no_key_ttl_x") == -2

    def test_key_expires(self, client):
        client.execute("set", "ttl3", "will_expire")
        client.execute("pexpire", "ttl3", "200")
        time.sleep(0.8)
        # Send a dummy command to trigger timer processing
        client.execute("get", "nonexistent_trigger_key")
        # Now the key should be expired
        result = client.execute("get", "ttl3")
        assert result is None


# ── Large-scale / stress ──────────────────────────────────────────────────────


class TestLargeScale:
    def test_large_sorted_set_ordering(self, client):
        """Insert 200 elements with pseudo-random scores and verify ordering."""
        n = 200
        for i in range(n):
            score = float((i * 37) % n)  # all unique scores
            name = f"member_{i:04d}"
            client.execute("zadd", "large1", str(score), name)

        result = client.execute("zquery", "large1", "0", "", "0", str(n * 2))
        assert len(result) == n * 2

        # Verify scores are non-decreasing
        scores = [result[i] for i in range(1, len(result), 2)]
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i - 1], (
                f"Score ordering violated at index {i}: "
                f"{scores[i - 1]} > {scores[i]}"
            )

    def test_large_insert_delete_query(self, client):
        """Insert 100, delete every other, verify remainder."""
        n = 100
        for i in range(n):
            client.execute("zadd", "large2", str(float(i)), f"m{i:04d}")

        # Delete every even-indexed element
        for i in range(0, n, 2):
            client.execute("zrem", "large2", f"m{i:04d}")

        result = client.execute("zquery", "large2", "0", "", "0", str(n * 2))
        remaining = n // 2
        assert len(result) == remaining * 2

        # Verify only odd-indexed members remain, in order
        for idx, i in enumerate(range(1, n, 2)):
            assert result[idx * 2] == f"m{i:04d}"
            assert result[idx * 2 + 1] == float(i)

    def test_sequential_insert_offset_queries(self, client):
        """Sequential insertion (worst case for BST) tests AVL balancing and offset."""
        n = 300
        for i in range(n):
            client.execute("zadd", "seq1", str(float(i)), f"s{i:05d}")

        # Query with various offsets to test avl_offset
        for offset in [0, 1, 50, 149, 299]:
            result = client.execute(
                "zquery", "seq1", "0", "", str(offset), "2"
            )
            if offset < n:
                assert len(result) == 2, (
                    f"offset={offset} returned {len(result)} items"
                )
                expected_name = f"s{offset:05d}"
                assert result[0] == expected_name, (
                    f"offset={offset}: got {result[0]}, expected {expected_name}"
                )
                assert result[1] == float(offset)

    def test_negative_scores(self, client):
        """Sorted set with negative scores."""
        client.execute("zadd", "neg1", "-5.0", "a")
        client.execute("zadd", "neg1", "0.0", "b")
        client.execute("zadd", "neg1", "5.0", "c")
        client.execute("zadd", "neg1", "-10.0", "d")

        result = client.execute("zquery", "neg1", "-100", "", "0", "10")
        assert len(result) == 8
        assert result[0] == "d"
        assert result[1] == -10.0
        assert result[2] == "a"
        assert result[3] == -5.0
        assert result[4] == "b"
        assert result[5] == 0.0
        assert result[6] == "c"
        assert result[7] == 5.0


# ── Sorted set + TTL interaction ──────────────────────────────────────────────


class TestZSetWithTTL:
    def test_zset_expires(self, client):
        """A sorted set key can have a TTL and expire."""
        client.execute("zadd", "zttl1", "1.0", "m1")
        client.execute("zadd", "zttl1", "2.0", "m2")
        client.execute("pexpire", "zttl1", "200")
        time.sleep(0.8)
        # Trigger timer processing
        client.execute("get", "nonexistent_trigger_key2")
        # Sorted set should be gone
        result = client.execute("zscore", "zttl1", "m1")
        assert result is None
        result2 = client.execute("zquery", "zttl1", "0", "", "0", "10")
        assert result2 == []
