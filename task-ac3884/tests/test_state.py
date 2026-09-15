
"""
Tests for DNS Zone Snapshot with HMAC-Verified Piece Distribution.
"""

import concurrent.futures
import hashlib
import hmac
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time

import pytest
import requests


# ============================================================
# Task DNA constants
# ============================================================

HMAC_KEY = bytes.fromhex("a3f7c9e1d2b4685f")
PIECE_LENGTH = 384
ZONE_NAME = "relay-9f.nebula.internal"


# ============================================================
# Bencoding decoder (test-side, independent of solution)
# ============================================================

def bdecode(data):
    def _d(data, i):
        c = data[i:i+1]
        if c == b'i':
            e = data.index(b'e', i+1)
            return int(data[i+1:e]), e+1
        elif c == b'l':
            r, i = [], i+1
            while data[i:i+1] != b'e':
                v, i = _d(data, i)
                r.append(v)
            return r, i+1
        elif c == b'd':
            r, i = {}, i+1
            while data[i:i+1] != b'e':
                k, i = _d(data, i)
                v, i = _d(data, i)
                r[k] = v
            return r, i+1
        else:
            colon = data.index(b':', i)
            ln = int(data[i:colon])
            s = colon + 1
            return data[s:s+ln], s+ln
    return _d(data, 0)[0]


# ============================================================
# DNS helpers
# ============================================================

QTYPES = {'A': 1, 'NS': 2, 'CNAME': 5, 'SOA': 6, 'MX': 15, 'TXT': 16, 'AAAA': 28}


def build_dns_query(name, qtype_str):
    qtype = QTYPES[qtype_str]
    header = struct.pack('>HHHHHH', 0xABCD, 0x0100, 1, 0, 0, 0)
    qname = b''
    for label in name.split('.'):
        qname += struct.pack('B', len(label)) + label.encode('ascii')
    qname += b'\x00'
    return header + qname + struct.pack('>HH', qtype, 1)


def parse_dns_name(data, offset):
    labels = []
    jumped = False
    end_off = None
    seen = set()
    while True:
        if offset in seen or offset >= len(data):
            break
        seen.add(offset)
        b = data[offset]
        if (b & 0xC0) == 0xC0:
            if not jumped:
                end_off = offset + 2
            ptr = struct.unpack('>H', data[offset:offset+2])[0] & 0x3FFF
            offset = ptr
            jumped = True
            continue
        if b == 0:
            if not jumped:
                end_off = offset + 1
            break
        offset += 1
        labels.append(data[offset:offset+b].decode('ascii'))
        offset += b
    return '.'.join(labels), end_off if end_off else offset + 1


def send_dns_query(name, qtype_str, port=5353, timeout=5):
    q = build_dns_query(name, qtype_str)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(q, ('127.0.0.1', port))
        resp, _ = sock.recvfrom(4096)
        return resp
    finally:
        sock.close()


def parse_dns_response(data):
    rid, flags, qdc, anc, nsc, arc = struct.unpack('>HHHHHH', data[:12])
    offset = 12
    for _ in range(qdc):
        _, offset = parse_dns_name(data, offset)
        offset += 4
    answers = []
    for _ in range(anc):
        name, offset = parse_dns_name(data, offset)
        rtype, rclass, ttl, rdlen = struct.unpack('>HHIH', data[offset:offset+10])
        rdata_off = offset + 10
        rdata = data[rdata_off:rdata_off+rdlen]
        offset = rdata_off + rdlen
        answers.append({
            'name': name, 'type': rtype, 'class': rclass,
            'ttl': ttl, 'rdata': rdata, 'rdata_offset': rdata_off,
        })
    return {
        'id': rid, 'flags': flags, 'rcode': flags & 0xF,
        'ancount': anc, 'answers': answers, 'raw': data,
    }


# ============================================================
# Test data — task-specific DNA values
# ============================================================

