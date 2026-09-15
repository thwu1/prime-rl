
import pytest
import subprocess
import socket
import struct
import time
import os
import signal

# DNS record type constants
TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_SRV = 33
TYPE_OPT = 41

PORT = 5353
QUERY_ID = 0xABCD


@pytest.fixture(scope="session", autouse=True)
def dns_server():
    """Start the DNS server and wait for it to accept queries."""
    proc = subprocess.Popen(
        ["python3", "/app/dns_server.py"],
        cwd="/app",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    ready = False
    for _ in range(100):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.5)
            query = _build_query("bench.example", TYPE_A)
            sock.sendto(query, ("127.0.0.1", PORT))
            sock.recvfrom(4096)
            sock.close()
            ready = True
            break
        except Exception:
            time.sleep(0.1)

    if not ready:
        proc.kill()
        stdout, stderr = proc.communicate()
        pytest.fail(
            f"DNS server failed to start.\nstdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )

    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# Wire-format helpers
# ---------------------------------------------------------------------------

def _encode_name(name):
    """Encode a domain name into DNS label format."""
    result = b""
    for label in name.split("."):
        enc = label.encode("ascii")
        result += bytes([len(enc)]) + enc
    result += b"\x00"
    return result


def _decode_name(data, offset):
    """Decode a DNS name handling compression pointers."""
    labels = []
    visited = set()
    end_offset = None
    while True:
        if offset >= len(data) or offset in visited:
            break
        visited.add(offset)
        length = data[offset]
        if length == 0:
            if end_offset is None:
                end_offset = offset + 1
            break
        if (length & 0xC0) == 0xC0:
            if end_offset is None:
                end_offset = offset + 2
            ptr = struct.unpack("!H", data[offset : offset + 2])[0] & 0x3FFF
            offset = ptr
        else:
            offset += 1
            labels.append(data[offset : offset + length].decode("ascii"))
            offset += length
    return ".".join(labels).lower(), end_offset


def _build_query(name, qtype, edns=False):
    """Construct a raw DNS query packet."""
    flags = 0x0100  # RD=1
    arcount = 1 if edns else 0
    header = struct.pack("!HHHHHH", QUERY_ID, flags, 1, 0, 0, arcount)
    question = _encode_name(name) + struct.pack("!HH", qtype, 1)
    packet = header + question
    if edns:
        # OPT pseudo-record: root name, type=41, udp=4096, ext-rcode=0, rdlen=0
        opt = b"\x00" + struct.pack("!HHIH", TYPE_OPT, 4096, 0, 0)
        packet += opt
    return packet


def _parse_rr(data, offset):
    """Parse a single resource record from wire data."""
    name, offset = _decode_name(data, offset)
    rtype, rclass, ttl, rdlength = struct.unpack("!HHIH", data[offset : offset + 10])
    rdata_start = offset + 10
    rdata_raw = data[rdata_start : rdata_start + rdlength]
    offset = rdata_start + rdlength

    rdata = rdata_raw
    if rtype == TYPE_A and rdlength == 4:
        rdata = socket.inet_ntoa(rdata_raw)
    elif rtype == TYPE_AAAA and rdlength == 16:
        rdata = socket.inet_ntop(socket.AF_INET6, rdata_raw)
    elif rtype in (TYPE_CNAME, TYPE_NS):
        rdata, _ = _decode_name(data, rdata_start)
    elif rtype == TYPE_MX:
        pref = struct.unpack("!H", rdata_raw[:2])[0]
        target, _ = _decode_name(data, rdata_start + 2)
        rdata = {"priority": pref, "target": target}
    elif rtype == TYPE_TXT:
        strings = []
        i = 0
        while i < rdlength:
            slen = rdata_raw[i]
            strings.append(rdata_raw[i + 1 : i + 1 + slen].decode("utf-8"))
            i += 1 + slen
        rdata = strings
    elif rtype == TYPE_SOA:
        mname, pos = _decode_name(data, rdata_start)
        rname, pos = _decode_name(data, pos)
        serial, refresh, retry, expire, minimum = struct.unpack(
            "!IIIII", data[pos : pos + 20]
        )
        rdata = {
            "mname": mname,
            "rname": rname,
            "serial": serial,
            "refresh": refresh,
            "retry": retry,
            "expire": expire,
            "minimum": minimum,
        }
    elif rtype == TYPE_SRV:
        priority, weight, port = struct.unpack("!HHH", rdata_raw[:6])
        target, _ = _decode_name(data, rdata_start + 6)
        rdata = {
            "priority": priority,
            "weight": weight,
            "port": port,
            "target": target,
        }

    return {
        "name": name,
        "type": rtype,
        "class": rclass,
        "ttl": ttl,
        "rdata": rdata,
    }, offset


def _parse_response(data):
    """Parse a full DNS response packet."""
    header = struct.unpack("!HHHHHH", data[:12])
    result = {
        "id": header[0],
        "flags": header[1],
        "qr": (header[1] >> 15) & 1,
        "aa": (header[1] >> 10) & 1,
        "rd": (header[1] >> 8) & 1,
        "rcode": header[1] & 0xF,
        "qdcount": header[2],
        "ancount": header[3],
        "nscount": header[4],
        "arcount": header[5],
        "answers": [],
        "authority": [],
        "additional": [],
    }
    offset = 12
    for _ in range(result["qdcount"]):
        _, offset = _decode_name(data, offset)
        offset += 4
    for section, count in [
        ("answers", result["ancount"]),
        ("authority", result["nscount"]),
        ("additional", result["arcount"]),
    ]:
        for _ in range(count):
            rr, offset = _parse_rr(data, offset)
            result[section].append(rr)
    return result


def _query(name, qtype, edns=False):
    """Send a DNS query and return the parsed response."""
    pkt = _build_query(name, qtype, edns)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    sock.sendto(pkt, ("127.0.0.1", PORT))
    data, _ = sock.recvfrom(4096)
    sock.close()
    return _parse_response(data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_server_responds():
    """Basic connectivity: server returns a response with matching ID."""
    resp = _query("bench.example", TYPE_A)
    assert resp["qr"] == 1, "QR bit must be 1 in a response"
    assert resp["id"] == QUERY_ID, "Response ID must match query ID"


def test_a_record_single():
    """Single A record for www.bench.example."""
    resp = _query("www.bench.example", TYPE_A)
    assert resp["rcode"] == 0
    a_recs = [r for r in resp["answers"] if r["type"] == TYPE_A]
    ips = {r["rdata"] for r in a_recs}
    assert "192.0.2.10" in ips


def test_a_record_multiple():
    """Two A records for the zone apex."""
    resp = _query("bench.example", TYPE_A)
    assert resp["rcode"] == 0
    a_recs = [r for r in resp["answers"] if r["type"] == TYPE_A]
    ips = {r["rdata"] for r in a_recs}
    assert "192.0.2.1" in ips
    assert "192.0.2.2" in ips
    assert len(a_recs) == 2


def test_aaaa_record():
    """AAAA record for www.bench.example."""
    resp = _query("www.bench.example", TYPE_AAAA)
    assert resp["rcode"] == 0
    aaaa_recs = [r for r in resp["answers"] if r["type"] == TYPE_AAAA]
    assert len(aaaa_recs) >= 1
    ips = {r["rdata"] for r in aaaa_recs}
    assert any("2001:db8" in ip and ip.endswith("10") for ip in ips), (
        f"Expected 2001:db8::10, got {ips}"
    )


def test_cname_single():
    """cdn is a CNAME to www; querying A should return CNAME + A."""
    resp = _query("cdn.bench.example", TYPE_A)
    assert resp["rcode"] == 0
    cnames = [r for r in resp["answers"] if r["type"] == TYPE_CNAME]
    a_recs = [r for r in resp["answers"] if r["type"] == TYPE_A]
    assert len(cnames) >= 1, "Must include CNAME record"
    assert len(a_recs) >= 1, "Must follow CNAME chain to A record"
    assert cnames[0]["rdata"] == "www.bench.example"
    assert a_recs[0]["rdata"] == "192.0.2.10"


def test_cname_chain():
    """blog -> cdn -> www chain; querying A should return 2 CNAMEs + A."""
    resp = _query("blog.bench.example", TYPE_A)
    assert resp["rcode"] == 0
    cnames = [r for r in resp["answers"] if r["type"] == TYPE_CNAME]
    a_recs = [r for r in resp["answers"] if r["type"] == TYPE_A]
    assert len(cnames) >= 2, "Must include both CNAME hops"
    assert len(a_recs) >= 1, "Must follow chain to final A"
    assert a_recs[0]["rdata"] == "192.0.2.10"


def test_mx_records():
    """Two MX records for the apex with correct priorities."""
    resp = _query("bench.example", TYPE_MX)
    assert resp["rcode"] == 0
    mx_recs = [r for r in resp["answers"] if r["type"] == TYPE_MX]
    assert len(mx_recs) == 2
    by_prio = sorted(
        [(r["rdata"]["priority"], r["rdata"]["target"]) for r in mx_recs]
    )
    assert by_prio[0] == (10, "mail.bench.example")
    assert by_prio[1] == (20, "mail2.bench.example")


def test_txt_record_apex():
    """SPF TXT record on the zone apex."""
    resp = _query("bench.example", TYPE_TXT)
    assert resp["rcode"] == 0
    txt_recs = [r for r in resp["answers"] if r["type"] == TYPE_TXT]
    assert len(txt_recs) >= 1
    all_strings = []
    for r in txt_recs:
        all_strings.extend(r["rdata"])
    assert any("v=spf1" in s for s in all_strings), (
        f"Expected SPF TXT, got {all_strings}"
    )


def test_txt_record_dmarc():
    """DMARC TXT record on _dmarc subdomain."""
    resp = _query("_dmarc.bench.example", TYPE_TXT)
    assert resp["rcode"] == 0
    txt_recs = [r for r in resp["answers"] if r["type"] == TYPE_TXT]
    assert len(txt_recs) >= 1
    all_strings = []
    for r in txt_recs:
        all_strings.extend(r["rdata"])
    assert any("DMARC1" in s for s in all_strings)


def test_srv_record():
    """SRV record for _sip._tcp.bench.example."""
    resp = _query("_sip._tcp.bench.example", TYPE_SRV)
    assert resp["rcode"] == 0
    srv_recs = [r for r in resp["answers"] if r["type"] == TYPE_SRV]
    assert len(srv_recs) >= 1
    srv = srv_recs[0]["rdata"]
    assert srv["priority"] == 10
    assert srv["weight"] == 60
    assert srv["port"] == 5060
    assert srv["target"] == "sip.bench.example"


def test_soa_record():
    """SOA record for the zone apex."""
    resp = _query("bench.example", TYPE_SOA)
    assert resp["rcode"] == 0
    soa_recs = [r for r in resp["answers"] if r["type"] == TYPE_SOA]
    assert len(soa_recs) == 1
    soa = soa_recs[0]["rdata"]
    assert soa["mname"] == "ns1.bench.example"
    assert soa["rname"] == "admin.bench.example"
    assert soa["serial"] == 2024010101


def test_ns_records():
    """NS records for the zone apex."""
    resp = _query("bench.example", TYPE_NS)
    assert resp["rcode"] == 0
    ns_recs = [r for r in resp["answers"] if r["type"] == TYPE_NS]
    assert len(ns_recs) == 2
    targets = {r["rdata"] for r in ns_recs}
    assert "ns1.bench.example" in targets
    assert "ns2.bench.example" in targets


def test_nxdomain():
    """NXDOMAIN for a name not covered by any record or wildcard."""
    resp = _query("nonexistent.deep.bench.example", TYPE_A)
    assert resp["rcode"] == 3, f"Expected NXDOMAIN (3), got {resp['rcode']}"


def test_nodata():
    """NODATA: name exists (mail has A) but queried type (MX) does not."""
    resp = _query("mail.bench.example", TYPE_MX)
    assert resp["rcode"] == 0, "Should be NOERROR for NODATA"
    mx_recs = [r for r in resp["answers"] if r["type"] == TYPE_MX]
    assert len(mx_recs) == 0, "Should have zero MX answers"


def test_wildcard_match():
    """Wildcard *.bench.example matches a non-existent single-label child."""
    resp = _query("randomhost.bench.example", TYPE_A)
    assert resp["rcode"] == 0, "Wildcard should produce NOERROR"
    a_recs = [r for r in resp["answers"] if r["type"] == TYPE_A]
    assert len(a_recs) >= 1
    assert a_recs[0]["rdata"] == "192.0.2.100"


def test_wildcard_override():
    """Explicit record 'specific' overrides the wildcard."""
    resp = _query("specific.bench.example", TYPE_A)
    assert resp["rcode"] == 0
    a_recs = [r for r in resp["answers"] if r["type"] == TYPE_A]
    assert len(a_recs) >= 1
    assert a_recs[0]["rdata"] == "192.0.2.200", (
        f"Explicit record should override wildcard; got {a_recs[0]['rdata']}"
    )


def test_case_insensitive():
    """Domain name matching must be case-insensitive."""
    resp = _query("WWW.BENCH.EXAMPLE", TYPE_A)
    assert resp["rcode"] == 0
    a_recs = [r for r in resp["answers"] if r["type"] == TYPE_A]
    assert len(a_recs) >= 1
    assert a_recs[0]["rdata"] == "192.0.2.10"


def test_authoritative_flag():
    """AA (authoritative answer) flag must be set."""
    resp = _query("bench.example", TYPE_A)
    assert resp["aa"] == 1, "AA flag must be set for authoritative server"


def test_edns0_opt():
    """EDNS0: server echoes OPT record when query includes one."""
    resp = _query("bench.example", TYPE_A, edns=True)
    assert resp["rcode"] == 0
    opt_recs = [r for r in resp["additional"] if r["type"] == TYPE_OPT]
    assert len(opt_recs) >= 1, "Must echo OPT record for EDNS0 support"


def test_nxdomain_authority_soa():
    """NXDOMAIN must include SOA in authority section (RFC 2308)."""
    resp = _query("nonexistent.deep.bench.example", TYPE_A)
    assert resp["rcode"] == 3, f"Expected NXDOMAIN (3), got {resp['rcode']}"
    soa_recs = [r for r in resp["authority"] if r["type"] == TYPE_SOA]
    assert len(soa_recs) >= 1, "NXDOMAIN must include SOA in authority section"
    assert soa_recs[0]["rdata"]["mname"] == "ns1.bench.example"
    assert soa_recs[0]["rdata"]["serial"] == 2024010101


def test_nodata_authority_soa():
    """NODATA must include SOA in authority section (RFC 2308)."""
    resp = _query("mail.bench.example", TYPE_MX)
    assert resp["rcode"] == 0, "Should be NOERROR for NODATA"
    mx_recs = [r for r in resp["answers"] if r["type"] == TYPE_MX]
    assert len(mx_recs) == 0, "Should have zero MX answers"
    soa_recs = [r for r in resp["authority"] if r["type"] == TYPE_SOA]
    assert len(soa_recs) >= 1, "NODATA must include SOA in authority section"
    assert soa_recs[0]["rdata"]["mname"] == "ns1.bench.example"


def test_mx_glue_additional():
    """MX response should include A glue records in additional section."""
    resp = _query("bench.example", TYPE_MX)
    assert resp["rcode"] == 0
    a_recs = [r for r in resp["additional"] if r["type"] == TYPE_A]
    ips = {r["rdata"] for r in a_recs}
    assert "192.0.2.20" in ips, "Must include glue A record for mail.bench.example"
    assert "192.0.2.21" in ips, "Must include glue A record for mail2.bench.example"
