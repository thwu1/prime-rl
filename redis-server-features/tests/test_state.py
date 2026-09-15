
import pytest
import socket
import struct
import time
import subprocess
import signal
import os


class RedisClient:
    """Client for the custom binary protocol Redis-like server."""

    TAG_NIL = 0
    TAG_ERR = 1
    TAG_STR = 2
    TAG_INT = 3
    TAG_DBL = 4
    TAG_ARR = 5

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

    def read_exact(self, n):
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def read_response(self):
        header = self.read_exact(4)
        length = struct.unpack("<I", header)[0]
        body = self.read_exact(length)
        val, pos = self.parse_value(body, 0)
        assert pos == len(body), f"trailing data: consumed {pos} of {len(body)} bytes"
        return val

    def parse_value(self, data, pos):
        tag = data[pos]
        pos += 1
        if tag == self.TAG_NIL:
            return (None, pos)
        elif tag == self.TAG_ERR:
            code = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            msg_len = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            msg = data[pos : pos + msg_len].decode("utf-8")
            pos += msg_len
            return (("ERR", code, msg), pos)
        elif tag == self.TAG_STR:
            slen = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            s = data[pos : pos + slen].decode("utf-8")
            pos += slen
            return (s, pos)
        elif tag == self.TAG_INT:
            val = struct.unpack_from("<q", data, pos)[0]
            pos += 8
            return (val, pos)
        elif tag == self.TAG_DBL:
            val = struct.unpack_from("<d", data, pos)[0]
            pos += 8
            return (val, pos)
        elif tag == self.TAG_ARR:
            n = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            items = []
            for _ in range(n):
                item, pos = self.parse_value(data, pos)
                items.append(item)
            return (items, pos)
        else:
            raise ValueError(f"Unknown tag: {tag}")

    def cmd(self, *args):
        self.send_command(*args)
        return self.read_response()


@pytest.fixture(scope="module")
def server():
    """Build and start the Redis-like server for the test module."""
    # Kill any existing server
    subprocess.run(["pkill", "-f", "/app/server"], capture_output=True)
    time.sleep(0.3)

    # Build
    result = subprocess.run(
        ["make", "-C", "/app", "clean"], capture_output=True
    )
    result = subprocess.run(["make", "-C", "/app"], capture_output=True)
    assert result.returncode == 0, f"Build failed:\n{result.stderr.decode()}\n{result.stdout.decode()}"

    # Verify binary exists
    assert os.path.isfile("/app/server"), "Build did not produce /app/server binary"

    # Start server
    proc = subprocess.Popen(["/app/server"], stderr=subprocess.PIPE)

    # Wait for server to be ready
    for _ in range(50):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2)
            s.connect(("127.0.0.1", 1234))
            s.close()
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("Server failed to start within 5 seconds")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture
def client(server):
    """Create a fresh client connection for each test."""
    c = RedisClient()
    yield c
    c.close()


# ============================================================
# Basic KV sanity tests
# ============================================================


class TestBasicKV:
    def test_set_get(self, client):
        assert client.cmd("set", "bkv_foo", "bar") is None
        assert client.cmd("get", "bkv_foo") == "bar"

    def test_del(self, client):
        client.cmd("set", "bkv_todel", "val")
        assert client.cmd("del", "bkv_todel") == 1
        assert client.cmd("get", "bkv_todel") is None

    def test_get_nonexistent(self, client):
        assert client.cmd("get", "bkv_nonexistent_xyz") is None


# ============================================================
# Sorted set sanity tests
# ============================================================


class TestSortedSet:
    def test_zadd_zscore(self, client):
        assert client.cmd("zadd", "ss_myset", "1.5", "alice") == 1
        assert client.cmd("zscore", "ss_myset", "alice") == 1.5

    def test_zadd_update(self, client):
        client.cmd("zadd", "ss_myset2", "1.0", "bob")
        assert client.cmd("zadd", "ss_myset2", "2.0", "bob") == 0
        assert client.cmd("zscore", "ss_myset2", "bob") == 2.0

    def test_zrem(self, client):
        client.cmd("zadd", "ss_remset", "1.0", "x")
        assert client.cmd("zrem", "ss_remset", "x") == 1
        assert client.cmd("zscore", "ss_remset", "x") is None


# ============================================================
# ZQUERY with offset tests (requires avl_offset)
# ============================================================


