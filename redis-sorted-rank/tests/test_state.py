#!/usr/bin/env python3

import pytest
import subprocess
import time
import socket
import struct
import os
import random


class RedisClient:
    """Client for the custom Redis-like binary protocol."""

    def __init__(self, host='127.0.0.1', port=1234):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self.sock.settimeout(5.0)

    def close(self):
        self.sock.close()

    def send_command(self, *args):
        body = struct.pack('<I', len(args))
        for arg in args:
            s = str(arg).encode() if not isinstance(arg, bytes) else arg
            body += struct.pack('<I', len(s)) + s
        msg = struct.pack('<I', len(body)) + body
        self.sock.sendall(msg)
        return self._read_response()

    def _read_exact(self, n):
        data = b''
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def _read_response(self):
        header = self._read_exact(4)
        length = struct.unpack('<I', header)[0]
        data = self._read_exact(length)
        result, _ = self._parse(data, 0)
        return result

    def _parse(self, data, offset):
        tag = data[offset]
        offset += 1
        if tag == 0:  # NIL
            return None, offset
        elif tag == 1:  # ERR
            code = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            slen = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            msg_str = data[offset:offset + slen].decode()
            offset += slen
            return ('ERR', code, msg_str), offset
        elif tag == 2:  # STR
            slen = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            s = data[offset:offset + slen].decode()
            offset += slen
            return s, offset
        elif tag == 3:  # INT
            val = struct.unpack_from('<q', data, offset)[0]
            offset += 8
            return val, offset
        elif tag == 4:  # DBL
            val = struct.unpack_from('<d', data, offset)[0]
            offset += 8
            return val, offset
        elif tag == 5:  # ARR
            n = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            items = []
            for _ in range(n):
                item, offset = self._parse(data, offset)
                items.append(item)
            return items, offset
        else:
            raise ValueError(f"Unknown tag: {tag}")