TEST_RECORDS = [
    {"name": "relay-9f.nebula.internal", "type": "A", "ttl": 1800, "rdata": "10.47.203.91"},
    {"name": "relay-9f.nebula.internal", "type": "AAAA", "ttl": 1800,
     "rdata": "fd12:3456:789a:1::47:cb5b"},
    {"name": "gw.relay-9f.nebula.internal", "type": "A", "ttl": 1800, "rdata": "10.47.203.1"},
    {"name": "relay-9f.nebula.internal", "type": "MX", "ttl": 3600,
     "rdata": "20 gw.relay-9f.nebula.internal"},
    {"name": "cdn.relay-9f.nebula.internal", "type": "CNAME", "ttl": 900,
     "rdata": "relay-9f.nebula.internal"},
    {"name": "relay-9f.nebula.internal", "type": "NS", "ttl": 7200,
     "rdata": "ns1.relay-9f.nebula.internal"},
    {"name": "relay-9f.nebula.internal", "type": "NS", "ttl": 7200,
     "rdata": "ns2.relay-9f.nebula.internal"},
    {"name": "relay-9f.nebula.internal", "type": "TXT", "ttl": 3600,
     "rdata": "fp=a3f7c9e1d2b4685f;proto=dnssync;v=3"},
    {"name": "relay-9f.nebula.internal", "type": "SOA", "ttl": 86400,
     "rdata": "ns1.relay-9f.nebula.internal ops.relay-9f.nebula.internal 2025071542 10800 3600 604800 1800"},
]

