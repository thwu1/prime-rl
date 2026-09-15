"""
Tests for authoritative DNS server with EDNS(0), TCP, and pcap-derived zones.

Sends raw DNS queries over UDP/TCP, parses wire-format responses,
and verifies correctness of record data, response codes, flags,
EDNS(0) negotiation, and TCP framing.
"""

import os
import socket
import struct
import subprocess
import time
import random
import ipaddress
import pytest

TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_OPT = 41

SERVER_PORT = 5353
SERVER_HOST = '127.0.0.1'


# ── DNS wire format helpers ──

def encode_qname(name):
    result = b''
    for label in name.rstrip('.').split('.'):
        if label:
            enc = label.encode('ascii')
            result += bytes([len(enc)]) + enc
    result += b'\x00'
    return result


def parse_name(data, offset):
    parts = []
    max_jumps = 15
    jumps = 0
    end_offset = None
    pos = offset
    while pos < len(data):
        length = data[pos]
        if length == 0:
            pos += 1
            break
        elif (length & 0xC0) == 0xC0:
            if jumps >= max_jumps:
                raise ValueError("Too many compression jumps")
            if end_offset is None:
                end_offset = pos + 2
            pointer = ((length & 0x3F) << 8) | data[pos + 1]
            pos = pointer
            jumps += 1
        else:
            pos += 1
            parts.append(data[pos:pos + length].decode('ascii'))
            pos += length
    if end_offset is None:
        end_offset = pos
    return '.'.join(parts).lower() + '.', end_offset


def parse_record(data, offset):
    name, offset = parse_name(data, offset)
    type_, class_, ttl, rdlength = struct.unpack('!HHIH', data[offset:offset + 10])
    offset += 10
    rdata_start = offset

    if type_ == TYPE_A and rdlength == 4:
        rdata = '.'.join(str(b) for b in data[offset:offset + 4])
    elif type_ == TYPE_AAAA and rdlength == 16:
        rdata = str(ipaddress.IPv6Address(data[offset:offset + 16]))
    elif type_ in (TYPE_NS, TYPE_CNAME):
        rdata, _ = parse_name(data, offset)
    elif type_ == TYPE_MX:
        preference = struct.unpack('!H', data[offset:offset + 2])[0]
        exchange, _ = parse_name(data, offset + 2)
        rdata = {'preference': preference, 'exchange': exchange}
    elif type_ == TYPE_TXT:
        texts = []
        pos = offset
        while pos < offset + rdlength:
            tlen = data[pos]
            pos += 1
            texts.append(data[pos:pos + tlen].decode('ascii', errors='replace'))
            pos += tlen
        rdata = ''.join(texts)
    elif type_ == TYPE_SOA:
        mname, pos = parse_name(data, offset)
        rname, pos = parse_name(data, pos)
        serial, refresh, retry, expire, minimum = struct.unpack('!IIIII', data[pos:pos + 20])
        rdata = {
            'mname': mname, 'rname': rname, 'serial': serial,
            'refresh': refresh, 'retry': retry, 'expire': expire, 'minimum': minimum,
        }
    elif type_ == TYPE_OPT:
        rdata = data[offset:offset + rdlength].hex() if rdlength else ''
    else:
        rdata = data[offset:offset + rdlength].hex()

    offset = rdata_start + rdlength
    return {'name': name, 'type': type_, 'class': class_, 'ttl': ttl, 'rdata': rdata}, offset


def parse_response(data):
    qid, flags, qdcount, ancount, nscount, arcount = struct.unpack('!HHHHHH', data[:12])
    offset = 12

    qr = (flags >> 15) & 1
    aa = (flags >> 10) & 1
    tc = (flags >> 9) & 1
    rcode = flags & 0xF

    questions = []
    for _ in range(qdcount):
        qname, offset = parse_name(data, offset)
        qtype, qclass = struct.unpack('!HH', data[offset:offset + 4])
        offset += 4
        questions.append({'name': qname, 'type': qtype, 'class': qclass})

    answers = []
    for _ in range(ancount):
        rec, offset = parse_record(data, offset)
        answers.append(rec)

    authority = []
    for _ in range(nscount):
        rec, offset = parse_record(data, offset)
        authority.append(rec)

    additional = []
    for _ in range(arcount):
        rec, offset = parse_record(data, offset)
        additional.append(rec)

    return {
        'id': qid, 'qr': qr, 'aa': aa, 'tc': tc, 'rcode': rcode,
        'questions': questions, 'answers': answers,
        'authority': authority, 'additional': additional,
    }


