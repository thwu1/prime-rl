"""Kafka wire protocol broker verification tests.


Tests start the broker at /app/run.sh, connect via TCP on port 9092,
send binary Kafka protocol requests, and validate binary responses.
Integration tests verify kcat interoperability.
"""

import os
import socket
import struct
import subprocess
import time

import pytest

# ─── Known fixture constants ────────────────────────────────────────────
ALPHA_UUID_HEX = "00112233445566778899aabbccddeeff"
BETA_UUID_HEX = "a0b1c2d3e4f5061728394a5b6c7d8e9f"
ALPHA_UUID_BYTES = bytes.fromhex(ALPHA_UUID_HEX)
BETA_UUID_BYTES = bytes.fromhex(BETA_UUID_HEX)
UNKNOWN_UUID_BYTES = bytes.fromhex("ff" * 16)

KRAFT_LOG_DIR = "/data/kraft-combined-logs"


# ─── Binary helpers ─────────────────────────────────────────────────────

class BinaryWriter:
    def __init__(self):
        self.buf = bytearray()

    def write_int8(self, v):
        self.buf += struct.pack('>b', v)

    def write_int16(self, v):
        self.buf += struct.pack('>h', v)

    def write_int32(self, v):
        self.buf += struct.pack('>i', v)

    def write_int64(self, v):
        self.buf += struct.pack('>q', v)

    def write_uvarint(self, v):
        while v > 0x7f:
            self.buf.append((v & 0x7f) | 0x80)
            v >>= 7
        self.buf.append(v & 0x7f)

    def write_raw(self, data):
        self.buf += data

    def write_nullable_string(self, s):
        if s is None:
            self.write_int16(-1)
        else:
            b = s.encode('utf-8')
            self.write_int16(len(b))
            self.buf += b

    def write_compact_string(self, s):
        b = s.encode('utf-8')
        self.write_uvarint(len(b) + 1)
        self.buf += b

    def bytes(self):
        return bytes(self.buf)


class BinaryReader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, n):
        r = self.data[self.pos:self.pos + n]
        self.pos += n
        return r

    def read_int8(self):
        return struct.unpack('>b', self.read(1))[0]

    def read_uint8(self):
        return struct.unpack('>B', self.read(1))[0]

    def read_int16(self):
        return struct.unpack('>h', self.read(2))[0]

    def read_int32(self):
        return struct.unpack('>i', self.read(4))[0]

    def read_uint32(self):
        return struct.unpack('>I', self.read(4))[0]

    def read_int64(self):
        return struct.unpack('>q', self.read(8))[0]

    def read_uvarint(self):
        result = 0
        shift = 0
        while True:
            b = self.data[self.pos]
            self.pos += 1
            result |= (b & 0x7f) << shift
            if not (b & 0x80):
                break
            shift += 7
        return result

    def read_varint(self):
        uv = self.read_uvarint()
        return (uv >> 1) ^ -(uv & 1)

    def read_uuid(self):
        return self.read(16)

    def read_compact_string(self):
        length = self.read_uvarint() - 1
        if length < 0:
            return None
        return self.read(length).decode('utf-8')

    def read_compact_nullable_bytes(self):
        length = self.read_uvarint() - 1
        if length < 0:
            return None
        return self.read(length)

    def read_compact_array_int32(self):
        count = self.read_uvarint() - 1
        return [self.read_int32() for _ in range(count)]

    def remaining(self):
        return len(self.data) - self.pos


# ─── Request builders ───────────────────────────────────────────────────

def _wrap(payload_bytes):
    """Prepend message_size header."""
    return struct.pack('>i', len(payload_bytes)) + payload_bytes


def build_api_versions_request(version, correlation_id):
    w = BinaryWriter()
    w.write_int16(18)
    w.write_int16(version)
    w.write_int32(correlation_id)
    w.write_nullable_string(None)
    w.write_uvarint(0)  # tag buffer
    if version >= 3:
        w.write_compact_string("")  # client software name
        w.write_compact_string("")  # client software version
        w.write_uvarint(0)
    return _wrap(w.bytes())