@pytest.fixture(scope="session")
def server_proc():
    """Start the Redis-like server for the test session."""
    os.system("pkill -f '/app/server' 2>/dev/null; sleep 0.5")

    proc = subprocess.Popen(
        ['/app/server'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(50):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(('127.0.0.1', 1234))
            s.close()
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("Server failed to start within 5 seconds")

    yield proc
    proc.kill()
    proc.wait()


@pytest.fixture
def client(server_proc):
    """Create a fresh client connection for each test."""
    c = RedisClient()
    yield c
    c.close()


def get_all_members(client, key):
    """Retrieve all (name, score) pairs from a sorted set via zquery."""
    result = client.send_command('zquery', key, '-1e308', '', '0', '100000')
    if not isinstance(result, list):
        return []
    return [(result[i], result[i + 1]) for i in range(0, len(result), 2)]


# ---------------------------------------------------------------------------
# ZUNIONSTORE tests
# ---------------------------------------------------------------------------

class TestZunionstore:

    def test_basic_union(self, client):
        """Union of two overlapping sets with default SUM aggregation."""
        client.send_command('zadd', 'zu1_s1', '1.0', 'a')
        client.send_command('zadd', 'zu1_s1', '2.0', 'b')
        client.send_command('zadd', 'zu1_s1', '3.0', 'c')

        client.send_command('zadd', 'zu1_s2', '10.0', 'b')
        client.send_command('zadd', 'zu1_s2', '20.0', 'c')
        client.send_command('zadd', 'zu1_s2', '30.0', 'd')

        result = client.send_command('zunionstore', 'zu1_out', '2', 'zu1_s1', 'zu1_s2')
        assert result == 4

        assert client.send_command('zscore', 'zu1_out', 'a') == 1.0
        assert client.send_command('zscore', 'zu1_out', 'b') == 12.0
        assert client.send_command('zscore', 'zu1_out', 'c') == 23.0
        assert client.send_command('zscore', 'zu1_out', 'd') == 30.0

    def test_no_overlap(self, client):
        """Union of two disjoint sets."""
        client.send_command('zadd', 'zu2_s1', '1.0', 'a')
        client.send_command('zadd', 'zu2_s1', '2.0', 'b')

        client.send_command('zadd', 'zu2_s2', '3.0', 'c')
        client.send_command('zadd', 'zu2_s2', '4.0', 'd')

        result = client.send_command('zunionstore', 'zu2_out', '2', 'zu2_s1', 'zu2_s2')
        assert result == 4

        assert client.send_command('zscore', 'zu2_out', 'a') == 1.0
        assert client.send_command('zscore', 'zu2_out', 'b') == 2.0
        assert client.send_command('zscore', 'zu2_out', 'c') == 3.0
        assert client.send_command('zscore', 'zu2_out', 'd') == 4.0

    def test_with_weights(self, client):
        """Weights multiply scores before aggregation."""
        client.send_command('zadd', 'zu3_s1', '1.0', 'a')
        client.send_command('zadd', 'zu3_s1', '2.0', 'b')

        client.send_command('zadd', 'zu3_s2', '3.0', 'b')
        client.send_command('zadd', 'zu3_s2', '4.0', 'c')

        result = client.send_command('zunionstore', 'zu3_out', '2',
                                     'zu3_s1', 'zu3_s2', 'weights', '2', '3')
        assert result == 3
        # a: 1*2 = 2.0, b: 2*2 + 3*3 = 13.0, c: 4*3 = 12.0
        assert client.send_command('zscore', 'zu3_out', 'a') == 2.0
        assert client.send_command('zscore', 'zu3_out', 'b') == 13.0
        assert client.send_command('zscore', 'zu3_out', 'c') == 12.0

    def test_aggregate_min(self, client):
        client.send_command('zadd', 'zu4_s1', '5.0', 'a')
        client.send_command('zadd', 'zu4_s1', '3.0', 'b')

        client.send_command('zadd', 'zu4_s2', '1.0', 'b')
        client.send_command('zadd', 'zu4_s2', '7.0', 'c')

        result = client.send_command('zunionstore', 'zu4_out', '2',
                                     'zu4_s1', 'zu4_s2', 'aggregate', 'min')
        assert result == 3
        assert client.send_command('zscore', 'zu4_out', 'a') == 5.0
        assert client.send_command('zscore', 'zu4_out', 'b') == 1.0  # min(3,1)
        assert client.send_command('zscore', 'zu4_out', 'c') == 7.0

    def test_aggregate_max(self, client):
        client.send_command('zadd', 'zu5_s1', '5.0', 'a')
        client.send_command('zadd', 'zu5_s1', '3.0', 'b')

        client.send_command('zadd', 'zu5_s2', '1.0', 'b')
        client.send_command('zadd', 'zu5_s2', '7.0', 'c')

        result = client.send_command('zunionstore', 'zu5_out', '2',
                                     'zu5_s1', 'zu5_s2', 'aggregate', 'max')
        assert result == 3
        assert client.send_command('zscore', 'zu5_out', 'b') == 3.0  # max(3,1)

    def test_weights_and_aggregate_min(self, client):
        """Weights applied before MIN aggregation."""
        client.send_command('zadd', 'zu6_s1', '5.0', 'x')
        client.send_command('zadd', 'zu6_s1', '3.0', 'y')

        client.send_command('zadd', 'zu6_s2', '7.0', 'y')
        client.send_command('zadd', 'zu6_s2', '1.0', 'z')

        result = client.send_command('zunionstore', 'zu6_out', '2',
                                     'zu6_s1', 'zu6_s2',
                                     'weights', '2', '1', 'aggregate', 'min')
        assert result == 3
        # x: 5*2=10 (only set1)
        # y: min(3*2, 7*1) = min(6,7) = 6
        # z: 1*1=1 (only set2)
        assert client.send_command('zscore', 'zu6_out', 'x') == 10.0
        assert client.send_command('zscore', 'zu6_out', 'y') == 6.0
        assert client.send_command('zscore', 'zu6_out', 'z') == 1.0

    def test_single_source(self, client):
        """Union of a single set is a copy of that set."""
        client.send_command('zadd', 'zu7_s1', '1.0', 'a')
        client.send_command('zadd', 'zu7_s1', '2.0', 'b')

        result = client.send_command('zunionstore', 'zu7_out', '1', 'zu7_s1')
        assert result == 2
        assert client.send_command('zscore', 'zu7_out', 'a') == 1.0
        assert client.send_command('zscore', 'zu7_out', 'b') == 2.0

    def test_nonexistent_source(self, client):
        """Non-existent source treated as empty set."""
        client.send_command('zadd', 'zu8_s1', '1.0', 'a')

        result = client.send_command('zunionstore', 'zu8_out', '2',
                                     'zu8_s1', 'zu8_nonexistent')
        assert result == 1
        assert client.send_command('zscore', 'zu8_out', 'a') == 1.0

    def test_all_nonexistent(self, client):
        """All sources non-existent -> empty result, no dest key created."""
        result = client.send_command('zunionstore', 'zu9_out', '2',
                                     'zu9_nope1', 'zu9_nope2')
        assert result == 0
        assert client.send_command('zscore', 'zu9_out', 'any') is None

    def test_overwrites_existing_dest(self, client):
        """Dest already contains a sorted set -> overwritten."""
        client.send_command('zadd', 'zu10_dest', '99.0', 'old_member')
        client.send_command('zadd', 'zu10_src', '1.0', 'new_member')

        result = client.send_command('zunionstore', 'zu10_dest', '1', 'zu10_src')
        assert result == 1
        assert client.send_command('zscore', 'zu10_dest', 'new_member') == 1.0
        assert client.send_command('zscore', 'zu10_dest', 'old_member') is None

    def test_overwrites_string_dest(self, client):
        """Dest holds a string value -> overwritten with sorted set."""
        client.send_command('set', 'zu11_dest', 'hello')
        client.send_command('zadd', 'zu11_src', '5.0', 'x')

        result = client.send_command('zunionstore', 'zu11_dest', '1', 'zu11_src')
        assert result == 1
        assert client.send_command('zscore', 'zu11_dest', 'x') == 5.0

    def test_dest_is_source(self, client):
        """Dest is also one of the source keys."""
        client.send_command('zadd', 'zu12_self', '1.0', 'a')
        client.send_command('zadd', 'zu12_self', '2.0', 'b')

        result = client.send_command('zunionstore', 'zu12_self', '1',
                                     'zu12_self', 'weights', '3')
        assert result == 2
        assert client.send_command('zscore', 'zu12_self', 'a') == 3.0
        assert client.send_command('zscore', 'zu12_self', 'b') == 6.0

    def test_wrong_type_source(self, client):
        """Source key holds a string -> error."""
        client.send_command('set', 'zu13_str', 'value')
        client.send_command('zadd', 'zu13_src', '1.0', 'a')

        result = client.send_command('zunionstore', 'zu13_out', '2',
                                     'zu13_src', 'zu13_str')
        assert isinstance(result, tuple) and result[0] == 'ERR'

    def test_three_way_union(self, client):
        """Union of three sets with overlapping members."""
        client.send_command('zadd', 'zu14_s1', '1.0', 'a')
        client.send_command('zadd', 'zu14_s1', '2.0', 'b')

        client.send_command('zadd', 'zu14_s2', '3.0', 'b')
        client.send_command('zadd', 'zu14_s2', '4.0', 'c')

        client.send_command('zadd', 'zu14_s3', '5.0', 'c')
        client.send_command('zadd', 'zu14_s3', '6.0', 'd')

        result = client.send_command('zunionstore', 'zu14_out', '3',
                                     'zu14_s1', 'zu14_s2', 'zu14_s3')
        assert result == 4
        # a: 1, b: 2+3=5, c: 4+5=9, d: 6
        assert client.send_command('zscore', 'zu14_out', 'a') == 1.0
        assert client.send_command('zscore', 'zu14_out', 'b') == 5.0
        assert client.send_command('zscore', 'zu14_out', 'c') == 9.0
        assert client.send_command('zscore', 'zu14_out', 'd') == 6.0

    def test_large_union(self, client):
        """Union of two 200-element sets with 50% overlap."""
        random.seed(42)
        expected = {}

        for i in range(200):
            score = random.uniform(0, 100)
            name = f'm{i:04d}'
            client.send_command('zadd', 'zu15_s1', str(score), name)
            expected[name] = score

        for i in range(100, 300):
            score = random.uniform(0, 100)
            name = f'm{i:04d}'
            client.send_command('zadd', 'zu15_s2', str(score), name)
            if name in expected:
                expected[name] += score  # SUM
            else:
                expected[name] = score

        result = client.send_command('zunionstore', 'zu15_out', '2',
                                     'zu15_s1', 'zu15_s2')
        assert result == 300

        # Spot-check 20 random members
        names = list(expected.keys())
        for name in random.sample(names, 20):
            actual = client.send_command('zscore', 'zu15_out', name)
            assert abs(actual - expected[name]) < 1e-6, \
                f"{name}: expected {expected[name]}, got {actual}"


# ---------------------------------------------------------------------------
# ZINTERSTORE tests
# ---------------------------------------------------------------------------

class TestZinterstore:

    def test_basic_intersection(self, client):
        """Intersection of two overlapping sets."""
        client.send_command('zadd', 'zi1_s1', '1.0', 'a')
        client.send_command('zadd', 'zi1_s1', '2.0', 'b')
        client.send_command('zadd', 'zi1_s1', '3.0', 'c')

        client.send_command('zadd', 'zi1_s2', '10.0', 'b')
        client.send_command('zadd', 'zi1_s2', '20.0', 'c')
        client.send_command('zadd', 'zi1_s2', '30.0', 'd')

        result = client.send_command('zinterstore', 'zi1_out', '2',
                                     'zi1_s1', 'zi1_s2')
        assert result == 2
        assert client.send_command('zscore', 'zi1_out', 'b') == 12.0
        assert client.send_command('zscore', 'zi1_out', 'c') == 23.0
        assert client.send_command('zscore', 'zi1_out', 'a') is None
        assert client.send_command('zscore', 'zi1_out', 'd') is None

    def test_no_common_members(self, client):
        """Intersection with no overlap -> empty result."""
        client.send_command('zadd', 'zi2_s1', '1.0', 'a')
        client.send_command('zadd', 'zi2_s2', '2.0', 'b')

        result = client.send_command('zinterstore', 'zi2_out', '2',
                                     'zi2_s1', 'zi2_s2')
        assert result == 0

    def test_with_weights(self, client):
        client.send_command('zadd', 'zi3_s1', '2.0', 'x')
        client.send_command('zadd', 'zi3_s1', '4.0', 'y')

        client.send_command('zadd', 'zi3_s2', '3.0', 'x')
        client.send_command('zadd', 'zi3_s2', '5.0', 'y')
        client.send_command('zadd', 'zi3_s2', '7.0', 'z')

        result = client.send_command('zinterstore', 'zi3_out', '2',
                                     'zi3_s1', 'zi3_s2', 'weights', '2', '3')
        assert result == 2
        # x: 2*2 + 3*3 = 13, y: 4*2 + 5*3 = 23
        assert client.send_command('zscore', 'zi3_out', 'x') == 13.0
        assert client.send_command('zscore', 'zi3_out', 'y') == 23.0

    def test_aggregate_min(self, client):
        client.send_command('zadd', 'zi4_s1', '5.0', 'a')
        client.send_command('zadd', 'zi4_s1', '10.0', 'b')

        client.send_command('zadd', 'zi4_s2', '3.0', 'a')
        client.send_command('zadd', 'zi4_s2', '20.0', 'b')

        result = client.send_command('zinterstore', 'zi4_out', '2',
                                     'zi4_s1', 'zi4_s2', 'aggregate', 'min')
        assert result == 2
        assert client.send_command('zscore', 'zi4_out', 'a') == 3.0
        assert client.send_command('zscore', 'zi4_out', 'b') == 10.0

    def test_aggregate_max(self, client):
        client.send_command('zadd', 'zi5_s1', '5.0', 'a')
        client.send_command('zadd', 'zi5_s1', '10.0', 'b')

        client.send_command('zadd', 'zi5_s2', '3.0', 'a')
        client.send_command('zadd', 'zi5_s2', '20.0', 'b')

        result = client.send_command('zinterstore', 'zi5_out', '2',
                                     'zi5_s1', 'zi5_s2', 'aggregate', 'max')
        assert result == 2
        assert client.send_command('zscore', 'zi5_out', 'a') == 5.0
        assert client.send_command('zscore', 'zi5_out', 'b') == 20.0

    def test_single_source(self, client):
        """Intersection of one set = copy of that set."""
        client.send_command('zadd', 'zi6_s1', '1.0', 'a')
        client.send_command('zadd', 'zi6_s1', '2.0', 'b')

        result = client.send_command('zinterstore', 'zi6_out', '1', 'zi6_s1')
        assert result == 2
        assert client.send_command('zscore', 'zi6_out', 'a') == 1.0
        assert client.send_command('zscore', 'zi6_out', 'b') == 2.0

    def test_nonexistent_source(self, client):
        """Non-existent source -> empty intersection."""
        client.send_command('zadd', 'zi7_s1', '1.0', 'a')

        result = client.send_command('zinterstore', 'zi7_out', '2',
                                     'zi7_s1', 'zi7_nonexistent')
        assert result == 0

    def test_three_way_intersection(self, client):
        """Intersection of three sets."""
        for name, score in [('a', 1), ('b', 2), ('c', 3)]:
            client.send_command('zadd', 'zi8_s1', str(float(score)), name)
        for name, score in [('b', 10), ('c', 20), ('d', 30)]:
            client.send_command('zadd', 'zi8_s2', str(float(score)), name)
        for name, score in [('a', 100), ('c', 200), ('d', 300)]:
            client.send_command('zadd', 'zi8_s3', str(float(score)), name)

        # Only 'c' is in all three sets
        result = client.send_command('zinterstore', 'zi8_out', '3',
                                     'zi8_s1', 'zi8_s2', 'zi8_s3')
        assert result == 1
        assert client.send_command('zscore', 'zi8_out', 'c') == 223.0  # 3+20+200

    def test_wrong_type_source(self, client):
        client.send_command('set', 'zi9_str', 'value')
        result = client.send_command('zinterstore', 'zi9_out', '1', 'zi9_str')
        assert isinstance(result, tuple) and result[0] == 'ERR'

    def test_dest_is_source(self, client):
        """Dest is also a source key."""
        client.send_command('zadd', 'zi10_self', '1.0', 'a')
        client.send_command('zadd', 'zi10_self', '2.0', 'b')
        client.send_command('zadd', 'zi10_other', '5.0', 'b')
        client.send_command('zadd', 'zi10_other', '6.0', 'c')

        result = client.send_command('zinterstore', 'zi10_self', '2',
                                     'zi10_self', 'zi10_other')
        assert result == 1  # only 'b' in common
        assert client.send_command('zscore', 'zi10_self', 'b') == 7.0

    def test_large_intersection(self, client):
        """Intersection of two 200-element sets with partial overlap."""
        random.seed(123)
        s1_members = {}
        s2_members = {}

        for i in range(200):
            score = random.uniform(0, 100)
            name = f'n{i:04d}'
            client.send_command('zadd', 'zi11_s1', str(score), name)
            s1_members[name] = score

        for i in range(100, 300):
            score = random.uniform(0, 100)
            name = f'n{i:04d}'
            client.send_command('zadd', 'zi11_s2', str(score), name)
            s2_members[name] = score

        result = client.send_command('zinterstore', 'zi11_out', '2',
                                     'zi11_s1', 'zi11_s2')
        # Overlap is n0100..n0199 = 100 members
        assert result == 100

        # Spot-check common members
        common = set(s1_members.keys()) & set(s2_members.keys())
        for name in random.sample(sorted(common), 10):
            actual = client.send_command('zscore', 'zi11_out', name)
            expected = s1_members[name] + s2_members[name]
            assert abs(actual - expected) < 1e-6


# ---------------------------------------------------------------------------
# ZREMRANGEBYSCORE tests
# ---------------------------------------------------------------------------

class TestZremrangebyscore:

    def test_basic_removal(self, client):
        for i in range(1, 6):
            client.send_command('zadd', 'zrbs1', str(float(i)), f'item{i}')

        result = client.send_command('zremrangebyscore', 'zrbs1', '2.0', '4.0')
        assert result == 3  # items 2, 3, 4

    def test_remaining_correct(self, client):
        """Verify remaining elements after range removal."""
        for i in range(1, 8):
            client.send_command('zadd', 'zrbs2', str(float(i)), f'e{i}')

        client.send_command('zremrangebyscore', 'zrbs2', '3.0', '5.0')

        assert client.send_command('zscore', 'zrbs2', 'e1') == 1.0
        assert client.send_command('zscore', 'zrbs2', 'e2') == 2.0
        assert client.send_command('zscore', 'zrbs2', 'e3') is None
        assert client.send_command('zscore', 'zrbs2', 'e4') is None
        assert client.send_command('zscore', 'zrbs2', 'e5') is None
        assert client.send_command('zscore', 'zrbs2', 'e6') == 6.0
        assert client.send_command('zscore', 'zrbs2', 'e7') == 7.0

    def test_exact_boundaries(self, client):
        """Min and max scores are inclusive."""
        for i in range(1, 6):
            client.send_command('zadd', 'zrbs3', str(float(i)), f'i{i}')

        result = client.send_command('zremrangebyscore', 'zrbs3', '2.0', '2.0')
        assert result == 1  # only i2

        result = client.send_command('zremrangebyscore', 'zrbs3', '1.0', '5.0')
        assert result == 4  # i1, i3, i4, i5 (i2 was already deleted)

    def test_empty_range(self, client):
        """No elements in the score range."""
        client.send_command('zadd', 'zrbs4', '1.0', 'a')
        client.send_command('zadd', 'zrbs4', '5.0', 'b')

        result = client.send_command('zremrangebyscore', 'zrbs4', '2.0', '4.0')
        assert result == 0

    def test_remove_all(self, client):
        """Range covers all elements."""
        for i in range(5):
            client.send_command('zadd', 'zrbs5', str(float(i)), f'x{i}')

        result = client.send_command('zremrangebyscore', 'zrbs5', '-1.0', '100.0')
        assert result == 5

    def test_nonexistent_key(self, client):
        result = client.send_command('zremrangebyscore', 'zrbs_nokey', '0', '100')
        assert result == 0

    def test_wrong_type(self, client):
        client.send_command('set', 'zrbs_str', 'value')
        result = client.send_command('zremrangebyscore', 'zrbs_str', '0', '10')
        assert isinstance(result, tuple) and result[0] == 'ERR'

    def test_inverted_range(self, client):
        """min > max -> 0 removals."""
        client.send_command('zadd', 'zrbs6', '5.0', 'a')
        result = client.send_command('zremrangebyscore', 'zrbs6', '10.0', '1.0')
        assert result == 0
        assert client.send_command('zscore', 'zrbs6', 'a') == 5.0

    def test_fractional_scores(self, client):
        client.send_command('zadd', 'zrbs7', '1.5', 'a')
        client.send_command('zadd', 'zrbs7', '2.5', 'b')
        client.send_command('zadd', 'zrbs7', '3.5', 'c')

        result = client.send_command('zremrangebyscore', 'zrbs7', '2.0', '3.0')
        assert result == 1  # only b (2.5)
        assert client.send_command('zscore', 'zrbs7', 'a') == 1.5
        assert client.send_command('zscore', 'zrbs7', 'b') is None
        assert client.send_command('zscore', 'zrbs7', 'c') == 3.5

    def test_large_set_removal(self, client):
        """Remove a range from a 500-element set."""
        for i in range(500):
            client.send_command('zadd', 'zrbs8', str(float(i)), f'n{i:04d}')

        result = client.send_command('zremrangebyscore', 'zrbs8', '100.0', '299.0')
        assert result == 200  # elements 100..299

        # Verify boundary elements survive
        assert client.send_command('zscore', 'zrbs8', 'n0099') == 99.0
        assert client.send_command('zscore', 'zrbs8', 'n0100') is None
        assert client.send_command('zscore', 'zrbs8', 'n0299') is None
        assert client.send_command('zscore', 'zrbs8', 'n0300') == 300.0

    def test_dual_index_consistency(self, client):
        """After removal, both indices remain consistent for subsequent operations."""
        for i in range(10):
            client.send_command('zadd', 'zrbs9', str(float(i)), f'k{i}')

        client.send_command('zremrangebyscore', 'zrbs9', '3.0', '6.0')
        # Removed k3,k4,k5,k6. Remaining: k0..k2, k7..k9

        # Verify hash index via zscore
        for i in [0, 1, 2, 7, 8, 9]:
            assert client.send_command('zscore', 'zrbs9', f'k{i}') == float(i)

        # Verify tree index via zquery (ordered traversal)
        members = get_all_members(client, 'zrbs9')
        names = [m[0] for m in members]
        assert names == ['k0', 'k1', 'k2', 'k7', 'k8', 'k9']

        # Verify new insertions work correctly in both indices
        client.send_command('zadd', 'zrbs9', '4.5', 'knew')
        assert client.send_command('zscore', 'zrbs9', 'knew') == 4.5
        members = get_all_members(client, 'zrbs9')
        names = [m[0] for m in members]
        assert 'knew' in names


# ---------------------------------------------------------------------------
# ZRANGEBYSCORE tests
# ---------------------------------------------------------------------------

class TestZrangebyscore:

    def test_basic_range(self, client):
        for i in range(1, 6):
            client.send_command('zadd', 'zrng1', str(float(i)), f'item{i}')

        result = client.send_command('zrangebyscore', 'zrng1', '2.0', '4.0')
        assert result == ['item2', 2.0, 'item3', 3.0, 'item4', 4.0]

    def test_full_range(self, client):
        client.send_command('zadd', 'zrng2', '1.0', 'a')
        client.send_command('zadd', 'zrng2', '2.0', 'b')
        client.send_command('zadd', 'zrng2', '3.0', 'c')

        result = client.send_command('zrangebyscore', 'zrng2', '0.0', '100.0')
        assert result == ['a', 1.0, 'b', 2.0, 'c', 3.0]

    def test_with_limit(self, client):
        for i in range(1, 11):
            client.send_command('zadd', 'zrng3', str(float(i)), f'e{i:02d}')

        # scores 3..8, skip 1, take 3
        result = client.send_command('zrangebyscore', 'zrng3', '3.0', '8.0',
                                     'limit', '1', '3')
        # Matching: e03(3), e04(4), e05(5), e06(6), e07(7), e08(8)
        # Skip 1: e04, e05, e06, e07, e08
        # Take 3: e04, e05, e06
        assert result == ['e04', 4.0, 'e05', 5.0, 'e06', 6.0]

    def test_limit_take_all(self, client):
        """LIMIT with offset 0 and large count returns everything."""
        client.send_command('zadd', 'zrng4', '1.0', 'a')
        client.send_command('zadd', 'zrng4', '2.0', 'b')

        result = client.send_command('zrangebyscore', 'zrng4', '0.0', '10.0',
                                     'limit', '0', '1000')
        assert result == ['a', 1.0, 'b', 2.0]

    def test_limit_negative_count(self, client):
        """Negative count means no limit on results."""
        for i in range(1, 6):
            client.send_command('zadd', 'zrng5', str(float(i)), f'x{i}')

        result = client.send_command('zrangebyscore', 'zrng5', '1.0', '5.0',
                                     'limit', '2', '-1')
        # Skip 2 (x1, x2), return all remaining
        assert result == ['x3', 3.0, 'x4', 4.0, 'x5', 5.0]

    def test_limit_offset_beyond(self, client):
        """Offset exceeds matching elements -> empty array."""
        client.send_command('zadd', 'zrng6', '1.0', 'a')
        client.send_command('zadd', 'zrng6', '2.0', 'b')

        result = client.send_command('zrangebyscore', 'zrng6', '1.0', '2.0',
                                     'limit', '10', '5')
        assert result == []

    def test_empty_range(self, client):
        client.send_command('zadd', 'zrng7', '1.0', 'a')
        client.send_command('zadd', 'zrng7', '5.0', 'b')

        result = client.send_command('zrangebyscore', 'zrng7', '2.0', '4.0')
        assert result == []

    def test_nonexistent_key(self, client):
        result = client.send_command('zrangebyscore', 'zrng_nokey', '0', '100')
        assert result == []

    def test_wrong_type(self, client):
        client.send_command('set', 'zrng_str', 'value')
        result = client.send_command('zrangebyscore', 'zrng_str', '0', '10')
        assert isinstance(result, tuple) and result[0] == 'ERR'

    def test_fractional_boundaries(self, client):
        client.send_command('zadd', 'zrng8', '1.5', 'a')
        client.send_command('zadd', 'zrng8', '2.5', 'b')
        client.send_command('zadd', 'zrng8', '3.5', 'c')
        client.send_command('zadd', 'zrng8', '4.5', 'd')

        result = client.send_command('zrangebyscore', 'zrng8', '2.0', '4.0')
        assert result == ['b', 2.5, 'c', 3.5]

    def test_same_score_ordering(self, client):
        """Members with the same score ordered lexicographically."""
        client.send_command('zadd', 'zrng9', '5.0', 'charlie')
        client.send_command('zadd', 'zrng9', '5.0', 'alice')
        client.send_command('zadd', 'zrng9', '5.0', 'bob')

        result = client.send_command('zrangebyscore', 'zrng9', '5.0', '5.0')
        assert result == ['alice', 5.0, 'bob', 5.0, 'charlie', 5.0]

    def test_large_set_with_limit(self, client):
        """Range query on a 500-element set with LIMIT."""
        for i in range(500):
            client.send_command('zadd', 'zrng10', str(float(i)), f'n{i:04d}')

        result = client.send_command('zrangebyscore', 'zrng10', '100.0', '400.0',
                                     'limit', '50', '5')
        # Matching: n0100..n0400 (301 elements)
        # Skip 50: start at n0150
        # Take 5: n0150, n0151, n0152, n0153, n0154
        assert len(result) == 10  # 5 name-score pairs
        assert result[0] == 'n0150'
        assert result[1] == 150.0
        assert result[8] == 'n0154'
        assert result[9] == 154.0


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestIntegration:

    def test_union_queryable(self, client):
        """Union result is a proper sorted set queryable with existing commands."""
        client.send_command('zadd', 'int1_s1', '1.0', 'a')
        client.send_command('zadd', 'int1_s1', '3.0', 'b')
        client.send_command('zadd', 'int1_s2', '2.0', 'c')

        client.send_command('zunionstore', 'int1_out', '2', 'int1_s1', 'int1_s2')

        # Use existing zquery to verify
        members = get_all_members(client, 'int1_out')
        assert members == [('a', 1.0), ('c', 2.0), ('b', 3.0)]

        # zadd to the result set should work
        client.send_command('zadd', 'int1_out', '0.5', 'z')
        members = get_all_members(client, 'int1_out')
        assert members[0] == ('z', 0.5)

    def test_intersect_subset_of_union(self, client):
        """Intersection members are a subset of union members."""
        client.send_command('zadd', 'int2_s1', '1.0', 'a')
        client.send_command('zadd', 'int2_s1', '2.0', 'b')
        client.send_command('zadd', 'int2_s1', '3.0', 'c')

        client.send_command('zadd', 'int2_s2', '10.0', 'b')
        client.send_command('zadd', 'int2_s2', '20.0', 'd')

        client.send_command('zunionstore', 'int2_union', '2', 'int2_s1', 'int2_s2')
        client.send_command('zinterstore', 'int2_inter', '2', 'int2_s1', 'int2_s2')

        union_members = get_all_members(client, 'int2_union')
        inter_members = get_all_members(client, 'int2_inter')

        union_names = {m[0] for m in union_members}
        inter_names = {m[0] for m in inter_members}
        assert inter_names.issubset(union_names)
        assert inter_names == {'b'}

    def test_remove_range_then_count(self, client):
        """After range removal, remaining elements are countable."""
        for i in range(20):
            client.send_command('zadd', 'int3', str(float(i)), f'm{i:02d}')

        # Remove scores 5..14
        removed = client.send_command('zremrangebyscore', 'int3', '5.0', '14.0')
        assert removed == 10

        # Remaining should be 10 elements
        remaining = get_all_members(client, 'int3')
        assert len(remaining) == 10

        # Check range query of remaining
        result = client.send_command('zrangebyscore', 'int3', '0.0', '100.0')
        assert len(result) == 20  # 10 name-score pairs

    def test_rangebyscore_consistent_with_zquery(self, client):
        """zrangebyscore results match manual iteration with zquery."""
        random.seed(99)
        for i in range(50):
            score = random.uniform(0, 100)
            client.send_command('zadd', 'int4', str(score), f'e{i:02d}')

        # Get all members via zquery
        all_members = get_all_members(client, 'int4')

        # Get range [25, 75] via zrangebyscore
        range_result = client.send_command('zrangebyscore', 'int4', '25.0', '75.0')
        range_pairs = [(range_result[i], range_result[i + 1])
                       for i in range(0, len(range_result), 2)]

        # Manually filter
        expected = [(n, s) for n, s in all_members if 25.0 <= s <= 75.0]
        assert range_pairs == expected

    def test_stress_combined(self, client):
        """Combined operations: union, modify, remove range, verify."""
        random.seed(7)

        # Create two source sets
        s1 = {}
        for i in range(100):
            score = random.uniform(0, 50)
            name = f'p{i:04d}'
            client.send_command('zadd', 'int5_s1', str(score), name)
            s1[name] = score

        s2 = {}
        for i in range(50, 150):
            score = random.uniform(25, 75)
            name = f'p{i:04d}'
            client.send_command('zadd', 'int5_s2', str(score), name)
            s2[name] = score

        # Union with weights
        client.send_command('zunionstore', 'int5_result', '2',
                            'int5_s1', 'int5_s2', 'weights', '1', '2')

        # Compute expected union
        expected = {}
        for name, score in s1.items():
            expected[name] = score * 1
        for name, score in s2.items():
            if name in expected:
                expected[name] += score * 2  # SUM
            else:
                expected[name] = score * 2

        # Verify cardinality
        result_members = get_all_members(client, 'int5_result')
        assert len(result_members) == len(expected)

        # Remove scores in [30, 60]
        removed = client.send_command('zremrangebyscore', 'int5_result', '30.0', '60.0')
        assert removed >= 0

        # Verify remaining members are outside [30, 60]
        remaining = get_all_members(client, 'int5_result')
        for name, score in remaining:
            assert score < 30.0 or score > 60.0, \
                f"{name} with score {score} should have been removed"

        # Verify zrangebyscore on remaining
        low_range = client.send_command('zrangebyscore', 'int5_result', '0.0', '29.99')
        high_range = client.send_command('zrangebyscore', 'int5_result', '60.01', '1000.0')
        total_via_range = len(low_range) // 2 + len(high_range) // 2
        assert total_via_range == len(remaining)
