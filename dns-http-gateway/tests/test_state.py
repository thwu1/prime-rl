
"""
Tests for multi-protocol DNS-HTTP gateway server.
Verifies DNS wire format, HTTP API, bencode serialization, CNAME chain resolution,
label compression parsing, and cross-protocol integration.
"""

import http.client
import json
import os
import signal
import socket
import struct
import subprocess
import threading
import time

import pytest

DNS_HOST = "127.0.0.1"
DNS_PORT = 2053
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8080


# ==================== Bencode helpers ====================

def bencode_encode(obj):
    if isinstance(obj, int):
        return f"i{obj}e".encode()
    elif isinstance(obj, str):
        b = obj.encode("utf-8")
        return f"{len(b)}:".encode() + b
    elif isinstance(obj, bytes):
        return f"{len(obj)}:".encode() + obj
    elif isinstance(obj, list):
        return b"l" + b"".join(bencode_encode(item) for item in obj) + b"e"
    elif isinstance(obj, dict):
        result = b"d"
        for key in sorted(obj.keys()):
            result += bencode_encode(key) + bencode_encode(obj[key])
        result += b"e"
        return result
    raise ValueError(f"Cannot bencode type {type(obj)}")


def _bencode_decode(data, idx):
    ch = data[idx : idx + 1]
    if ch == b"i":
        end = data.index(b"e", idx)
        return int(data[idx + 1 : end]), end + 1
    elif ch == b"l":
        result = []
        idx += 1
        while data[idx : idx + 1] != b"e":
            item, idx = _bencode_decode(data, idx)
            result.append(item)
        return result, idx + 1
    elif ch == b"d":
        result = {}
        idx += 1
        while data[idx : idx + 1] != b"e":
            key, idx = _bencode_decode(data, idx)
            val, idx = _bencode_decode(data, idx)
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            result[key] = val
        return result, idx + 1
    elif ch.isdigit():
        colon = data.index(b":", idx)
        length = int(data[idx:colon])
        start = colon + 1
        return data[start : start + length], start + length
    else:
        raise ValueError(f"Bad bencode at {idx}")


def bencode_decode(data):
    if isinstance(data, str):
        data = data.encode()
    result, _ = _bencode_decode(data, 0)
    return result


def bytes_to_native(obj):
    """Recursively convert bytes to str in decoded bencode data."""
    if isinstance(obj, bytes):
        return obj.decode("utf-8")
    elif isinstance(obj, list):
        return [bytes_to_native(i) for i in obj]
    elif isinstance(obj, dict):
        return {bytes_to_native(k): bytes_to_native(v) for k, v in obj.items()}
    return obj


# ==================== DNS helpers ====================

def encode_dns_name(domain):
    """Encode domain to DNS label sequence (no compression)."""
    if domain.endswith("."):
        domain = domain[:-1]
    result = b""
    for label in domain.split("."):
        encoded = label.encode("ascii")
        result += struct.pack("B", len(encoded)) + encoded
    result += b"\x00"
    return result


def decode_dns_name(data, offset):
    """Decode DNS label sequence with compression pointer support."""
    labels = []
    jumped = False
    final_offset = offset
    jumps = 0
    while True:
        if offset >= len(data):
            break
        length = data[offset]
        if (length & 0xC0) == 0xC0:
            if not jumped:
                final_offset = offset + 2
            pointer = struct.unpack("!H", data[offset : offset + 2])[0] & 0x3FFF
            offset = pointer
            jumped = True
            jumps += 1
            if jumps > 15:
                raise ValueError("Too many compression jumps")
        elif length == 0:
            if not jumped:
                final_offset = offset + 1
            break
        else:
            offset += 1
            labels.append(data[offset : offset + length].decode("ascii"))
            offset += length
    return ".".join(labels) + ".", final_offset


