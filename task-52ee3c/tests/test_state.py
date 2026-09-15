
import socket
import struct
import subprocess
import time
import os
import signal
import json
import pytest

SERVER_PORT = 5300
SERVER_HOST = '127.0.0.1'

TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_SRV = 33

CLASS_IN = 1


def encode_name(name):
    """Encode a DNS name into wire format without compression."""
    result = b''
    for label in name.rstrip('.').split('.'):
        encoded = label.encode('ascii')
        result += bytes([len(encoded)]) + encoded
    result += b'\x00'
    return result


def decode_name(data, offset):
    """Decode a DNS name from wire format, handling compression pointers."""
    labels = []
    visited = set()
    final_offset = None

    while True:
        if offset >= len(data):
            break
        if offset in visited:
            raise ValueError("Compression pointer loop detected")
        visited.add(offset)

        length = data[offset]
        if length == 0:
            if final_offset is None:
                final_offset = offset + 1
            break
        elif (length & 0xC0) == 0xC0:
            pointer = struct.unpack('!H', data[offset:offset + 2])[0] & 0x3FFF
            if final_offset is None:
                final_offset = offset + 2
            offset = pointer
        else:
            offset += 1
            labels.append(data[offset:offset + length].decode('ascii'))
            offset += length

    return '.'.join(labels) + '.', final_offset or offset


def build_query(name, qtype, qclass=CLASS_IN):
    """Build a DNS query packet."""
    txn_id = 0x1234
    flags = 0x0100  # RD=1
    header = struct.pack('!HHHHHH', txn_id, flags, 1, 0, 0, 0)
    question = encode_name(name) + struct.pack('!HH', qtype, qclass)
    return header + question


def parse_response(data):
    """Parse a DNS response packet into its components."""
    txn_id, flags, qdcount, ancount, nscount, arcount = struct.unpack(
        '!HHHHHH', data[:12]
    )

    qr = (flags >> 15) & 1
    aa = (flags >> 10) & 1
    tc = (flags >> 9) & 1
    rd = (flags >> 8) & 1
    ra = (flags >> 7) & 1
    rcode = flags & 0xF

    offset = 12

    questions = []
    for _ in range(qdcount):
        name, offset = decode_name(data, offset)
        qtype, qclass = struct.unpack('!HH', data[offset:offset + 4])
        offset += 4
        questions.append((name, qtype, qclass))

    def parse_rrs(count):
        nonlocal offset
        rrs = []
        for _ in range(count):
            name, offset = decode_name(data, offset)
            rtype, rclass, ttl, rdlength = struct.unpack(
                '!HHIH', data[offset:offset + 10]
            )
            offset += 10
            rdata_start = offset
            rdata = data[offset:offset + rdlength]
            offset += rdlength
            rrs.append({
                'name': name,
                'type': rtype,
                'class': rclass,
                'ttl': ttl,
                'rdata': rdata,
                'rdata_offset': rdata_start,
            })
        return rrs

    answers = parse_rrs(ancount)
    authority = parse_rrs(nscount)
    additional = parse_rrs(arcount)

    return {
        'id': txn_id,
        'qr': qr,
        'aa': aa,
        'tc': tc,
        'rcode': rcode,
        'questions': questions,
        'answers': answers,
        'authority': authority,
        'additional': additional,
        'raw': data,
    }


def parse_a_rdata(rdata):
    """Parse A record RDATA to dotted-quad string."""
    return '.'.join(str(b) for b in rdata)


def parse_aaaa_rdata(rdata):
    """Parse AAAA record RDATA to IPv6 string."""
    import ipaddress
    return str(ipaddress.IPv6Address(rdata))


def parse_name_rdata(data, rdata_offset):
    """Parse RDATA that is a single DNS name (NS, CNAME)."""
    name, _ = decode_name(data, rdata_offset)
    return name


def parse_mx_rdata(data, rdata_offset):
    """Parse MX RDATA: preference + exchange name."""
    preference = struct.unpack('!H', data[rdata_offset:rdata_offset + 2])[0]
    name, _ = decode_name(data, rdata_offset + 2)
    return preference, name


def parse_soa_rdata(data, rdata_offset):
    """Parse SOA RDATA fields."""
    mname, offset = decode_name(data, rdata_offset)
    rname, offset = decode_name(data, offset)
    serial, refresh, retry, expire, minimum = struct.unpack(
        '!IIIII', data[offset:offset + 20]
    )
    return {
        'mname': mname,
        'rname': rname,
        'serial': serial,
        'refresh': refresh,
        'retry': retry,
        'expire': expire,
        'minimum': minimum,
    }


