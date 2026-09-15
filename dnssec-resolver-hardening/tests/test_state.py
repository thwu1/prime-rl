
"""
Verification tests for DNS infrastructure diagnosis and repair:
  - NSD authoritative server on 127.0.0.1:5353
  - Unbound validating resolver on 127.0.0.1:5300
  - DNSSEC signing and validation for acme-internal.test
  - Private-address response filtering for evil.test
"""

import time
import dns.message
import dns.query
import dns.flags
import dns.rdatatype
import dns.rcode
import pytest


SERVER = "127.0.0.1"
RESOLVER_PORT = 5300
AUTH_PORT = 5353
TIMEOUT = 10


def send_query(name, rdtype, port=RESOLVER_PORT, want_dnssec=False):
    """Send a UDP DNS query and return the response message."""
    q = dns.message.make_query(name, rdtype, want_dnssec=want_dnssec)
    if want_dnssec:
        q.flags |= dns.flags.AD
    return dns.query.udp(q, SERVER, port=port, timeout=TIMEOUT)


def send_query_with_retry(name, rdtype, port=RESOLVER_PORT, want_dnssec=False,
                          retries=8, delay=3):
    """Send a DNS query with retries for resolver startup timing."""
    for attempt in range(retries):
        try:
            r = send_query(name, rdtype, port=port, want_dnssec=want_dnssec)
            if r.rcode() in (dns.rcode.SERVFAIL, dns.rcode.REFUSED):
                time.sleep(delay)
                continue
            return r
        except Exception:
            time.sleep(delay)
    # Final attempt — let any exception propagate
    return send_query(name, rdtype, port=port, want_dnssec=want_dnssec)


class TestAuthoritativeServer:
    """Verify NSD is running and serving zones on port 5353."""

    def test_nsd_serves_acme_zone(self):
        r = send_query("www.acme-internal.test", "A", port=AUTH_PORT)
        assert r.rcode() == dns.rcode.NOERROR, (
            f"Expected NOERROR, got {dns.rcode.to_text(r.rcode())}"
        )
        addrs = [str(rr) for rrset in r.answer for rr in rrset
                 if rrset.rdtype == dns.rdatatype.A]
        assert "203.0.113.10" in addrs, f"Expected 203.0.113.10 in {addrs}"

    def test_nsd_serves_evil_zone(self):
        r = send_query("trap.evil.test", "A", port=AUTH_PORT)
        assert r.rcode() == dns.rcode.NOERROR, (
            f"Expected NOERROR, got {dns.rcode.to_text(r.rcode())}"
        )
        addrs = [str(rr) for rrset in r.answer for rr in rrset
                 if rrset.rdtype == dns.rdatatype.A]
        assert "10.0.0.1" in addrs, (
            f"NSD should return 10.0.0.1 directly, got {addrs}"
        )