def build_dtp_request(correlation_id, topic_names):
    w = BinaryWriter()
    w.write_int16(75)
    w.write_int16(0)
    w.write_int32(correlation_id)
    w.write_nullable_string(None)
    w.write_uvarint(0)
    # body
    w.write_uvarint(len(topic_names) + 1)
    for name in topic_names:
        w.write_compact_string(name)
        w.write_uvarint(0)
    w.write_int32(100)   # response partition limit
    w.write_int8(-1)     # cursor: null (0xff)
    w.write_uvarint(0)
    return _wrap(w.bytes())


def build_fetch_request(correlation_id, topics):
    """topics: list of (uuid_bytes, partition_id) tuples, or empty list."""
    w = BinaryWriter()
    w.write_int16(1)
    w.write_int16(16)
    w.write_int32(correlation_id)
    w.write_nullable_string(None)
    w.write_uvarint(0)
    # body
    w.write_int32(500)        # maxWaitMs
    w.write_int32(1)          # minBytes
    w.write_int32(52428800)   # maxBytes
    w.write_int8(0)           # isolationLevel
    w.write_int32(0)          # sessionId
    w.write_int32(-1)         # sessionEpoch
    # topics
    w.write_uvarint(len(topics) + 1)
    for uuid_bytes, partition_id in topics:
        w.write_raw(uuid_bytes)
        w.write_uvarint(2)   # partitions: 1 element
        w.write_int32(partition_id)
        w.write_int32(0)     # currentLeaderEpoch
        w.write_int64(0)     # fetchOffset
        w.write_int32(-1)    # lastFetchedEpoch
        w.write_int64(-1)    # logStartOffset
        w.write_int32(1048576)  # partitionMaxBytes
        w.write_uvarint(0)  # tag buffer
        w.write_uvarint(0)  # tag buffer (topic)
    # forgottenTopics: empty
    w.write_uvarint(1)
    # rackId: empty
    w.write_compact_string("")
    w.write_uvarint(0)
    return _wrap(w.bytes())


def build_metadata_request_v1(correlation_id, topics=None):
    """Metadata v1 request with header v1 (no tag buffer).
    topics: None = list all; list of strings = specific topics.
    """
    w = BinaryWriter()
    # Header v1 (no tag buffer after client_id)
    w.write_int16(3)     # api_key = Metadata
    w.write_int16(1)     # api_version = 1
    w.write_int32(correlation_id)
    w.write_nullable_string(None)  # client_id
    # Body (old-style encoding)
    if topics is None:
        w.write_int32(-1)  # null = all topics
    else:
        w.write_int32(len(topics))
        for t in topics:
            w.write_nullable_string(t)  # old-style STRING
    return _wrap(w.bytes())


# ─── Response parsers ────────────────────────────────────────────────────

def parse_api_versions_response(data):
    r = BinaryReader(data)
    msg_size = r.read_int32()
    assert msg_size == len(data) - 4, f"msg_size {msg_size} != {len(data) - 4}"
    cid = r.read_int32()
    # response header v0: no tag buffer
    error_code = r.read_int16()
    count = r.read_uvarint() - 1
    api_keys = {}
    for _ in range(count):
        key = r.read_int16()
        min_v = r.read_int16()
        max_v = r.read_int16()
        r.read_uvarint()  # tag buffer
        api_keys[key] = (min_v, max_v)
    throttle = r.read_int32()
    r.read_uvarint()  # tag buffer
    return {"correlation_id": cid, "error_code": error_code,
            "api_keys": api_keys, "throttle_time_ms": throttle}