def parse_txt_rdata(rdata):
    """Parse TXT RDATA: sequence of length-prefixed strings."""
    strings = []
    offset = 0
    while offset < len(rdata):
        length = rdata[offset]
        offset += 1
        strings.append(rdata[offset:offset + length].decode('ascii'))
        offset += length
    return strings


def dns_query(name, qtype):
    """Send a DNS query via UDP and return parsed response."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    try:
        q = build_query(name, qtype)
        sock.sendto(q, (SERVER_HOST, SERVER_PORT))
        data, _ = sock.recvfrom(4096)
        return parse_response(data)
    finally:
        sock.close()


def recv_all(sock, n):
    """Receive exactly n bytes from a TCP socket."""
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return data
        data += chunk
    return data


def dns_query_tcp(name, qtype):
    """Send a DNS query via TCP (with 2-byte length prefix) and return parsed response."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((SERVER_HOST, SERVER_PORT))
        q = build_query(name, qtype)
        sock.sendall(struct.pack('!H', len(q)) + q)

        length_data = recv_all(sock, 2)
        assert len(length_data) == 2, "Failed to read TCP response length prefix"
        resp_len = struct.unpack('!H', length_data)[0]

        data = recv_all(sock, resp_len)
        assert len(data) == resp_len, f"Short TCP response: got {len(data)}, expected {resp_len}"
        return parse_response(data)
    finally:
        sock.close()


@pytest.fixture(scope="session", autouse=True)
def start_server():
    """Start the DNS server before tests and stop it after."""
    proc = subprocess.Popen(
        ['/bin/bash', '/app/start.sh'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )
    # Wait for server to accept UDP queries
    for attempt in range(50):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1)
            sock.sendto(
                build_query('example.test.', TYPE_SOA),
                (SERVER_HOST, SERVER_PORT),
            )
            sock.recvfrom(4096)
            sock.close()
            break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError("DNS server did not start within 10 seconds")

    # Wait for TCP listener to be ready
    for attempt in range(25):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect((SERVER_HOST, SERVER_PORT))
            sock.close()
            break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError("DNS TCP listener did not start within 5 seconds")

    yield

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired, ChildProcessError):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, ChildProcessError):
            pass