BASE = "http://localhost:8080"


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="session")
def server():
    proc = subprocess.Popen(
        [sys.executable, '/app/server.py'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    for _ in range(40):
        try:
            requests.get(f"{BASE}/zones/_probe/records", timeout=0.5)
            break
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("Server did not start")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def zone_id(server):
    resp = requests.post(f"{BASE}/zones", json={
        "name": ZONE_NAME, "records": TEST_RECORDS,
    })
    assert resp.status_code == 201
    return resp.json()["zone_id"]


@pytest.fixture(scope="session")
def manifest_bytes(server, zone_id):
    resp = requests.post(f"{BASE}/zones/{zone_id}/snapshot")
    assert resp.status_code == 201
    return resp.content


# ============================================================
# Zone creation & retrieval
# ============================================================

class TestZoneCreation:
    def test_create_returns_id(self, zone_id):
        assert isinstance(zone_id, str) and len(zone_id) > 0

    def test_get_records_count(self, server, zone_id):
        r = requests.get(f"{BASE}/zones/{zone_id}/records")
        assert r.status_code == 200
        assert len(r.json()["records"]) == len(TEST_RECORDS)

    def test_independent_zones(self, server):
        r1 = requests.post(f"{BASE}/zones", json={
            "name": "alpha.internal",
            "records": [{"name": "alpha.internal", "type": "A", "ttl": 60,
                         "rdata": "10.99.1.1"}],
        })
        r2 = requests.post(f"{BASE}/zones", json={
            "name": "beta.internal",
            "records": [{"name": "beta.internal", "type": "A", "ttl": 60,
                         "rdata": "10.99.2.2"}],
        })
        assert r1.json()["zone_id"] != r2.json()["zone_id"]
        d1 = requests.get(f"{BASE}/zones/{r1.json()['zone_id']}/records").json()
        d2 = requests.get(f"{BASE}/zones/{r2.json()['zone_id']}/records").json()
        assert d1["records"][0]["rdata"] == "10.99.1.1"
        assert d2["records"][0]["rdata"] == "10.99.2.2"


# ============================================================
# Snapshot / manifest / HMAC piece hashing
# ============================================================

class TestSnapshot:
    def test_manifest_content_type(self, server, zone_id, manifest_bytes):
        r = requests.get(f"{BASE}/zones/{zone_id}/snapshot/manifest")
        assert r.headers['Content-Type'] == 'application/x-bittorrent'

    def test_manifest_has_required_keys(self, manifest_bytes):
        m = bdecode(manifest_bytes)
        for key in [b'algorithm', b'fingerprint', b'piece length', b'pieces',
                    b'record count', b'total length', b'zone']:
            assert key in m, f"Missing manifest key {key}"

    def test_manifest_algorithm_and_fingerprint(self, manifest_bytes):
        m = bdecode(manifest_bytes)
        assert m[b'algorithm'] == b'hmac-sha1', "algorithm must be b'hmac-sha1'"
        assert m[b'fingerprint'] == HMAC_KEY, (
            f"fingerprint must be {HMAC_KEY!r}, got {m[b'fingerprint']!r}"
        )

    def test_manifest_values(self, manifest_bytes):
        m = bdecode(manifest_bytes)
        assert m[b'zone'] == ZONE_NAME.encode()
        assert m[b'piece length'] == PIECE_LENGTH
        assert m[b'record count'] == len(TEST_RECORDS)
        assert m[b'total length'] > 0
        assert len(m[b'pieces']) > 0 and len(m[b'pieces']) % 20 == 0

    def test_manifest_keys_sorted(self, manifest_bytes):
        m = bdecode(manifest_bytes)
        keys = list(m.keys())
        assert keys == sorted(keys), "Bencoded dict keys must be sorted"

    def test_piece_hmac_integrity(self, server, zone_id, manifest_bytes):
        """Each piece's HMAC-SHA1 (keyed with task fingerprint) must match manifest."""
        m = bdecode(manifest_bytes)
        ph = m[b'pieces']
        n = len(ph) // 20
        for i in range(n):
            r = requests.get(f"{BASE}/zones/{zone_id}/snapshot/piece/{i}")
            assert r.status_code == 200
            expected = ph[i*20:(i+1)*20]
            actual = hmac.new(HMAC_KEY, r.content, hashlib.sha1).digest()
            assert actual == expected, f"Piece {i} HMAC-SHA1 mismatch"

    def test_total_length_equals_pieces_sum(self, server, zone_id, manifest_bytes):
        m = bdecode(manifest_bytes)
        n = len(m[b'pieces']) // 20
        total = sum(
            len(requests.get(f"{BASE}/zones/{zone_id}/snapshot/piece/{i}").content)
            for i in range(n)
        )
        assert total == m[b'total length']

    def test_piece_length_384(self, server, zone_id, manifest_bytes):
        """All pieces except the last must be exactly 384 bytes."""
        m = bdecode(manifest_bytes)
        n = len(m[b'pieces']) // 20
        assert n >= 1
        for i in range(n - 1):
            r = requests.get(f"{BASE}/zones/{zone_id}/snapshot/piece/{i}")
            assert len(r.content) == PIECE_LENGTH, (
                f"Piece {i} is {len(r.content)} bytes, expected {PIECE_LENGTH}"
            )
        last = requests.get(f"{BASE}/zones/{zone_id}/snapshot/piece/{n-1}")
        assert 0 < len(last.content) <= PIECE_LENGTH

    def test_verify_endpoint(self, server, zone_id, manifest_bytes):
        r = requests.get(f"{BASE}/zones/{zone_id}/snapshot/verify")
        assert r.status_code == 200
        d = r.json()
        assert d["valid"] is True
        assert all(p["valid"] for p in d["pieces"])


# ============================================================
# DNS authoritative server
# ============================================================

class TestDNSServer:
    def test_a_record(self, server, zone_id):
        resp = send_dns_query('relay-9f.nebula.internal', 'A')
        p = parse_dns_response(resp)
        assert p['rcode'] == 0
        assert len(p['answers']) == 1
        ip = '.'.join(str(b) for b in p['answers'][0]['rdata'])
        assert ip == '10.47.203.91'

    def test_aaaa_record(self, server, zone_id):
        resp = send_dns_query('relay-9f.nebula.internal', 'AAAA')
        p = parse_dns_response(resp)
        assert p['rcode'] == 0
        assert len(p['answers']) == 1
        assert len(p['answers'][0]['rdata']) == 16

    def test_mx_record_priority_and_exchange(self, server, zone_id):
        resp = send_dns_query('relay-9f.nebula.internal', 'MX')
        p = parse_dns_response(resp)
        assert p['rcode'] == 0
        assert len(p['answers']) == 1
        prio = struct.unpack('>H', p['answers'][0]['rdata'][:2])[0]
        assert prio == 20
        exchange, _ = parse_dns_name(p['raw'], p['answers'][0]['rdata_offset'] + 2)
        assert exchange == 'gw.relay-9f.nebula.internal'

    def test_cname_target(self, server, zone_id):
        resp = send_dns_query('cdn.relay-9f.nebula.internal', 'CNAME')
        p = parse_dns_response(resp)
        assert p['rcode'] == 0
        assert len(p['answers']) == 1
        target, _ = parse_dns_name(p['raw'], p['answers'][0]['rdata_offset'])
        assert target == 'relay-9f.nebula.internal'

    def test_ns_records(self, server, zone_id):
        resp = send_dns_query('relay-9f.nebula.internal', 'NS')
        p = parse_dns_response(resp)
        assert p['rcode'] == 0
        assert len(p['answers']) == 2
        ns_names = set()
        for a in p['answers']:
            name, _ = parse_dns_name(p['raw'], a['rdata_offset'])
            ns_names.add(name)
        assert ns_names == {'ns1.relay-9f.nebula.internal', 'ns2.relay-9f.nebula.internal'}

    def test_txt_record(self, server, zone_id):
        resp = send_dns_query('relay-9f.nebula.internal', 'TXT')
        p = parse_dns_response(resp)
        assert p['rcode'] == 0
        assert len(p['answers']) == 1
        rd = p['answers'][0]['rdata']
        txt_len = rd[0]
        txt = rd[1:1+txt_len].decode('utf-8')
        assert 'fp=a3f7c9e1d2b4685f' in txt

    def test_soa_record(self, server, zone_id):
        resp = send_dns_query('relay-9f.nebula.internal', 'SOA')
        p = parse_dns_response(resp)
        assert p['rcode'] == 0
        assert len(p['answers']) == 1
        assert p['answers'][0]['type'] == 6
        assert len(p['answers'][0]['rdata']) >= 22

    def test_label_compression_used(self, server, zone_id):
        """NS response must use compression — uncompressed would be ~174 bytes."""
        resp = send_dns_query('relay-9f.nebula.internal', 'NS')
        assert len(resp) < 120, (
            f"Response is {len(resp)} bytes; compression likely missing"
        )


# ============================================================
# Wire-format pieces — sort order and structure
# ============================================================

class TestWireFormatPieces:
    def test_pieces_are_valid_rrs(self, server, zone_id, manifest_bytes):
        m = bdecode(manifest_bytes)
        n = len(m[b'pieces']) // 20
        wire = b''
        for i in range(n):
            wire += requests.get(f"{BASE}/zones/{zone_id}/snapshot/piece/{i}").content

        offset = 0
        count = 0
        seen_types = set()
        while offset < len(wire):
            _, offset = parse_dns_name(wire, offset)
            assert offset + 10 <= len(wire), "Truncated RR header"
            rtype, rclass, ttl, rdlen = struct.unpack('>HHIH', wire[offset:offset+10])
            offset += 10
            assert rclass == 1
            assert rtype in {1, 2, 5, 6, 15, 16, 28}
            seen_types.add(rtype)
            offset += rdlen
            count += 1

        assert count == len(TEST_RECORDS)
        assert seen_types == {1, 2, 5, 6, 15, 16, 28}

    def test_records_sorted_by_type_then_name(self, server, zone_id, manifest_bytes):
        """Records in wire format must be sorted by (type_code asc, name asc)."""
        m = bdecode(manifest_bytes)
        n = len(m[b'pieces']) // 20
        wire = b''
        for i in range(n):
            wire += requests.get(f"{BASE}/zones/{zone_id}/snapshot/piece/{i}").content

        offset = 0
        record_order = []
        while offset < len(wire):
            name, offset = parse_dns_name(wire, offset)
            rtype, rclass, ttl, rdlen = struct.unpack('>HHIH', wire[offset:offset+10])
            offset += 10 + rdlen
            record_order.append((rtype, name.lower()))

        for i in range(len(record_order) - 1):
            curr = record_order[i]
            nxt = record_order[i + 1]
            assert curr <= nxt, (
                f"Records not sorted by (type, name): {curr} came before {nxt}"
            )

        # Verify A records (type 1) come before NS (type 2) etc.
        types_in_order = [r[0] for r in record_order]
        assert types_in_order == sorted(types_in_order), (
            "Type codes are not in ascending order"
        )


# ============================================================
# Error handling
# ============================================================

class TestErrors:
    def test_unknown_zone(self, server):
        r = requests.get(f"{BASE}/zones/zzz_no_such_zone/records")
        assert r.status_code == 404

    def test_bad_piece_number(self, server, zone_id, manifest_bytes):
        r = requests.get(f"{BASE}/zones/{zone_id}/snapshot/piece/99999")
        assert r.status_code == 404

    def test_manifest_before_snapshot(self, server):
        r = requests.post(f"{BASE}/zones", json={
            "name": "nosnap.internal",
            "records": [{"name": "nosnap.internal", "type": "A", "ttl": 60,
                         "rdata": "10.0.0.1"}],
        })
        zid = r.json()["zone_id"]
        assert requests.get(f"{BASE}/zones/{zid}/snapshot/manifest").status_code == 404


# ============================================================
# Concurrency
# ============================================================

class TestConcurrency:
    def test_parallel_http(self, server, zone_id, manifest_bytes):
        def fetch():
            return requests.get(f"{BASE}/zones/{zone_id}/records")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(fetch) for _ in range(20)]
            results = [f.result() for f in futs]
        assert all(r.status_code == 200 for r in results)

    def test_parallel_dns(self, server, zone_id):
        def query():
            resp = send_dns_query('relay-9f.nebula.internal', 'A')
            p = parse_dns_response(resp)
            return p['rcode'] == 0 and len(p['answers']) == 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futs = [pool.submit(query) for _ in range(10)]
            results = [f.result() for f in futs]
        assert all(results)
