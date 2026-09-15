
"""Tests for DNS authoritative server protocol compliance and audit report."""

import pytest
import subprocess
import time
import json
import os
import dns.message
import dns.query
import dns.rdatatype
import dns.rcode
import dns.flags

SERVER = "127.0.0.1"
PORT = 1053
TIMEOUT = 5


@pytest.fixture(scope="module", autouse=True)
def dns_server():
    """Start the DNS server before tests and stop it after."""
    proc = subprocess.Popen(
        [
            "python3",
            "/app/dns_server.py",
            "--zone",
            "/app/zones/example.com.zone",
            "--port",
            str(PORT),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for attempt in range(30):
        try:
            q = dns.message.make_query("example.com.", "SOA", use_edns=-1)
            r = dns.query.udp(q, SERVER, port=PORT, timeout=2)
            if r.rcode() == dns.rcode.NOERROR:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("DNS server did not start within 15 seconds")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def query(name, rdtype, use_edns=-1):
    """Send a DNS query to the test server."""
    q = dns.message.make_query(name, rdtype, use_edns=use_edns)
    return dns.query.udp(q, SERVER, port=PORT, timeout=TIMEOUT)


def test_a_record_apex():
    """Query A record for zone apex."""
    r = query("example.com.", "A")
    assert r.rcode() == dns.rcode.NOERROR
    a_records = [rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.A]
    addresses = [rr.address for rr in a_records]
    assert "192.0.2.1" in addresses


def test_aaaa_record_apex():
    """Query AAAA record for zone apex."""
    r = query("example.com.", "AAAA")
    assert r.rcode() == dns.rcode.NOERROR
    aaaa_records = [
        rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.AAAA
    ]
    addresses = [rr.address for rr in aaaa_records]
    assert "2001:db8::1" in addresses


def test_ns_records():
    """Query NS records for zone apex."""
    r = query("example.com.", "NS")
    assert r.rcode() == dns.rcode.NOERROR
    ns_records = [rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.NS]
    targets = {str(rr.target) for rr in ns_records}
    assert "ns1.example.com." in targets
    assert "ns2.example.com." in targets


def test_mx_records():
    """Query MX records with correct preferences."""
    r = query("example.com.", "MX")
    assert r.rcode() == dns.rcode.NOERROR
    mx_records = [rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.MX]
    mx_data = {(rr.preference, str(rr.exchange)) for rr in mx_records}
    assert (10, "mail.example.com.") in mx_data
    assert (20, "mail2.example.com.") in mx_data


def test_soa_record():
    """Query SOA record with correct fields including all integer values."""
    r = query("example.com.", "SOA")
    assert r.rcode() == dns.rcode.NOERROR
    soa_records = [
        rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.SOA
    ]
    assert len(soa_records) == 1
    soa = soa_records[0]
    assert str(soa.mname) == "ns1.example.com."
    assert str(soa.rname) == "admin.example.com."
    assert soa.serial == 2024010101
    assert soa.refresh == 3600
    assert soa.retry == 900
    assert soa.expire == 604800
    assert soa.minimum == 86400


def test_txt_record():
    """Query TXT record with properly encoded character-string."""
    r = query("example.com.", "TXT")
    assert r.rcode() == dns.rcode.NOERROR
    txt_records = [
        rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.TXT
    ]
    assert len(txt_records) >= 1
    txt_data = b"".join(txt_records[0].strings).decode("ascii")
    assert "v=spf1" in txt_data


def test_a_record_subdomain():
    """Query A record for a subdomain."""
    r = query("ns1.example.com.", "A")
    assert r.rcode() == dns.rcode.NOERROR
    a_records = [rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.A]
    addresses = [rr.address for rr in a_records]
    assert "192.0.2.2" in addresses


def test_cname_single():
    """Query A for a CNAME should return CNAME + target A record."""
    r = query("www.example.com.", "A")
    assert r.rcode() == dns.rcode.NOERROR
    cname_records = [
        rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.CNAME
    ]
    assert len(cname_records) >= 1
    assert str(cname_records[0].target) == "example.com."
    a_records = [rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.A]
    assert len(a_records) >= 1
    assert "192.0.2.1" in [rr.address for rr in a_records]


def test_cname_chain():
    """Query A for a chained CNAME (blog -> www -> apex)."""
    r = query("blog.example.com.", "A")
    assert r.rcode() == dns.rcode.NOERROR
    cname_records = [
        rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.CNAME
    ]
    assert len(cname_records) >= 2
    a_records = [rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.A]
    assert len(a_records) >= 1
    assert "192.0.2.1" in [rr.address for rr in a_records]


def test_wildcard_match():
    """Wildcard *.wild.example.com should match foo.wild.example.com."""
    r = query("foo.wild.example.com.", "A")
    assert r.rcode() == dns.rcode.NOERROR
    a_records = [rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.A]
    assert len(a_records) >= 1
    assert "192.0.2.100" in [rr.address for rr in a_records]


def test_wildcard_different_name():
    """Wildcard should match any single label under wild.example.com."""
    r = query("bar.wild.example.com.", "A")
    assert r.rcode() == dns.rcode.NOERROR
    a_records = [rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.A]
    assert "192.0.2.100" in [rr.address for rr in a_records]


def test_wildcard_synthesized_name():
    """Wildcard responses must use the queried name, not the wildcard owner."""
    r = query("synth.wild.example.com.", "A")
    assert r.rcode() == dns.rcode.NOERROR
    for rrset in r.answer:
        assert str(rrset.name) == "synth.wild.example.com."


def test_nxdomain():
    """Non-existent name should return NXDOMAIN with SOA in authority."""
    r = query("nonexistent.example.com.", "A")
    assert r.rcode() == dns.rcode.NXDOMAIN
    soa_records = [
        rr for rrset in r.authority for rr in rrset if rr.rdtype == dns.rdatatype.SOA
    ]
    assert len(soa_records) >= 1


def test_nodata():
    """Existing name with no matching type returns NODATA (RCODE 0, empty answer, SOA in authority)."""
    r = query("ns1.example.com.", "AAAA")
    assert r.rcode() == dns.rcode.NOERROR
    assert len(r.answer) == 0
    soa_records = [
        rr for rrset in r.authority for rr in rrset if rr.rdtype == dns.rdatatype.SOA
    ]
    assert len(soa_records) >= 1


def test_edns0():
    """Query with EDNS0 OPT should get OPT in response with version 0."""
    r = query("example.com.", "A", use_edns=0)
    assert r.rcode() == dns.rcode.NOERROR
    assert r.edns >= 0, "Response should include EDNS0 OPT record"
    assert r.edns == 0, "EDNS version must be 0 per RFC 6891"


def test_aa_flag():
    """All responses should have the AA (Authoritative Answer) flag set."""
    r = query("example.com.", "A")
    assert r.flags & dns.flags.AA, "AA flag must be set"


def test_srv_record():
    """Query SRV record with correct priority, weight, port, and target."""
    r = query("_sip._tcp.example.com.", "SRV")
    assert r.rcode() == dns.rcode.NOERROR
    srv_records = [
        rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.SRV
    ]
    assert len(srv_records) >= 1
    srv = srv_records[0]
    assert srv.priority == 10
    assert srv.weight == 60
    assert srv.port == 5060
    assert str(srv.target) == "sip.example.com."


def test_sub_aaaa():
    """Subdomain with both A and AAAA should return correct AAAA."""
    r = query("sub.example.com.", "AAAA")
    assert r.rcode() == dns.rcode.NOERROR
    aaaa_records = [
        rr for rrset in r.answer for rr in rrset if rr.rdtype == dns.rdatatype.AAAA
    ]
    assert "2001:db8::50" in [rr.address for rr in aaaa_records]


def test_compliance_report_exists():
    """Compliance report must exist at /app/compliance_report.json with sufficient violations."""
    assert os.path.isfile("/app/compliance_report.json"), \
        "/app/compliance_report.json not found"
    with open("/app/compliance_report.json") as f:
        report = json.load(f)
    assert isinstance(report, list), "Report must be a JSON array"
    assert len(report) >= 4, \
        f"Report should document at least 4 violations, found {len(report)}"


def test_compliance_report_structure():
    """Each entry in compliance report must have required fields with valid values."""
    with open("/app/compliance_report.json") as f:
        report = json.load(f)
    required_fields = {"violation", "rfc", "section", "severity", "fix_description"}
    valid_severities = {"critical", "major", "minor"}
    for i, entry in enumerate(report):
        for field in required_fields:
            assert field in entry, f"Entry {i} missing required field '{field}'"
            assert isinstance(entry[field], str) and len(entry[field]) > 0, \
                f"Entry {i} field '{field}' must be a non-empty string"
        assert entry["severity"] in valid_severities, \
            f"Entry {i} severity '{entry['severity']}' not in {valid_severities}"
        assert entry["rfc"].startswith("RFC"), \
            f"Entry {i} rfc field '{entry['rfc']}' must start with 'RFC'"