def query(name, qtype):
    qid = random.randint(0, 65535)
    flags = 0x0100
    header = struct.pack('!HHHHHH', qid, flags, 1, 0, 0, 0)
    question = encode_qname(name) + struct.pack('!HH', qtype, 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    try:
        sock.sendto(header + question, (SERVER_HOST, SERVER_PORT))
        data, _ = sock.recvfrom(4096)
    finally:
        sock.close()
    return parse_response(data)


def query_edns(name, qtype, udp_size=4096):
    """Send a DNS query with EDNS(0) OPT record."""
    qid = random.randint(0, 65535)
    flags = 0x0100
    header = struct.pack('!HHHHHH', qid, flags, 1, 0, 0, 1)
    question = encode_qname(name) + struct.pack('!HH', qtype, 1)
    opt = b'\x00' + struct.pack('!HHIH', TYPE_OPT, udp_size, 0, 0)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    try:
        sock.sendto(header + question + opt, (SERVER_HOST, SERVER_PORT))
        data, _ = sock.recvfrom(65535)
    finally:
        sock.close()
    return parse_response(data)


def query_tcp(name, qtype):
    """Send a DNS query over TCP with 2-byte length prefix."""
    qid = random.randint(0, 65535)
    flags = 0x0100
    header = struct.pack('!HHHHHH', qid, flags, 1, 0, 0, 0)
    question = encode_qname(name) + struct.pack('!HH', qtype, 1)
    msg = header + question
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((SERVER_HOST, SERVER_PORT))
        sock.sendall(struct.pack('!H', len(msg)) + msg)
        length_data = b''
        while len(length_data) < 2:
            chunk = sock.recv(2 - len(length_data))
            if not chunk:
                raise ConnectionError("Connection closed before length")
            length_data += chunk
        resp_len = struct.unpack('!H', length_data)[0]
        resp_data = b''
        while len(resp_data) < resp_len:
            chunk = sock.recv(resp_len - len(resp_data))
            if not chunk:
                raise ConnectionError("Connection closed before full response")
            resp_data += chunk
    finally:
        sock.close()
    return parse_response(resp_data)


# ── Fixtures ──

@pytest.fixture(scope="session", autouse=True)
def dns_server():
    """Start the DNS server and wait for UDP + TCP readiness."""
    proc = subprocess.Popen(
        ['python3', '/app/dns_server.py'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for UDP
    ready = False
    for _ in range(30):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1)
            probe = struct.pack('!HHHHHH', 0, 0x0100, 1, 0, 0, 0) + \
                    encode_qname('example.com') + struct.pack('!HH', 1, 1)
            sock.sendto(probe, (SERVER_HOST, SERVER_PORT))
            sock.recvfrom(4096)
            sock.close()
            ready = True
            break
        except (socket.timeout, ConnectionRefusedError, OSError):
            try:
                sock.close()
            except Exception:
                pass
            time.sleep(0.5)

    if not ready:
        proc.kill()
        stdout, stderr = proc.communicate()
        pytest.fail(
            f"DNS server UDP not ready within 15s.\n"
            f"stdout: {stdout.decode(errors='replace')}\n"
            f"stderr: {stderr.decode(errors='replace')}"
        )

    # Wait for TCP
    tcp_ready = False
    for _ in range(10):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect((SERVER_HOST, SERVER_PORT))
            sock.close()
            tcp_ready = True
            break
        except (socket.timeout, ConnectionRefusedError, OSError):
            try:
                sock.close()
            except Exception:
                pass
            time.sleep(0.5)

    if not tcp_ready:
        proc.kill()
        stdout, stderr = proc.communicate()
        pytest.fail(
            f"DNS server TCP not ready.\n"
            f"stdout: {stdout.decode(errors='replace')}\n"
            f"stderr: {stderr.decode(errors='replace')}"
        )

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ── Tests: Basic Record Types (example.com zone) ──

class TestBasicRecords:
    def test_a_record(self):
        resp = query('example.com', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert len(a_recs) >= 1
        assert '93.184.216.34' in [r['rdata'] for r in a_recs]

    def test_aaaa_record(self):
        resp = query('example.com', TYPE_AAAA)
        assert resp['rcode'] == 0
        aaaa_recs = [r for r in resp['answers'] if r['type'] == TYPE_AAAA]
        assert len(aaaa_recs) >= 1
        expected = str(ipaddress.IPv6Address('2606:2800:220:1:248:1893:25c8:1946'))
        assert expected in [r['rdata'] for r in aaaa_recs]

    def test_ns_records(self):
        resp = query('example.com', TYPE_NS)
        assert resp['rcode'] == 0
        ns_recs = [r for r in resp['answers'] if r['type'] == TYPE_NS]
        assert len(ns_recs) == 2
        ns_names = sorted([r['rdata'] for r in ns_recs])
        assert 'ns1.example.com.' in ns_names
        assert 'ns2.example.com.' in ns_names

    def test_mx_record(self):
        resp = query('example.com', TYPE_MX)
        assert resp['rcode'] == 0
        mx_recs = [r for r in resp['answers'] if r['type'] == TYPE_MX]
        assert len(mx_recs) >= 1
        assert mx_recs[0]['rdata']['preference'] == 10
        assert mx_recs[0]['rdata']['exchange'] == 'mailserver.example.com.'

    def test_mx_additional_section(self):
        """MX response must include glue A for the mail exchange."""
        resp = query('example.com', TYPE_MX)
        a_adds = [r for r in resp['additional'] if r['type'] == TYPE_A]
        ms_a = [r for r in a_adds if r['name'] == 'mailserver.example.com.']
        assert len(ms_a) >= 1, \
            "Expected A glue for mailserver.example.com in additional section"
        assert ms_a[0]['rdata'] == '10.0.0.10'

    def test_txt_record(self):
        resp = query('info.example.com', TYPE_TXT)
        assert resp['rcode'] == 0
        txt_recs = [r for r in resp['answers'] if r['type'] == TYPE_TXT]
        assert len(txt_recs) >= 1
        assert 'v=spf1' in txt_recs[0]['rdata']

    def test_soa_record(self):
        resp = query('example.com', TYPE_SOA)
        assert resp['rcode'] == 0
        soa_recs = [r for r in resp['answers'] if r['type'] == TYPE_SOA]
        assert len(soa_recs) >= 1
        soa = soa_recs[0]['rdata']
        assert soa['mname'] == 'ns1.example.com.'
        assert soa['serial'] == 2024010101

    def test_subdomain_a_record(self):
        resp = query('ns1.example.com', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '10.0.0.1' in [r['rdata'] for r in a_recs]

    def test_multi_label_subdomain(self):
        """Multi-label subdomain like sub.deep.example.com."""
        resp = query('sub.deep.example.com', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '172.16.0.1' in [r['rdata'] for r in a_recs]


# ── Tests: CNAME Resolution ──

class TestCNAME:
    def test_single_cname(self):
        """www.example.com CNAME -> example.com; both in answer."""
        resp = query('www.example.com', TYPE_A)
        assert resp['rcode'] == 0
        cname_recs = [r for r in resp['answers'] if r['type'] == TYPE_CNAME]
        assert len(cname_recs) >= 1
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert len(a_recs) >= 1
        assert '93.184.216.34' in [r['rdata'] for r in a_recs]

    def test_multi_hop_cname(self):
        """app -> frontend -> www -> A; full chain in answer."""
        resp = query('app.internal.test', TYPE_A)
        assert resp['rcode'] == 0
        cname_recs = [r for r in resp['answers'] if r['type'] == TYPE_CNAME]
        assert len(cname_recs) >= 2
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert len(a_recs) >= 1
        assert '10.1.0.100' in [r['rdata'] for r in a_recs]


# ── Tests: Response Codes ──

class TestResponseCodes:
    def test_nxdomain(self):
        resp = query('nonexistent.example.com', TYPE_A)
        assert resp['rcode'] == 3

    def test_noerror_no_records(self):
        """Name exists (A) but queried type (MX) absent -> NOERROR, empty answer."""
        resp = query('mailserver.example.com', TYPE_MX)
        assert resp['rcode'] == 0
        mx_recs = [r for r in resp['answers'] if r['type'] == TYPE_MX]
        assert len(mx_recs) == 0

    def test_unknown_zone(self):
        resp = query('google.com', TYPE_A)
        assert resp['rcode'] in (3, 5)


# ── Tests: Flags ──

class TestFlags:
    def test_qr_flag(self):
        resp = query('example.com', TYPE_A)
        assert resp['qr'] == 1

    def test_aa_flag(self):
        resp = query('example.com', TYPE_A)
        assert resp['aa'] == 1


# ── Tests: Case Insensitivity ──

class TestCaseInsensitive:
    def test_uppercase(self):
        resp = query('EXAMPLE.COM', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '93.184.216.34' in [r['rdata'] for r in a_recs]

    def test_mixed_case(self):
        resp = query('Www.Example.Com', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '93.184.216.34' in [r['rdata'] for r in a_recs]


# ── Tests: Wildcards ──

class TestWildcard:
    def test_wildcard_match(self):
        resp = query('anything.wild.internal.test', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '10.1.1.0' in [r['rdata'] for r in a_recs]

    def test_wildcard_different_name(self):
        resp = query('other.wild.internal.test', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '10.1.1.0' in [r['rdata'] for r in a_recs]


# ── Tests: Second Zone (internal.test) ──

class TestSecondZone:
    def test_a_record(self):
        resp = query('www.internal.test', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '10.1.0.100' in [r['rdata'] for r in a_recs]

    def test_aaaa_record(self):
        resp = query('db.internal.test', TYPE_AAAA)
        assert resp['rcode'] == 0
        aaaa_recs = [r for r in resp['answers'] if r['type'] == TYPE_AAAA]
        assert len(aaaa_recs) >= 1

    def test_dual_stack(self):
        """db.internal.test has A and AAAA; A query returns only A."""
        resp = query('db.internal.test', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '10.1.0.200' in [r['rdata'] for r in a_recs]
        aaaa_in_answer = [r for r in resp['answers'] if r['type'] == TYPE_AAAA]
        assert len(aaaa_in_answer) == 0


# ── Tests: Third Zone from PCAP (services.lab) ──

class TestPcapZone:
    def test_zone_file_exists(self):
        """The services.lab zone file must be generated from the pcap."""
        assert os.path.exists('/app/zones/services.lab.zone'), \
            "services.lab.zone must exist (extracted from pcap)"

    def test_api_a_record(self):
        resp = query('api.services.lab', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '10.2.0.10' in [r['rdata'] for r in a_recs]

    def test_api_aaaa_record(self):
        resp = query('api.services.lab', TYPE_AAAA)
        assert resp['rcode'] == 0
        aaaa_recs = [r for r in resp['answers'] if r['type'] == TYPE_AAAA]
        expected = str(ipaddress.IPv6Address('fd00:2::10'))
        assert expected in [r['rdata'] for r in aaaa_recs]

    def test_cdn_cname_chain(self):
        """cdn CNAME -> origin, plus origin A record."""
        resp = query('cdn.services.lab', TYPE_A)
        assert resp['rcode'] == 0
        cname_recs = [r for r in resp['answers'] if r['type'] == TYPE_CNAME]
        assert len(cname_recs) >= 1
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '10.2.0.20' in [r['rdata'] for r in a_recs]

    def test_mx_record(self):
        resp = query('services.lab', TYPE_MX)
        assert resp['rcode'] == 0
        mx_recs = [r for r in resp['answers'] if r['type'] == TYPE_MX]
        assert len(mx_recs) >= 1
        assert mx_recs[0]['rdata']['preference'] == 20
        assert mx_recs[0]['rdata']['exchange'] == 'smtp.services.lab.'

    def test_txt_record(self):
        resp = query('services.lab', TYPE_TXT)
        assert resp['rcode'] == 0
        txt_recs = [r for r in resp['answers'] if r['type'] == TYPE_TXT]
        assert len(txt_recs) >= 1
        assert 'v=spf1' in txt_recs[0]['rdata']

    def test_soa_record(self):
        resp = query('services.lab', TYPE_SOA)
        assert resp['rcode'] == 0
        soa_recs = [r for r in resp['answers'] if r['type'] == TYPE_SOA]
        assert len(soa_recs) >= 1
        assert soa_recs[0]['rdata']['serial'] == 2024020101

    def test_ns_record(self):
        resp = query('services.lab', TYPE_NS)
        assert resp['rcode'] == 0
        ns_recs = [r for r in resp['answers'] if r['type'] == TYPE_NS]
        assert len(ns_recs) >= 1
        assert 'ns1.services.lab.' in [r['rdata'] for r in ns_recs]

    def test_wildcard(self):
        """Wildcard *.apps.services.lab must match arbitrary subdomains."""
        resp = query('xyz.apps.services.lab', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '10.2.1.0' in [r['rdata'] for r in a_recs]


# ── Tests: EDNS(0) ──

class TestEDNS:
    def test_opt_in_response(self):
        """EDNS(0) query must get OPT in response additional section."""
        resp = query_edns('example.com', TYPE_A, udp_size=4096)
        assert resp['rcode'] == 0
        opt_recs = [r for r in resp['additional'] if r['type'] == TYPE_OPT]
        assert len(opt_recs) >= 1, "Expected OPT record in additional section"

    def test_server_payload_size(self):
        """Server OPT must advertise 4096-byte UDP payload."""
        resp = query_edns('example.com', TYPE_A, udp_size=4096)
        opt_recs = [r for r in resp['additional'] if r['type'] == TYPE_OPT]
        assert len(opt_recs) >= 1
        assert opt_recs[0]['class'] == 4096, \
            f"Expected server UDP payload 4096, got {opt_recs[0]['class']}"

    def test_tc_on_small_buffer(self):
        """Tiny UDP buffer must trigger TC flag."""
        resp = query_edns('example.com', TYPE_NS, udp_size=50)
        assert resp['tc'] == 1, "Expected TC=1 when response exceeds client buffer"

    def test_no_opt_without_edns(self):
        """Non-EDNS query must not get OPT in response."""
        resp = query('example.com', TYPE_A)
        opt_recs = [r for r in resp['additional'] if r['type'] == TYPE_OPT]
        assert len(opt_recs) == 0, "Should not include OPT without EDNS query"


# ── Tests: TCP ──

class TestTCP:
    def test_tcp_a_record(self):
        """TCP query must return correct A record without truncation."""
        resp = query_tcp('example.com', TYPE_A)
        assert resp['rcode'] == 0
        assert resp['tc'] == 0, "TCP responses must not be truncated"
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '93.184.216.34' in [r['rdata'] for r in a_recs]

    def test_tcp_full_response(self):
        """TCP must return full response even for large replies."""
        resp = query_tcp('example.com', TYPE_NS)
        assert resp['rcode'] == 0
        assert resp['tc'] == 0
        ns_recs = [r for r in resp['answers'] if r['type'] == TYPE_NS]
        assert len(ns_recs) == 2

    def test_tcp_pcap_zone(self):
        """TCP query to pcap-derived zone must work."""
        resp = query_tcp('api.services.lab', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert '10.2.0.10' in [r['rdata'] for r in a_recs]