class TestDNSServer:
    """Tests for DNS authoritative server conformance."""

    # ---- Core UDP tests (existing) ----

    def test_a_record(self):
        """Query A record for zone apex."""
        resp = dns_query('example.test.', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert len(a_recs) == 1
        assert parse_a_rdata(a_recs[0]['rdata']) == '192.0.2.1'

    def test_aaaa_record(self):
        """Query AAAA record for zone apex."""
        resp = dns_query('example.test.', TYPE_AAAA)
        assert resp['rcode'] == 0
        aaaa_recs = [r for r in resp['answers'] if r['type'] == TYPE_AAAA]
        assert len(aaaa_recs) == 1
        assert parse_aaaa_rdata(aaaa_recs[0]['rdata']) == '2001:db8::1'

    def test_cname_chase(self):
        """Query A for a CNAME should return CNAME + target A record."""
        resp = dns_query('www.example.test.', TYPE_A)
        assert resp['rcode'] == 0
        cname_recs = [r for r in resp['answers'] if r['type'] == TYPE_CNAME]
        assert len(cname_recs) == 1
        target = parse_name_rdata(resp['raw'], cname_recs[0]['rdata_offset'])
        assert target.lower() == 'example.test.'
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert len(a_recs) >= 1
        assert parse_a_rdata(a_recs[0]['rdata']) == '192.0.2.1'

    def test_mx_with_additional(self):
        """Query MX should return MX records with glue A in additional."""
        resp = dns_query('example.test.', TYPE_MX)
        assert resp['rcode'] == 0
        mx_recs = [r for r in resp['answers'] if r['type'] == TYPE_MX]
        assert len(mx_recs) == 2

        mx_data = []
        for mx in mx_recs:
            pref, name = parse_mx_rdata(resp['raw'], mx['rdata_offset'])
            mx_data.append((pref, name.lower()))
        mx_data.sort()

        assert mx_data[0] == (10, 'mail.example.test.')
        assert mx_data[1] == (20, 'backup-mail.example.test.')

        add_a = [r for r in resp['additional'] if r['type'] == TYPE_A]
        add_names = {r['name'].lower() for r in add_a}
        assert 'mail.example.test.' in add_names
        assert 'backup-mail.example.test.' in add_names

    def test_txt_record(self):
        """Query TXT record for zone apex."""
        resp = dns_query('example.test.', TYPE_TXT)
        assert resp['rcode'] == 0
        txt_recs = [r for r in resp['answers'] if r['type'] == TYPE_TXT]
        assert len(txt_recs) == 1
        strings = parse_txt_rdata(txt_recs[0]['rdata'])
        assert 'v=spf1 include:example.test ~all' in strings

    def test_soa_record(self):
        """Query SOA record for zone apex."""
        resp = dns_query('example.test.', TYPE_SOA)
        assert resp['rcode'] == 0
        soa_recs = [r for r in resp['answers'] if r['type'] == TYPE_SOA]
        assert len(soa_recs) == 1
        soa = parse_soa_rdata(resp['raw'], soa_recs[0]['rdata_offset'])
        assert soa['serial'] == 2024010101
        assert soa['mname'].lower() == 'ns1.example.test.'
        assert soa['rname'].lower() == 'admin.example.test.'

    def test_ns_with_glue(self):
        """Query NS should return NS records with glue A in additional."""
        resp = dns_query('example.test.', TYPE_NS)
        assert resp['rcode'] == 0
        ns_recs = [r for r in resp['answers'] if r['type'] == TYPE_NS]
        assert len(ns_recs) == 2

        ns_names = set()
        for ns in ns_recs:
            name = parse_name_rdata(resp['raw'], ns['rdata_offset'])
            ns_names.add(name.lower())
        assert 'ns1.example.test.' in ns_names
        assert 'ns2.example.test.' in ns_names

        add_a = [r for r in resp['additional'] if r['type'] == TYPE_A]
        add_names = {r['name'].lower() for r in add_a}
        assert 'ns1.example.test.' in add_names
        assert 'ns2.example.test.' in add_names

    def test_nxdomain(self):
        """Non-existent name should return NXDOMAIN with SOA in authority."""
        resp = dns_query('nonexistent.example.test.', TYPE_A)
        assert resp['rcode'] == 3  # NXDOMAIN
        assert len(resp['answers']) == 0
        soa_recs = [r for r in resp['authority'] if r['type'] == TYPE_SOA]
        assert len(soa_recs) == 1

    def test_nodata(self):
        """Existing name with no matching type should return NODATA."""
        resp = dns_query('example.test.', TYPE_SRV)
        assert resp['rcode'] == 0  # NOERROR
        assert len(resp['answers']) == 0
        soa_recs = [r for r in resp['authority'] if r['type'] == TYPE_SOA]
        assert len(soa_recs) == 1

    def test_wildcard_match(self):
        """Wildcard should match non-existent names under wildcard parent."""
        resp = dns_query('foo.wild.example.test.', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert len(a_recs) == 1
        assert parse_a_rdata(a_recs[0]['rdata']) == '192.0.2.200'
        # Owner name must be the queried name, not the wildcard
        assert a_recs[0]['name'].lower() == 'foo.wild.example.test.'

    def test_wildcard_override(self):
        """Explicit record should take precedence over wildcard."""
        resp = dns_query('deep.wild.example.test.', TYPE_A)
        assert resp['rcode'] == 0
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert len(a_recs) == 1
        assert parse_a_rdata(a_recs[0]['rdata']) == '192.0.2.201'

    def test_aa_flag_set(self):
        """Authoritative responses must have AA flag set."""
        resp = dns_query('example.test.', TYPE_A)
        assert resp['aa'] == 1, "AA flag must be set for authoritative response"

    def test_qr_flag_set(self):
        """All responses must have QR flag set."""
        resp = dns_query('example.test.', TYPE_A)
        assert resp['qr'] == 1, "QR flag must be set in response"

    def test_compression_used(self):
        """Response must use DNS name compression pointers."""
        resp = dns_query('example.test.', TYPE_NS)
        data = resp['raw']
        assert len(data) > 31, "Response too short to contain answer records"
        first_byte = data[30]
        assert (first_byte & 0xC0) == 0xC0, (
            f"Expected compression pointer at first answer RR owner name "
            f"(byte 30 = {first_byte:#x}), compression not detected"
        )

    def test_delegation(self):
        """Query below delegated subzone should return referral."""
        resp = dns_query('foo.sub.example.test.', TYPE_A)
        assert resp['aa'] == 0, "AA must not be set for delegation referral"
        assert len(resp['answers']) == 0
        ns_recs = [r for r in resp['authority'] if r['type'] == TYPE_NS]
        assert len(ns_recs) >= 1
        ns_name = parse_name_rdata(resp['raw'], ns_recs[0]['rdata_offset'])
        assert ns_name.lower() == 'ns1.sub.example.test.'
        add_a = [r for r in resp['additional'] if r['type'] == TYPE_A]
        assert len(add_a) >= 1
        assert parse_a_rdata(add_a[0]['rdata']) == '192.0.2.100'

    # ---- TCP DNS tests ----

    def test_tcp_a_record(self):
        """TCP query for A record must return correct response with length framing."""
        resp = dns_query_tcp('example.test.', TYPE_A)
        assert resp['rcode'] == 0
        assert resp['qr'] == 1
        assert resp['aa'] == 1
        a_recs = [r for r in resp['answers'] if r['type'] == TYPE_A]
        assert len(a_recs) == 1
        assert parse_a_rdata(a_recs[0]['rdata']) == '192.0.2.1'

    def test_tcp_mx_with_additional(self):
        """TCP query for MX must return MX records with glue in additional."""
        resp = dns_query_tcp('example.test.', TYPE_MX)
        assert resp['rcode'] == 0
        mx_recs = [r for r in resp['answers'] if r['type'] == TYPE_MX]
        assert len(mx_recs) == 2

        mx_data = []
        for mx in mx_recs:
            pref, name = parse_mx_rdata(resp['raw'], mx['rdata_offset'])
            mx_data.append((pref, name.lower()))
        mx_data.sort()
        assert mx_data[0] == (10, 'mail.example.test.')
        assert mx_data[1] == (20, 'backup-mail.example.test.')

        add_a = [r for r in resp['additional'] if r['type'] == TYPE_A]
        add_names = {r['name'].lower() for r in add_a}
        assert 'mail.example.test.' in add_names

    def test_tcp_nxdomain(self):
        """TCP query for non-existent name must return NXDOMAIN."""
        resp = dns_query_tcp('nonexistent.example.test.', TYPE_A)
        assert resp['rcode'] == 3
        assert len(resp['answers']) == 0
        soa_recs = [r for r in resp['authority'] if r['type'] == TYPE_SOA]
        assert len(soa_recs) == 1

    # ---- Tool integration tests ----

    def test_zone_checkzone_validation(self):
        """Zone file must pass named-checkzone validation."""
        result = subprocess.run(
            ['named-checkzone', 'example.test', '/app/zones/example.test.zone'],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"named-checkzone failed with exit code {result.returncode}: {result.stderr}"
        )

    def test_json_log_format(self):
        """Query log must be NDJSON with required fields."""
        # Send a distinctive query to generate a log entry
        dns_query('mail.example.test.', TYPE_A)
        time.sleep(0.5)

        log_path = '/app/dns_query.log'
        assert os.path.exists(log_path), "Query log file /app/dns_query.log not found"

        with open(log_path, 'r') as f:
            lines = [l.strip() for l in f if l.strip()]

        assert len(lines) > 0, "Query log is empty after sending queries"

        required_fields = {'ts', 'client', 'qname', 'qtype', 'rcode', 'answers'}
        for line in lines:
            entry = json.loads(line)
            missing = required_fields - set(entry.keys())
            assert not missing, f"Log entry missing fields {missing}: {line}"
            assert isinstance(entry['qtype'], int), f"qtype must be int: {entry['qtype']}"
            assert isinstance(entry['rcode'], int), f"rcode must be int: {entry['rcode']}"
            assert isinstance(entry['answers'], int), f"answers must be int: {entry['answers']}"

    def test_json_log_content(self):
        """Query log must record queries with correct field values."""
        # Send a query for a known record
        dns_query('ns1.example.test.', TYPE_A)
        time.sleep(0.5)

        with open('/app/dns_query.log', 'r') as f:
            lines = [l.strip() for l in f if l.strip()]

        # Find an entry for our specific query
        found = False
        for line in lines:
            entry = json.loads(line)
            if entry.get('qname', '').lower().rstrip('.') == 'ns1.example.test':
                assert entry['qtype'] == TYPE_A
                assert entry['rcode'] == 0
                assert entry['answers'] >= 1
                assert entry['client'] in ('127.0.0.1', '::1')
                assert 'T' in entry['ts']  # ISO 8601 contains T separator
                found = True
                break
        assert found, "No log entry found for ns1.example.test A query"