def build_dns_query(domain, qtype=1, query_id=0x1234, rd=True):
    """Construct a single-question DNS query packet."""
    flags = 0
    if rd:
        flags |= 1 << 8
    header = struct.pack("!HHHHHH", query_id, flags, 1, 0, 0, 0)
    question = encode_dns_name(domain) + struct.pack("!HH", qtype, 1)
    return header + question


def build_dns_query_opcode(domain, opcode, query_id=0xABCD, rd=False):
    """Construct a DNS query with a specific opcode."""
    flags = (opcode & 0xF) << 11
    if rd:
        flags |= 1 << 8
    header = struct.pack("!HHHHHH", query_id, flags, 1, 0, 0, 0)
    question = encode_dns_name(domain) + struct.pack("!HH", 1, 1)
    return header + question


def build_compressed_two_question_query(domain1, domain2, query_id=0x5678):
    """Build a DNS query with two questions where domain2 uses a compression pointer
    referencing a shared suffix in domain1.

    Both domains must share a suffix starting from the second label,
    e.g. 'abc.example.com' and 'def.example.com'.
    """
    flags = 1 << 8  # RD=1
    header = struct.pack("!HHHHHH", query_id, flags, 2, 0, 0, 0)

    q1_name = encode_dns_name(domain1)
    q1 = q1_name + struct.pack("!HH", 1, 1)

    # Calculate offset where the shared suffix starts in q1
    parts1 = domain1.rstrip(".").split(".")
    first_label_encoded_len = 1 + len(parts1[0])  # length byte + label bytes
    shared_offset = 12 + first_label_encoded_len  # 12 = header size

    parts2 = domain2.rstrip(".").split(".")
    unique_label = parts2[0]
    q2_name = (
        struct.pack("B", len(unique_label))
        + unique_label.encode("ascii")
        + struct.pack("!H", 0xC000 | shared_offset)
    )
    q2 = q2_name + struct.pack("!HH", 1, 1)

    return header + q1 + q2


def parse_dns_response(data):
    """Parse a DNS response into a structured dict."""
    if len(data) < 12:
        raise ValueError("Packet too short for DNS header")
    id_, flags, qdcount, ancount, nscount, arcount = struct.unpack(
        "!HHHHHH", data[:12]
    )
    parsed = {
        "id": id_,
        "qr": (flags >> 15) & 1,
        "opcode": (flags >> 11) & 0xF,
        "aa": (flags >> 10) & 1,
        "tc": (flags >> 9) & 1,
        "rd": (flags >> 8) & 1,
        "ra": (flags >> 7) & 1,
        "rcode": flags & 0xF,
        "qdcount": qdcount,
        "ancount": ancount,
        "questions": [],
        "answers": [],
    }

    offset = 12
    for _ in range(qdcount):
        name, offset = decode_dns_name(data, offset)
        qtype, qclass = struct.unpack("!HH", data[offset : offset + 4])
        offset += 4
        parsed["questions"].append({"name": name, "type": qtype, "class": qclass})

    for _ in range(ancount):
        name, offset = decode_dns_name(data, offset)
        rtype, rclass, ttl, rdlength = struct.unpack(
            "!HHIH", data[offset : offset + 10]
        )
        offset += 10
        rdata_start = offset
        rdata = data[offset : offset + rdlength]
        offset += rdlength

        answer = {
            "name": name,
            "type": rtype,
            "class": rclass,
            "ttl": ttl,
        }
        if rtype == 1 and rdlength == 4:
            answer["address"] = ".".join(str(b) for b in rdata)
        elif rtype == 5:
            cname, _ = decode_dns_name(data, rdata_start)
            answer["cname"] = cname

        parsed["answers"].append(answer)

    return parsed