class TestResolverRecords:
    """Verify Unbound resolves all record types through NSD."""

    def test_a_record_www(self):
        r = send_query_with_retry("www.acme-internal.test", "A")
        assert r.rcode() == dns.rcode.NOERROR
        addrs = [str(rr) for rrset in r.answer for rr in rrset
                 if rrset.rdtype == dns.rdatatype.A]
        assert "203.0.113.10" in addrs

    def test_a_record_mail(self):
        r = send_query_with_retry("mail.acme-internal.test", "A")
        assert r.rcode() == dns.rcode.NOERROR
        addrs = [str(rr) for rrset in r.answer for rr in rrset
                 if rrset.rdtype == dns.rdatatype.A]
        assert "203.0.113.20" in addrs

    def test_mx_record(self):
        r = send_query_with_retry("acme-internal.test", "MX")
        assert r.rcode() == dns.rcode.NOERROR
        mx_strs = [str(rr) for rrset in r.answer for rr in rrset
                   if rrset.rdtype == dns.rdatatype.MX]
        assert any("mail.acme-internal.test" in s.lower() for s in mx_strs), (
            f"MX not found: {mx_strs}"
        )

    def test_srv_record(self):
        r = send_query_with_retry("_submission._tcp.acme-internal.test", "SRV")
        assert r.rcode() == dns.rcode.NOERROR
        srv_strs = [str(rr) for rrset in r.answer for rr in rrset
                    if rrset.rdtype == dns.rdatatype.SRV]
        assert any(
            "587" in s and "mail.acme-internal.test" in s.lower()
            for s in srv_strs
        ), f"SRV record with port 587 and mail target not found: {srv_strs}"

    def test_cname_resolution(self):
        r = send_query_with_retry("cdn.acme-internal.test", "A")
        assert r.rcode() == dns.rcode.NOERROR
        has_cname = any(
            rrset.rdtype == dns.rdatatype.CNAME for rrset in r.answer
        )
        a_addrs = [str(rr) for rrset in r.answer for rr in rrset
                   if rrset.rdtype == dns.rdatatype.A]
        assert has_cname, "Expected CNAME in answer section"
        assert "203.0.113.10" in a_addrs, (
            f"CNAME chain should resolve to 203.0.113.10, got {a_addrs}"
        )

    def test_wildcard_resolution(self):
        r = send_query_with_retry("anything.apps.acme-internal.test", "A")
        assert r.rcode() == dns.rcode.NOERROR
        addrs = [str(rr) for rrset in r.answer for rr in rrset
                 if rrset.rdtype == dns.rdatatype.A]
        assert "203.0.113.50" in addrs, (
            f"Wildcard should resolve to 203.0.113.50, got {addrs}"
        )

    def test_ptr_reverse_lookup(self):
        r = send_query_with_retry("10.113.0.203.in-addr.arpa", "PTR")
        assert r.rcode() == dns.rcode.NOERROR
        ptrs = [str(rr) for rrset in r.answer for rr in rrset
                if rrset.rdtype == dns.rdatatype.PTR]
        assert any("www.acme-internal.test" in p.lower() for p in ptrs), (
            f"PTR not found: {ptrs}"
        )


class TestDNSSECValidation:
    """Verify DNSSEC signing and validation through the resolver."""

    def test_ad_flag_set_on_validated_response(self):
        """Querying with DO bit must return AD flag for the signed zone."""
        r = send_query_with_retry(
            "www.acme-internal.test", "A", want_dnssec=True
        )
        assert r.rcode() == dns.rcode.NOERROR, (
            f"Query failed: {dns.rcode.to_text(r.rcode())}"
        )
        assert r.flags & dns.flags.AD, (
            f"AD flag not set — DNSSEC validation failed. "
            f"Flags: {dns.flags.to_text(r.flags)}"
        )

    def test_dnskey_records_present(self):
        """The signed zone must contain DNSKEY records."""
        r = send_query(
            "acme-internal.test", "DNSKEY", port=AUTH_PORT, want_dnssec=True
        )
        assert r.rcode() == dns.rcode.NOERROR
        dnskeys = [rr for rrset in r.answer for rr in rrset
                   if rrset.rdtype == dns.rdatatype.DNSKEY]
        assert len(dnskeys) >= 2, (
            f"Expected at least KSK + ZSK, found {len(dnskeys)} DNSKEY records"
        )

    def test_rrsig_present_in_signed_zone(self):
        """RRSIG records must accompany A records in the signed zone."""
        r = send_query(
            "www.acme-internal.test", "A", port=AUTH_PORT, want_dnssec=True
        )
        assert r.rcode() == dns.rcode.NOERROR
        has_rrsig = any(
            rrset.rdtype == dns.rdatatype.RRSIG for rrset in r.answer
        )
        assert has_rrsig, (
            "No RRSIG records found for www.acme-internal.test A query"
        )


class TestPrivateAddressFiltering:
    """Verify RFC1918 response filtering (deny_answers equivalent)."""

    def test_private_address_filtered_from_response(self):
        """trap.evil.test A record (10.0.0.1) must be blocked by resolver."""
        r = send_query_with_retry("trap.evil.test", "A")
        # The private address must not appear in the answer
        for rrset in r.answer:
            for rr in rrset:
                assert "10.0.0.1" not in str(rr), (
                    "Private address 10.0.0.1 was not filtered"
                )

    def test_non_private_address_passes_through(self):
        """legit.evil.test A record (203.0.113.99) must resolve normally."""
        r = send_query_with_retry("legit.evil.test", "A")
        assert r.rcode() == dns.rcode.NOERROR, (
            f"Expected NOERROR, got {dns.rcode.to_text(r.rcode())}"
        )
        addrs = [str(rr) for rrset in r.answer for rr in rrset
                 if rrset.rdtype == dns.rdatatype.A]
        assert "203.0.113.99" in addrs, (
            f"legit.evil.test should resolve to 203.0.113.99, got {addrs}"
        )