def parse_dtp_response(data):
    r = BinaryReader(data)
    msg_size = r.read_int32()
    assert msg_size == len(data) - 4
    cid = r.read_int32()
    r.read_uvarint()  # header v1 tag buffer
    throttle = r.read_int32()
    topic_count = r.read_uvarint() - 1
    topics = []
    for _ in range(topic_count):
        error_code = r.read_int16()
        name = r.read_compact_string()
        topic_id = r.read_uuid()
        is_internal = r.read_int8()
        part_count = r.read_uvarint() - 1
        partitions = []
        for _ in range(part_count):
            pe = r.read_int16()
            pi = r.read_int32()
            lid = r.read_int32()
            le = r.read_int32()
            rn = r.read_compact_array_int32()
            isr = r.read_compact_array_int32()
            elr = r.read_compact_array_int32()
            lkelr = r.read_compact_array_int32()
            offl = r.read_compact_array_int32()
            r.read_uvarint()
            partitions.append({"error_code": pe, "partition_index": pi,
                               "leader_id": lid, "leader_epoch": le,
                               "replicas": rn, "isr": isr})
        auth_ops = r.read_int32()
        r.read_uvarint()
        topics.append({"error_code": error_code, "name": name,
                       "topic_id": topic_id, "is_internal": is_internal,
                       "partitions": partitions})
    cursor = r.read_int8()
    r.read_uvarint()
    return {"correlation_id": cid, "topics": topics, "cursor": cursor}


def parse_fetch_response(data):
    r = BinaryReader(data)
    msg_size = r.read_int32()
    assert msg_size == len(data) - 4
    cid = r.read_int32()
    r.read_uvarint()  # header v1 tag buffer
    throttle = r.read_int32()
    error_code = r.read_int16()
    session_id = r.read_int32()
    resp_count = r.read_uvarint() - 1
    responses = []
    for _ in range(resp_count):
        topic_id = r.read_uuid()
        pcount = r.read_uvarint() - 1
        partitions = []
        for _ in range(pcount):
            pi = r.read_int32()
            pe = r.read_int16()
            hw = r.read_int64()
            lso = r.read_int64()
            ls_off = r.read_int64()
            at_count = r.read_uvarint() - 1
            for _ in range(at_count):
                r.read_int64()
                r.read_int64()
                r.read_uvarint()
            prr = r.read_int32()
            records = r.read_compact_nullable_bytes()
            r.read_uvarint()
            partitions.append({"partition_index": pi, "error_code": pe,
                               "records": records})
        r.read_uvarint()
        responses.append({"topic_id": topic_id, "partitions": partitions})
    r.read_uvarint()
    return {"correlation_id": cid, "error_code": error_code,
            "responses": responses}


def parse_metadata_response_v1(data):
    """Parse Metadata v1 response (old-style encoding, header v0)."""
    r = BinaryReader(data)
    msg_size = r.read_int32()
    assert msg_size == len(data) - 4

    # Header v0
    cid = r.read_int32()

    # Brokers (old-style array: INT32 count)
    broker_count = r.read_int32()
    brokers = []
    for _ in range(broker_count):
        node_id = r.read_int32()
        host_len = r.read_int16()
        host = r.read(host_len).decode('utf-8')
        port = r.read_int32()
        rack_len = r.read_int16()
        rack = None if rack_len < 0 else r.read(rack_len).decode('utf-8')
        brokers.append({"node_id": node_id, "host": host,
                        "port": port, "rack": rack})

    controller_id = r.read_int32()

    # Topics (old-style array)
    topic_count = r.read_int32()
    topics = []
    for _ in range(topic_count):
        error_code = r.read_int16()
        name_len = r.read_int16()
        name = r.read(name_len).decode('utf-8')
        is_internal = r.read_int8()
        part_count = r.read_int32()
        partitions = []
        for _ in range(part_count):
            pe = r.read_int16()
            pi = r.read_int32()
            leader = r.read_int32()
            rep_count = r.read_int32()
            replicas = [r.read_int32() for _ in range(rep_count)]
            isr_count = r.read_int32()
            isr_list = [r.read_int32() for _ in range(isr_count)]
            partitions.append({"error_code": pe, "partition_index": pi,
                               "leader": leader, "replicas": replicas,
                               "isr": isr_list})
        topics.append({"error_code": error_code, "name": name,
                       "is_internal": is_internal, "partitions": partitions})

    return {"correlation_id": cid, "brokers": brokers,
            "controller_id": controller_id, "topics": topics}


