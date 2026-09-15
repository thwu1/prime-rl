"""
Tests for BIND9 DNS security deployment task.

Verifies DNSSEC signing, TSIG zone transfer authentication,
RPZ threat blocking, Response Rate Limiting, and that all
original DNS records and split-horizon behavior are preserved.
"""

import subprocess
import pytest
import re
import os
import glob


def dns_query(name, qtype="A"):
    """Query the local BIND9 server and return +short output."""
    cmd = ["dig", "@127.0.0.1", name, qtype, "+short", "+timeout=5", "+tries=3"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    return result.stdout.strip()


def dns_query_full(name, qtype="A", extra_flags=None):
    """Query and return full dig output for detailed inspection."""
    cmd = ["dig", "@127.0.0.1", name, qtype, "+timeout=5", "+tries=3"]
    if extra_flags:
        cmd.extend(extra_flags)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    return result.stdout


def reverse_lookup(ip):
    """Perform a reverse DNS lookup via the local server."""
    cmd = ["dig", "@127.0.0.1", "-x", ip, "+short", "+timeout=5", "+tries=3"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    return result.stdout.strip()


def find_tsig_secret():
    """Search all BIND config files for the xfer-key TSIG secret."""
    for path in glob.glob("/etc/bind/**", recursive=True):
        if not os.path.isfile(path):
            continue
        try:
            with open(path) as f:
                content = f.read()
        except (IOError, UnicodeDecodeError):
            continue
        match = re.search(
            r'key\s+"xfer-key"\s*\{[^}]*?secret\s+"([^"]+)"',
            content,
            re.DOTALL,
        )
        if match:
            return match.group(1)
    return None


# ---------------------------------------------------------------------------
# 1. Named Running & Configuration Valid
# ---------------------------------------------------------------------------
class TestNamedRunning:
    """BIND9 must be running and configuration must be valid."""

    def test_named_responds_on_localhost(self):
        result = subprocess.run(
            ["dig", "@127.0.0.1", "weilburg.corp", "SOA",
             "+timeout=5", "+tries=3"],
            capture_output=True, text=True, timeout=20,
        )
        combined = (result.stdout + result.stderr).lower()
        assert "connection refused" not in combined, \
            "named is not listening on 127.0.0.1:53"
        assert "timed out" not in combined, \
            "named is not responding on 127.0.0.1:53"

    def test_named_checkconf(self):
        result = subprocess.run(
            ["named-checkconf", "/etc/bind/named.conf"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, \
            f"named-checkconf failed: {result.stderr}"


# ---------------------------------------------------------------------------
# 2. Original Records Preserved
# ---------------------------------------------------------------------------
class TestOriginalRecords:
    """All original DNS records and split-horizon behavior must work."""

    def test_root_domain(self):
        assert dns_query("weilburg.corp", "A") == "10.10.0.1"

    def test_web(self):
        assert dns_query("web.weilburg.corp", "A") == "10.10.0.10"

    def test_portal(self):
        assert dns_query("portal.weilburg.corp", "A") == "10.10.0.20"

    def test_mx_record(self):
        answer = dns_query_full("weilburg.corp", "MX", ["+noall", "+answer"])
        assert "mx.weilburg.corp." in answer, \
            f"MX record incorrect: {answer}"

    def test_reverse_web(self):
        assert reverse_lookup("10.10.0.10") == "web.weilburg.corp."

    def test_www_cname(self):
        result = dns_query("www.weilburg.corp", "A")
        assert "10.10.0.10" in result


# ---------------------------------------------------------------------------
# 3. DNSSEC Signing
# ---------------------------------------------------------------------------
class TestDNSSEC:
    """Zones must be signed with ECDSAP256SHA256 and NSEC3."""

    def test_dnskey_exists(self):
        result = dns_query("weilburg.corp", "DNSKEY")
        assert result, "No DNSKEY records found for weilburg.corp"

    def test_rrsig_on_a_record(self):
        output = dns_query_full("weilburg.corp", "A", ["+dnssec"])
        assert "RRSIG" in output, \
            "No RRSIG found in DNSSEC-aware A query"

    def test_rrsig_on_soa(self):
        output = dns_query_full("weilburg.corp", "SOA", ["+dnssec"])
        assert "RRSIG" in output, \
            "No RRSIG found in DNSSEC-aware SOA query"

    def test_algorithm_ecdsap256sha256(self):
        """DNSKEY must use algorithm 13 (ECDSAP256SHA256)."""
        output = dns_query("weilburg.corp", "DNSKEY")
        lines = [l.strip() for l in output.split("\n") if l.strip()]
        assert lines, "No DNSKEY records"
        for line in lines:
            parts = line.split()
            assert len(parts) >= 3, f"Unexpected DNSKEY format: {line}"
            assert parts[2] == "13", \
                f"DNSKEY uses algorithm {parts[2]}, expected 13"

    def test_nsec3_in_use(self):
        """Zone must use NSEC3 for authenticated denial of existence."""
        result = dns_query("weilburg.corp", "NSEC3PARAM")
        assert result, \
            "NSEC3PARAM not found — zone may not be using NSEC3"

    def test_nsec3_zero_iterations(self):
        """NSEC3 must use zero iterations per RFC 9276."""
        output = dns_query("weilburg.corp", "NSEC3PARAM")
        # NSEC3PARAM +short format: algorithm flags iterations salt
        parts = output.split()
        assert len(parts) >= 3, f"Unexpected NSEC3PARAM format: {output}"
        iterations = int(parts[2])
        assert iterations == 0, \
            f"NSEC3 iterations should be 0 per RFC 9276, got {iterations}"


# ---------------------------------------------------------------------------
# 4. TSIG Zone Transfer Authentication
# ---------------------------------------------------------------------------
class TestTSIG:
    """Zone transfers must require TSIG authentication."""

    def test_tsig_key_exists_in_config(self):
        secret = find_tsig_secret()
        assert secret is not None, \
            "TSIG key 'xfer-key' (hmac-sha256) not found in BIND config"

    def test_axfr_with_key_succeeds(self):
        secret = find_tsig_secret()
        assert secret, "Cannot test: xfer-key not found"
        result = subprocess.run(
            ["dig", "@127.0.0.1", "weilburg.corp", "AXFR",
             "-y", f"hmac-sha256:xfer-key:{secret}",
             "+timeout=10"],
            capture_output=True, text=True, timeout=30,
        )
        # Successful AXFR wraps zone data between two SOA records
        soa_count = result.stdout.lower().count("\tsoa\t")
        assert soa_count >= 2, \
            f"AXFR with valid TSIG should succeed (got {soa_count} SOA records)"

    def test_axfr_without_key_refused(self):
        result = subprocess.run(
            ["dig", "@127.0.0.1", "weilburg.corp", "AXFR",
             "+timeout=5", "+tries=1"],
            capture_output=True, text=True, timeout=20,
        )
        output = result.stdout.lower()
        soa_count = output.count("\tsoa\t")
        transfer_denied = (
            "refused" in output
            or "transfer failed" in output
            or soa_count < 2
        )
        assert transfer_denied, \
            "AXFR without TSIG key should be refused"


# ---------------------------------------------------------------------------
# 5. Response Policy Zone (RPZ) Threat Blocking
# ---------------------------------------------------------------------------
class TestRPZ:
    """RPZ must block specified threat domains."""

    def test_malware_blocked_nxdomain(self):
        output = dns_query_full("malware.evil.test", "A")
        assert "NXDOMAIN" in output, \
            f"malware.evil.test should return NXDOMAIN: {output}"

    def test_phishing_redirected_to_sinkhole(self):
        result = dns_query("phishing.evil.test", "A")
        assert "10.10.0.99" in result, \
            f"phishing.evil.test should redirect to 10.10.0.99, got: {result}"

    def test_botnet_wildcard_blocked(self):
        output = dns_query_full("c2.botnet.evil.test", "A")
        assert "NXDOMAIN" in output, \
            f"c2.botnet.evil.test should return NXDOMAIN: {output}"

    def test_legitimate_domain_unaffected(self):
        result = dns_query("web.weilburg.corp", "A")
        assert result == "10.10.0.10", \
            f"RPZ affected legitimate domain resolution: got {result}"


# ---------------------------------------------------------------------------
# 6. Response Rate Limiting
# ---------------------------------------------------------------------------
class TestRRL:
    """RRL must be configured in BIND options."""

    def test_rrl_configured_in_named(self):
        found_rate_limit = False
        found_rps = False
        for path in glob.glob("/etc/bind/**", recursive=True):
            if not os.path.isfile(path):
                continue
            try:
                with open(path) as f:
                    content = f.read()
            except (IOError, UnicodeDecodeError):
                continue
            if "rate-limit" in content:
                found_rate_limit = True
            if "responses-per-second" in content:
                found_rps = True
        assert found_rate_limit, \
            "rate-limit block not found in BIND configuration"
        assert found_rps, \
            "responses-per-second not found in rate-limit configuration"