def dns_query(packet, timeout=5):
    """Send a raw DNS query via UDP and return parsed response."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, (DNS_HOST, DNS_PORT))
        data, _ = sock.recvfrom(4096)
        return parse_dns_response(data)
    finally:
        sock.close()


# ==================== HTTP helpers ====================

def http_request(method, path, body=None, content_type=None):
    """Make an HTTP request and return (status, headers_dict, body_bytes)."""
    conn = http.client.HTTPConnection(HTTP_HOST, HTTP_PORT, timeout=10)
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    resp_body = resp.read()
    status = resp.status
    resp_headers = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return status, resp_headers, resp_body


def add_record_http(name, rtype, value, ttl=300):
    """Add a single record via HTTP POST with bencode body."""
    record = {"name": name, "type": rtype, "value": value, "ttl": ttl}
    body = bencode_encode(record)
    status, _, _ = http_request("POST", "/records", body=body, content_type="application/x-bencode")
    assert status == 201, f"POST /records returned {status}, expected 201"


# ==================== Server fixture ====================

@pytest.fixture(scope="session", autouse=True)
def server_process():
    """Start the server and wait until it is ready."""
    proc = subprocess.Popen(
        ["python3", "/app/server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    ready = False
    for attempt in range(40):
        time.sleep(0.5)
        if proc.poll() is not None:
            stdout = proc.stdout.read().decode(errors="replace")
            stderr = proc.stderr.read().decode(errors="replace")
            raise RuntimeError(
                f"Server exited early (code {proc.returncode}).\n"
                f"stdout: {stdout}\nstderr: {stderr}"
            )
        try:
            conn = http.client.HTTPConnection(HTTP_HOST, HTTP_PORT, timeout=2)
            conn.request("GET", "/records")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            ready = True
            break
        except Exception:
            continue

    if not ready:
        proc.terminate()
        raise RuntimeError("Server did not become ready within 20 seconds")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


# ==================== DNS Tests ====================

class TestDNSSeedRecords:
    """Verify that seed records from config.json are served via DNS."""

    def test_seed_a_record(self, server_process):
        """Query the seed A record and verify correct answer."""
        pkt = build_dns_query("seed.example.com")
        resp = dns_query(pkt)
        assert resp["qr"] == 1, "QR must be 1 for a response"
        assert resp["rcode"] == 0, f"Expected RCODE 0, got {resp['rcode']}"
        assert resp["ancount"] >= 1, "Expected at least one answer"
        a_records = [a for a in resp["answers"] if a["type"] == 1]
        assert len(a_records) >= 1, "Expected at least one A record in answers"
        assert a_records[0]["address"] == "10.0.0.1"

    def test_seed_cname_chain(self, server_process):
        """Query www.example.com (CNAME→web.example.com→A) and verify chain."""
        pkt = build_dns_query("www.example.com")
        resp = dns_query(pkt)
        assert resp["rcode"] == 0
        assert resp["ancount"] >= 2, f"Expected >=2 answers for CNAME chain, got {resp['ancount']}"
        cname_answers = [a for a in resp["answers"] if a["type"] == 5]
        a_answers = [a for a in resp["answers"] if a["type"] == 1]
        assert len(cname_answers) >= 1, "Expected CNAME record in answer"
        assert len(a_answers) >= 1, "Expected terminal A record in answer"
        assert a_answers[0]["address"] == "10.0.0.2"


class TestDNSHeaderFlags:
    """Verify DNS response header flag behaviour."""

    def test_qr_bit(self, server_process):
        pkt = build_dns_query("seed.example.com")
        resp = dns_query(pkt)
        assert resp["qr"] == 1

    def test_aa_bit_set_for_known_domain(self, server_process):
        pkt = build_dns_query("seed.example.com")
        resp = dns_query(pkt)
        assert resp["aa"] == 1, "AA should be 1 for domains in the store"

    def test_rd_mirrored(self, server_process):
        pkt_rd1 = build_dns_query("seed.example.com", rd=True)
        resp1 = dns_query(pkt_rd1)
        assert resp1["rd"] == 1, "RD should be mirrored as 1"

        pkt_rd0 = build_dns_query("seed.example.com", query_id=0x2345, rd=False)
        resp0 = dns_query(pkt_rd0)
        assert resp0["rd"] == 0, "RD should be mirrored as 0"

    def test_query_id_mirrored(self, server_process):
        test_id = 0xBEEF
        pkt = build_dns_query("seed.example.com", query_id=test_id)
        resp = dns_query(pkt)
        assert resp["id"] == test_id, f"Expected query ID 0x{test_id:04X}, got 0x{resp['id']:04X}"

    def test_nxdomain(self, server_process):
        pkt = build_dns_query("nonexistent.domain.test")
        resp = dns_query(pkt)
        assert resp["rcode"] == 3, f"Expected RCODE 3 (NXDOMAIN), got {resp['rcode']}"
        assert resp["ancount"] == 0

    def test_opcode_not_implemented(self, server_process):
        pkt = build_dns_query_opcode("seed.example.com", opcode=2)
        resp = dns_query(pkt)
        assert resp["rcode"] == 4, f"Expected RCODE 4 (Not Implemented) for non-zero opcode, got {resp['rcode']}"
        assert resp["opcode"] == 2, "OPCODE should be mirrored"


class TestDNSQuestionEcho:
    """Verify the question section is echoed in responses."""

    def test_question_echo(self, server_process):
        domain = "seed.example.com"
        pkt = build_dns_query(domain)
        resp = dns_query(pkt)
        assert resp["qdcount"] >= 1, "Must echo at least one question"
        q = resp["questions"][0]
        assert q["name"].rstrip(".") == domain.rstrip(".")
        assert q["type"] == 1
        assert q["class"] == 1


class TestDNSLabelCompression:
    """Verify the server can parse queries with DNS label compression pointers."""

    def test_compressed_query_two_questions(self, server_process):
        """Add two records sharing a suffix, send compressed query, verify both answers."""
        add_record_http("abc.compression.test", "A", "10.10.10.1")
        add_record_http("def.compression.test", "A", "10.10.10.2")

        pkt = build_compressed_two_question_query(
            "abc.compression.test", "def.compression.test"
        )
        resp = dns_query(pkt)

        assert resp["rcode"] == 0, f"Expected RCODE 0, got {resp['rcode']}"
        assert resp["qdcount"] == 2, f"Expected 2 questions echoed, got {resp['qdcount']}"
        assert resp["ancount"] >= 2, f"Expected >=2 answers, got {resp['ancount']}"

        addresses = sorted(a["address"] for a in resp["answers"] if a["type"] == 1)
        assert "10.10.10.1" in addresses, f"Missing answer for abc.compression.test: {addresses}"
        assert "10.10.10.2" in addresses, f"Missing answer for def.compression.test: {addresses}"


# ==================== HTTP Tests ====================

class TestHTTPRecords:
    """Test the HTTP /records endpoints."""

    def test_get_all_records(self, server_process):
        status, headers, body = http_request("GET", "/records")
        assert status == 200
        assert "application/json" in headers.get("content-type", "")
        records = json.loads(body)
        assert isinstance(records, list)
        # Should contain at least the seed records
        names = [r["name"] for r in records]
        assert any("seed.example.com" in n for n in names)

    def test_post_record_bencode(self, server_process):
        record = {"name": "httptest.example.com", "type": "A", "value": "10.5.5.5", "ttl": 120}
        body = bencode_encode(record)
        status, _, _ = http_request("POST", "/records", body=body, content_type="application/x-bencode")
        assert status == 201

        # Verify via GET
        status, _, resp_body = http_request("GET", "/records/httptest.example.com")
        assert status == 200
        records = json.loads(resp_body)
        assert len(records) >= 1
        assert records[0]["value"] == "10.5.5.5"

    def test_delete_record(self, server_process):
        # Add a record
        add_record_http("deleteme.example.com", "A", "10.9.9.9")

        # Verify it exists
        status, _, body = http_request("GET", "/records/deleteme.example.com")
        records = json.loads(body)
        assert len(records) >= 1

        # Delete it
        status, _, _ = http_request("DELETE", "/records/deleteme.example.com")
        assert status == 204

        # Verify deleted via DNS (should be NXDOMAIN)
        pkt = build_dns_query("deleteme.example.com")
        resp = dns_query(pkt)
        assert resp["rcode"] == 3, "Deleted record should produce NXDOMAIN"


class TestHTTPZoneTransfer:
    """Test the /zone-transfer endpoints for bencode bulk import/export."""

    def test_zone_export(self, server_process):
        status, headers, body = http_request("GET", "/zone-transfer")
        assert status == 200
        ct = headers.get("content-type", "")
        assert "bencode" in ct or "octet" in ct, f"Expected bencode content type, got {ct}"
        decoded = bencode_decode(body)
        decoded = bytes_to_native(decoded)
        assert isinstance(decoded, list)
        assert len(decoded) >= 3  # at least seed records

    def test_zone_import_and_dns_query(self, server_process):
        records = [
            {"name": "zt-alpha.example.com", "type": "A", "value": "10.20.1.1", "ttl": 600},
            {"name": "zt-beta.example.com", "type": "A", "value": "10.20.1.2", "ttl": 600},
        ]
        body = bencode_encode(records)
        status, _, _ = http_request("POST", "/zone-transfer", body=body, content_type="application/x-bencode")
        assert status == 201

        # Verify via DNS
        for rec in records:
            pkt = build_dns_query(rec["name"])
            resp = dns_query(pkt)
            assert resp["rcode"] == 0, f"Expected RCODE 0 for {rec['name']}"
            a_records = [a for a in resp["answers"] if a["type"] == 1]
            assert len(a_records) >= 1
            assert a_records[0]["address"] == rec["value"]


# ==================== Integration Tests ====================

class TestCrossProtocol:
    """Add records via HTTP, verify via DNS."""

    def test_add_via_http_query_via_dns(self, server_process):
        add_record_http("cross.protocol.test", "A", "172.16.0.42")

        pkt = build_dns_query("cross.protocol.test")
        resp = dns_query(pkt)
        assert resp["rcode"] == 0
        a_records = [a for a in resp["answers"] if a["type"] == 1]
        assert len(a_records) >= 1
        assert a_records[0]["address"] == "172.16.0.42"

    def test_multi_hop_cname_chain(self, server_process):
        """Build a 3-hop CNAME chain via HTTP and resolve via DNS."""
        add_record_http("hop1.chain.test", "CNAME", "hop2.chain.test")
        add_record_http("hop2.chain.test", "CNAME", "hop3.chain.test")
        add_record_http("hop3.chain.test", "A", "10.99.99.99")

        pkt = build_dns_query("hop1.chain.test")
        resp = dns_query(pkt)

        assert resp["rcode"] == 0
        # Should contain 2 CNAME + 1 A = 3 answers
        assert resp["ancount"] >= 3, f"Expected >=3 answers for 3-hop chain, got {resp['ancount']}"
        cnames = [a for a in resp["answers"] if a["type"] == 5]
        a_recs = [a for a in resp["answers"] if a["type"] == 1]
        assert len(cnames) >= 2, f"Expected >=2 CNAME records, got {len(cnames)}"
        assert len(a_recs) >= 1, "Expected terminal A record"
        assert a_recs[0]["address"] == "10.99.99.99"


class TestConcurrentDNS:
    """Verify the server handles concurrent DNS queries."""

    def test_concurrent_queries(self, server_process):
        results = [None] * 8
        errors = [None] * 8

        def worker(idx):
            try:
                pkt = build_dns_query("seed.example.com", query_id=0x1000 + idx)
                results[idx] = dns_query(pkt)
            except Exception as e:
                errors[idx] = e

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        for i in range(8):
            assert errors[i] is None, f"Thread {i} failed: {errors[i]}"
            assert results[i] is not None, f"Thread {i} got no result"
            assert results[i]["rcode"] == 0
            assert results[i]["id"] == 0x1000 + i
            a_recs = [a for a in results[i]["answers"] if a["type"] == 1]
            assert len(a_recs) >= 1
            assert a_recs[0]["address"] == "10.0.0.1"