# ─── Network helpers ─────────────────────────────────────────────────────

def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed prematurely")
        buf += chunk
    return buf


def send_recv(sock, request):
    sock.sendall(request)
    header = recv_exact(sock, 4)
    msg_size = struct.unpack('>i', header)[0]
    body = recv_exact(sock, msg_size)
    return header + body


# ─── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def broker():
    proc = subprocess.Popen(
        ["/app/run.sh"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for port 9092
    for _ in range(50):
        try:
            s = socket.create_connection(("localhost", 9092), timeout=1)
            s.close()
            break
        except (ConnectionRefusedError, OSError):
            if proc.poll() is not None:
                out, err = proc.communicate()
                pytest.fail(f"Broker exited early: {err.decode()}")
            time.sleep(0.2)
    else:
        proc.kill()
        out, err = proc.communicate()
        pytest.fail(f"Broker did not start on port 9092 within 10 seconds. stderr: {err.decode()}")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def conn(broker):
    sock = socket.create_connection(("localhost", 9092), timeout=10)
    yield sock
    sock.close()


# ─── Tests: ApiVersions ─────────────────────────────────────────────────

class TestApiVersions:
    def test_basic_response(self, conn):
        """ApiVersions v4 returns supported API keys including Metadata."""
        req = build_api_versions_request(4, 42)
        resp = parse_api_versions_response(send_recv(conn, req))
        assert resp["correlation_id"] == 42
        assert resp["error_code"] == 0
        # Must advertise ApiVersions(18), Metadata(3),
        # DescribeTopicPartitions(75), Fetch(1)
        assert 18 in resp["api_keys"]
        assert resp["api_keys"][18][1] >= 4
        assert 3 in resp["api_keys"], "Metadata API (key 3) must be advertised"
        assert resp["api_keys"][3][1] >= 1
        assert 75 in resp["api_keys"]
        assert resp["api_keys"][75][1] >= 0
        assert 1 in resp["api_keys"]
        assert resp["api_keys"][1][1] >= 16

    def test_unsupported_version(self, conn):
        """ApiVersions with unsupported version returns error 35."""
        req = build_api_versions_request(99, 7777)
        resp = parse_api_versions_response(send_recv(conn, req))
        assert resp["correlation_id"] == 7777
        assert resp["error_code"] == 35

    def test_correlation_id_echo(self, conn):
        """Correlation ID is echoed correctly."""
        for cid in [0, 1, 0x7FFFFFFF, 12345]:
            req = build_api_versions_request(4, cid)
            resp = parse_api_versions_response(send_recv(conn, req))
            assert resp["correlation_id"] == cid


# ─── Tests: Metadata ────────────────────────────────────────────────────

class TestMetadata:
    def test_all_topics(self, conn):
        """Metadata with null topics array returns all known topics."""
        req = build_metadata_request_v1(500, topics=None)
        resp = parse_metadata_response_v1(send_recv(conn, req))
        assert resp["correlation_id"] == 500
        topic_names = sorted(t["name"] for t in resp["topics"])
        assert "alpha" in topic_names
        assert "beta" in topic_names

    def test_broker_info(self, conn):
        """Metadata response includes correct broker information."""
        req = build_metadata_request_v1(501, topics=None)
        resp = parse_metadata_response_v1(send_recv(conn, req))
        assert len(resp["brokers"]) >= 1
        b = resp["brokers"][0]
        assert b["node_id"] == 1
        assert b["host"] == "localhost"
        assert b["port"] == 9092

    def test_controller_id(self, conn):
        """Metadata response includes controller_id = 1."""
        req = build_metadata_request_v1(502, topics=None)
        resp = parse_metadata_response_v1(send_recv(conn, req))
        assert resp["controller_id"] == 1

    def test_specific_topic_beta(self, conn):
        """Metadata requesting 'beta' returns only beta with 1 partition."""
        req = build_metadata_request_v1(503, topics=["beta"])
        resp = parse_metadata_response_v1(send_recv(conn, req))
        assert resp["correlation_id"] == 503
        assert len(resp["topics"]) == 1
        t = resp["topics"][0]
        assert t["error_code"] == 0
        assert t["name"] == "beta"
        assert len(t["partitions"]) == 1
        assert t["partitions"][0]["partition_index"] == 0
        assert t["partitions"][0]["leader"] == 1

    def test_alpha_partitions(self, conn):
        """Metadata for 'alpha' shows 2 partitions."""
        req = build_metadata_request_v1(504, topics=["alpha"])
        resp = parse_metadata_response_v1(send_recv(conn, req))
        t = resp["topics"][0]
        assert t["error_code"] == 0
        assert t["name"] == "alpha"
        assert len(t["partitions"]) == 2
        indices = sorted(p["partition_index"] for p in t["partitions"])
        assert indices == [0, 1]

    def test_unknown_topic(self, conn):
        """Metadata for unknown topic returns error code 3."""
        req = build_metadata_request_v1(505, topics=["nonexistent"])
        resp = parse_metadata_response_v1(send_recv(conn, req))
        assert len(resp["topics"]) == 1
        t = resp["topics"][0]
        assert t["error_code"] == 3
        assert t["name"] == "nonexistent"
        assert len(t["partitions"]) == 0

    def test_correlation_id_echo(self, conn):
        """Metadata correctly echoes correlation ID."""
        req = build_metadata_request_v1(99999, topics=None)
        resp = parse_metadata_response_v1(send_recv(conn, req))
        assert resp["correlation_id"] == 99999


# ─── Tests: DescribeTopicPartitions ──────────────────────────────────────

class TestDescribeTopicPartitions:
    def test_unknown_topic(self, conn):
        """Unknown topic returns error code 3 with zeroed UUID."""
        req = build_dtp_request(100, ["nonexistent"])
        resp = parse_dtp_response(send_recv(conn, req))
        assert resp["correlation_id"] == 100
        assert len(resp["topics"]) == 1
        t = resp["topics"][0]
        assert t["error_code"] == 3
        assert t["name"] == "nonexistent"
        assert t["topic_id"] == b'\x00' * 16
        assert len(t["partitions"]) == 0

    def test_known_topic_beta(self, conn):
        """Topic 'beta' returns correct UUID and 1 partition."""
        req = build_dtp_request(200, ["beta"])
        resp = parse_dtp_response(send_recv(conn, req))
        assert resp["correlation_id"] == 200
        assert len(resp["topics"]) == 1
        t = resp["topics"][0]
        assert t["error_code"] == 0
        assert t["name"] == "beta"
        assert t["topic_id"] == BETA_UUID_BYTES
        assert len(t["partitions"]) == 1
        p = t["partitions"][0]
        assert p["error_code"] == 0
        assert p["partition_index"] == 0
        assert p["leader_id"] == 1

    def test_known_topic_alpha(self, conn):
        """Topic 'alpha' returns 2 partitions."""
        req = build_dtp_request(201, ["alpha"])
        resp = parse_dtp_response(send_recv(conn, req))
        assert resp["correlation_id"] == 201
        t = resp["topics"][0]
        assert t["error_code"] == 0
        assert t["topic_id"] == ALPHA_UUID_BYTES
        assert len(t["partitions"]) == 2
        indices = sorted(p["partition_index"] for p in t["partitions"])
        assert indices == [0, 1]

    def test_null_cursor(self, conn):
        """Response cursor is null (-1)."""
        req = build_dtp_request(202, ["beta"])
        resp = parse_dtp_response(send_recv(conn, req))
        assert resp["cursor"] == -1


# ─── Tests: Fetch ────────────────────────────────────────────────────────

class TestFetch:
    def test_no_topics(self, conn):
        """Fetch with no topics returns empty responses."""
        req = build_fetch_request(300, [])
        resp = parse_fetch_response(send_recv(conn, req))
        assert resp["correlation_id"] == 300
        assert resp["error_code"] == 0
        assert len(resp["responses"]) == 0

    def test_unknown_topic_uuid(self, conn):
        """Fetch with unknown UUID returns error 100."""
        req = build_fetch_request(301, [(UNKNOWN_UUID_BYTES, 0)])
        resp = parse_fetch_response(send_recv(conn, req))
        assert resp["correlation_id"] == 301
        assert len(resp["responses"]) == 1
        assert resp["responses"][0]["topic_id"] == UNKNOWN_UUID_BYTES
        p = resp["responses"][0]["partitions"][0]
        assert p["error_code"] == 100

    def test_empty_partition(self, conn):
        """Fetch for alpha partition 1 (empty) returns no records."""
        req = build_fetch_request(302, [(ALPHA_UUID_BYTES, 1)])
        resp = parse_fetch_response(send_recv(conn, req))
        assert resp["correlation_id"] == 302
        p = resp["responses"][0]["partitions"][0]
        assert p["error_code"] == 0
        # records should be empty (0 bytes) or null
        assert p["records"] is None or len(p["records"]) == 0

    def test_fetch_beta_partition_0(self, conn):
        """Fetch for beta-0 returns correct RecordBatch bytes from disk."""
        log_path = os.path.join(KRAFT_LOG_DIR, "beta-0", "00000000000000000000.log")
        with open(log_path, 'rb') as f:
            expected = f.read()
        assert len(expected) > 0, "beta-0 log should not be empty"

        req = build_fetch_request(303, [(BETA_UUID_BYTES, 0)])
        resp = parse_fetch_response(send_recv(conn, req))
        assert resp["correlation_id"] == 303
        p = resp["responses"][0]["partitions"][0]
        assert p["error_code"] == 0
        assert p["records"] == expected

    def test_fetch_alpha_partition_0(self, conn):
        """Fetch for alpha-0 returns multiple RecordBatches from disk."""
        log_path = os.path.join(KRAFT_LOG_DIR, "alpha-0", "00000000000000000000.log")
        with open(log_path, 'rb') as f:
            expected = f.read()
        assert len(expected) > 0, "alpha-0 log should not be empty"

        req = build_fetch_request(304, [(ALPHA_UUID_BYTES, 0)])
        resp = parse_fetch_response(send_recv(conn, req))
        assert resp["correlation_id"] == 304
        p = resp["responses"][0]["partitions"][0]
        assert p["error_code"] == 0
        assert p["records"] == expected


# ─── Tests: kcat interoperability ────────────────────────────────────────

class TestKcatInterop:
    def test_kcat_list_metadata(self, broker):
        """kcat -L must successfully list metadata from the broker."""
        result = None
        for attempt in range(3):
            result = subprocess.run(
                ["kcat", "-L", "-b", "localhost:9092"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                break
            time.sleep(1)
        assert result.returncode == 0, \
            f"kcat -L failed (exit {result.returncode}): {result.stderr}"
        assert "alpha" in result.stdout, \
            f"topic 'alpha' not found in kcat output: {result.stdout}"
        assert "beta" in result.stdout, \
            f"topic 'beta' not found in kcat output: {result.stdout}"

    def test_kcat_partition_counts(self, broker):
        """kcat -L reports correct partition counts for each topic."""
        result = subprocess.run(
            ["kcat", "-L", "-b", "localhost:9092"],
            capture_output=True, text=True, timeout=15
        )
        assert result.returncode == 0, f"kcat failed: {result.stderr}"
        # alpha has 2 partitions, beta has 1
        assert "2 partitions" in result.stdout, \
            f"expected '2 partitions' in output: {result.stdout}"
        assert "1 partitions" in result.stdout, \
            f"expected '1 partitions' in output: {result.stdout}"

    def test_kcat_broker_reported(self, broker):
        """kcat -L reports at least one broker."""
        result = subprocess.run(
            ["kcat", "-L", "-b", "localhost:9092"],
            capture_output=True, text=True, timeout=15
        )
        assert result.returncode == 0
        assert "broker" in result.stdout.lower()
        assert "9092" in result.stdout