class TestZQueryOffset:
    @pytest.fixture(autouse=True)
    def setup_data(self, client):
        for name, score in [("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5)]:
            client.cmd("zadd", "zq_set", str(float(score)), name)

    def test_zquery_all(self, client):
        result = client.cmd("zquery", "zq_set", "1", "", "0", "100")
        assert result == ["a", 1.0, "b", 2.0, "c", 3.0, "d", 4.0, "e", 5.0]

    def test_zquery_offset_2(self, client):
        result = client.cmd("zquery", "zq_set", "1", "", "2", "100")
        assert result == ["c", 3.0, "d", 4.0, "e", 5.0]

    def test_zquery_offset_and_limit(self, client):
        result = client.cmd("zquery", "zq_set", "1", "", "1", "2")
        assert result == ["b", 2.0]

    def test_zquery_large_offset(self, client):
        result = client.cmd("zquery", "zq_set", "1", "", "10", "100")
        assert result == []

    def test_zquery_same_score_ordering(self, client):
        """Elements with the same score should be ordered by name."""
        client.cmd("zadd", "zq_same", "1.0", "charlie")
        client.cmd("zadd", "zq_same", "1.0", "alice")
        client.cmd("zadd", "zq_same", "1.0", "bob")
        result = client.cmd("zquery", "zq_same", "0", "", "0", "100")
        assert result == ["alice", 1.0, "bob", 1.0, "charlie", 1.0]


# ============================================================
# TTL tests (requires heap + PEXPIRE/PTTL)
# ============================================================


class TestTTL:
    def test_pexpire_pttl(self, client):
        client.cmd("set", "ttl_key1", "value")
        assert client.cmd("pexpire", "ttl_key1", "10000") == 1
        ttl = client.cmd("pttl", "ttl_key1")
        assert isinstance(ttl, int)
        assert 0 < ttl <= 10000

    def test_pttl_no_ttl(self, client):
        client.cmd("set", "ttl_nottl", "value")
        assert client.cmd("pttl", "ttl_nottl") == -1

    def test_pttl_nonexistent(self, client):
        assert client.cmd("pttl", "ttl_nonexist_abc") == -2

    def test_pexpire_nonexistent_key(self, client):
        assert client.cmd("pexpire", "ttl_nokey_xyz", "1000") == 0

    def test_key_expires(self, client):
        client.cmd("set", "ttl_expkey", "willexpire")
        client.cmd("pexpire", "ttl_expkey", "500")
        time.sleep(2.0)
        # Any command triggers the event loop's timer processing
        client.cmd("get", "ttl_dummy_trigger")
        time.sleep(0.2)
        assert client.cmd("get", "ttl_expkey") is None

    def test_ttl_update(self, client):
        """Setting TTL twice should update to the new value."""
        client.cmd("set", "ttl_upd", "val")
        client.cmd("pexpire", "ttl_upd", "100")
        client.cmd("pexpire", "ttl_upd", "60000")
        ttl = client.cmd("pttl", "ttl_upd")
        assert ttl > 50000, f"TTL should be close to 60s but got {ttl}"

    def test_ttl_on_zset(self, client):
        """TTL should work on sorted set keys too."""
        client.cmd("zadd", "ttl_zs", "1.0", "member")
        client.cmd("pexpire", "ttl_zs", "500")
        time.sleep(2.0)
        client.cmd("get", "ttl_zs_trigger")
        time.sleep(0.2)
        result = client.cmd("zscore", "ttl_zs", "member")
        assert result is None, "ZSet key should have expired"


# ============================================================
# ZRANGEBYSCORE tests
# ============================================================


class TestZRangeByScore:
    @pytest.fixture(autouse=True)
    def setup_data(self, client):
        for name, score in [("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5)]:
            client.cmd("zadd", "zrbs_set", str(float(score)), name)

    def test_basic_range(self, client):
        result = client.cmd("zrangebyscore", "zrbs_set", "2", "4", "0", "100")
        assert result == ["b", 2.0, "c", 3.0, "d", 4.0]

    def test_full_range(self, client):
        result = client.cmd("zrangebyscore", "zrbs_set", "1", "5", "0", "100")
        assert result == ["a", 1.0, "b", 2.0, "c", 3.0, "d", 4.0, "e", 5.0]

    def test_range_with_offset(self, client):
        result = client.cmd("zrangebyscore", "zrbs_set", "1", "5", "2", "100")
        assert result == ["c", 3.0, "d", 4.0, "e", 5.0]

    def test_range_with_limit(self, client):
        result = client.cmd("zrangebyscore", "zrbs_set", "1", "5", "0", "4")
        assert result == ["a", 1.0, "b", 2.0]

    def test_empty_range(self, client):
        result = client.cmd("zrangebyscore", "zrbs_set", "10", "20", "0", "100")
        assert result == []

    def test_inverted_range(self, client):
        """min > max should return empty."""
        result = client.cmd("zrangebyscore", "zrbs_set", "5", "1", "0", "100")
        assert result == []

    def test_nonexistent_zset(self, client):
        result = client.cmd(
            "zrangebyscore", "zrbs_nonexist", "0", "100", "0", "100"
        )
        assert result == []
