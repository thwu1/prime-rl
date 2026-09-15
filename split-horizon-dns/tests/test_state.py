"""
Tests for repaired BIND9 split-horizon DNS infrastructure.
Verifies forward/reverse zones, split-horizon views, and access control.
"""


import os
import subprocess
import pytest

DNS_SERVER = "127.0.0.1"
DNS_PORT = "8053"


def dig(name, qtype="A"):
    """Run a dig query and return +short output."""
    cmd = [
        "dig", f"@{DNS_SERVER}", "-p", DNS_PORT,
        name, qtype, "+short", "+tries=2", "+time=5",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


def dig_full(name, qtype="A"):
    """Run a dig query and return full output."""
    cmd = [
        "dig", f"@{DNS_SERVER}", "-p", DNS_PORT,
        name, qtype, "+tries=2", "+time=5",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout


def get_flags(output):
    """Extract DNS flags list from dig full output."""
    for line in output.split("\n"):
        if ";; flags:" in line:
            flags_str = line.split("flags:")[1].split(";")[0].strip()
            return flags_str.split()
    return []


def _get_parsed_config():
    """Return the parsed BIND config (comments stripped) via named-checkconf -p."""
    result = subprocess.run(
        ["named-checkconf", "-p"],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout if result.returncode == 0 else ""


def _find_external_zone_file():
    """
    Locate the external-view forward zone file by scanning /etc/bind/ for
    a file that contains both the zone name and external IPs (203.0.113.x).
    Works regardless of directory layout or view naming conventions.
    """
    for root, _dirs, files in os.walk("/etc/bind"):
        for name in files:
            path = os.path.join(root, name)
            try:
                with open(path) as f:
                    content = f.read()
                if "203.0.113" in content and "infra.example.com" in content:
                    return path
            except (IOError, UnicodeDecodeError):
                continue
    return None


def _dump_zone(zone_name, zone_file):
    """Dump zone records in canonical format using named-checkzone -D."""
    result = subprocess.run(
        ["named-checkzone", "-D", zone_name, zone_file],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout if result.returncode == 0 else ""


def _get_a_from_dump(dump, hostname):
    """Extract A record value for a hostname from named-checkzone -D output."""
    fqdn = f"{hostname}.infra.example.com."
    for line in dump.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == fqdn and parts[3] == "A":
            return parts[4]
    return None


# ---------------------------------------------------------------------------
# Core infrastructure
# ---------------------------------------------------------------------------

class TestBindRunning:
    def test_bind_responds(self):
        """BIND9 should respond to queries on port 8053."""
        result = dig("infra.example.com", "SOA")
        assert result, "BIND is not responding on port 8053"


class TestConfigValidation:
    def test_named_checkconf(self):
        """named.conf must be syntactically valid."""
        result = subprocess.run(
            ["named-checkconf"], capture_output=True, text=True,
        )
        assert result.returncode == 0, f"named-checkconf failed: {result.stderr}"


# ---------------------------------------------------------------------------
# Internal-view forward zone
# ---------------------------------------------------------------------------

class TestForwardZoneInternal:
    def test_soa_record(self):
        result = dig("infra.example.com", "SOA")
        assert "ns1.infra.example.com" in result
        assert "admin.infra.example.com" in result

    def test_ns_records(self):
        result = dig("infra.example.com", "NS")
        assert "ns1.infra.example.com" in result
        assert "ns2.infra.example.com" in result

    @pytest.mark.parametrize("hostname,expected_ip", [
        ("ns1.infra.example.com", "10.0.1.1"),
        ("ns2.infra.example.com", "10.0.1.2"),
        ("web1.infra.example.com", "10.0.1.10"),
        ("web2.infra.example.com", "10.0.1.11"),
        ("db1.infra.example.com", "10.0.1.20"),
        ("mail.infra.example.com", "10.0.1.30"),
        ("vpn.infra.example.com", "10.0.1.40"),
    ])
    def test_a_record(self, hostname, expected_ip):
        result = dig(hostname, "A")
        assert result == expected_ip, (
            f"{hostname}: expected {expected_ip}, got {result}"
        )

    @pytest.mark.parametrize("hostname,expected_ip", [
        ("ns1.infra.example.com", "fd00::1"),
        ("ns2.infra.example.com", "fd00::2"),
        ("web1.infra.example.com", "fd00::10"),
        ("web2.infra.example.com", "fd00::11"),
        ("db1.infra.example.com", "fd00::20"),
        ("mail.infra.example.com", "fd00::30"),
    ])
    def test_aaaa_record(self, hostname, expected_ip):
        result = dig(hostname, "AAAA")
        assert result.lower() == expected_ip.lower(), (
            f"{hostname}: expected {expected_ip}, got {result}"
        )

    def test_mx_record(self):
        result = dig("infra.example.com", "MX")
        assert "10" in result
        assert "mail.infra.example.com" in result

    def test_mx_target_fqdn(self):
        """MX target must be a proper FQDN — not double-appended origin."""
        result = dig("infra.example.com", "MX")
        # If trailing dot was missing, BIND appends origin producing
        # mail.infra.example.com.infra.example.com — reject that.
        assert "infra.example.com.infra.example.com" not in result, (
            f"MX target has double-appended origin (missing trailing dot): {result}"
        )

    def test_cname_www(self):
        result = dig("www.infra.example.com", "CNAME")
        assert "web1.infra.example.com" in result

    def test_cname_smtp(self):
        result = dig("smtp.infra.example.com", "CNAME")
        assert "mail.infra.example.com" in result

    def test_srv_ldap(self):
        result = dig("_ldap._tcp.infra.example.com", "SRV")
        assert "389" in result
        assert "db1.infra.example.com" in result
        assert "0 100 389" in result

    def test_txt_spf(self):
        result = dig("infra.example.com", "TXT")
        assert "v=spf1" in result
        assert "mail.infra.example.com" in result

    def test_no_cname_at_apex(self):
        """Zone apex must not have a CNAME (RFC 1034 violation)."""
        result = dig("infra.example.com", "CNAME")
        assert not result, (
            f"CNAME at zone apex is an RFC violation: {result}"
        )


# ---------------------------------------------------------------------------
# IPv4 reverse zone
# ---------------------------------------------------------------------------

class TestReverseZoneIPv4:
    @pytest.mark.parametrize("last_octet,expected_host", [
        ("1", "ns1.infra.example.com."),
        ("2", "ns2.infra.example.com."),
        ("10", "web1.infra.example.com."),
        ("11", "web2.infra.example.com."),
        ("20", "db1.infra.example.com."),
        ("30", "mail.infra.example.com."),
        ("40", "vpn.infra.example.com."),
    ])
    def test_ptr_ipv4(self, last_octet, expected_host):
        query = f"{last_octet}.1.0.10.in-addr.arpa"
        result = dig(query, "PTR")
        assert expected_host in result, (
            f"PTR {query}: expected {expected_host}, got {result}"
        )

    def test_ptr_target_is_fqdn(self):
        """PTR targets must be proper FQDNs, not relative to reverse zone."""
        query = "1.1.0.10.in-addr.arpa"
        result = dig(query, "PTR")
        assert "in-addr.arpa" not in result, (
            f"PTR target appears relative to reverse zone (missing trailing dot): {result}"
        )


# ---------------------------------------------------------------------------
# IPv6 reverse zone
# ---------------------------------------------------------------------------

class TestReverseZoneIPv6:
    @pytest.mark.parametrize("ipv6_fqdn,expected_host", [
        # fd00::1  -> ns1
        (
            "1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0"
            ".0.0.0.0.0.0.0.0.0.0.0.0.0.0.d.f.ip6.arpa",
            "ns1.infra.example.com.",
        ),
        # fd00::2  -> ns2
        (
            "2.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0"
            ".0.0.0.0.0.0.0.0.0.0.0.0.0.0.d.f.ip6.arpa",
            "ns2.infra.example.com.",
        ),
        # fd00::10 -> web1
        (
            "0.1.0.0.0.0.0.0.0.0.0.0.0.0.0.0"
            ".0.0.0.0.0.0.0.0.0.0.0.0.0.0.d.f.ip6.arpa",
            "web1.infra.example.com.",
        ),
        # fd00::11 -> web2
        (
            "1.1.0.0.0.0.0.0.0.0.0.0.0.0.0.0"
            ".0.0.0.0.0.0.0.0.0.0.0.0.0.0.d.f.ip6.arpa",
            "web2.infra.example.com.",
        ),
        # fd00::20 -> db1
        (
            "0.2.0.0.0.0.0.0.0.0.0.0.0.0.0.0"
            ".0.0.0.0.0.0.0.0.0.0.0.0.0.0.d.f.ip6.arpa",
            "db1.infra.example.com.",
        ),
        # fd00::30 -> mail
        (
            "0.3.0.0.0.0.0.0.0.0.0.0.0.0.0.0"
            ".0.0.0.0.0.0.0.0.0.0.0.0.0.0.d.f.ip6.arpa",
            "mail.infra.example.com.",
        ),
    ])
    def test_ptr_ipv6(self, ipv6_fqdn, expected_host):
        result = dig(ipv6_fqdn, "PTR")
        assert expected_host in result, (
            f"IPv6 PTR: expected {expected_host}, got {result}"
        )


# ---------------------------------------------------------------------------
# Split-horizon (external view) — verified via zone file inspection
# ---------------------------------------------------------------------------

class TestSplitHorizon:
    """
    Verify the external view serves correct IPs by dumping its zone file
    with named-checkzone -D.  This avoids needing CAP_NET_ADMIN to add a
    secondary loopback address for source-IP-based testing.
    """

    @pytest.fixture(autouse=True)
    def _load_zone(self):
        zone_file = _find_external_zone_file()
        assert zone_file is not None, (
            "Could not find an external-view zone file containing external "
            "IPs (203.0.113.x) under /etc/bind/"
        )
        self.zone_dump = _dump_zone("infra.example.com", zone_file)
        assert self.zone_dump, (
            f"named-checkzone -D failed for {zone_file}"
        )

    def test_external_web1(self):
        """web1 should resolve to external IP in external view."""
        ip = _get_a_from_dump(self.zone_dump, "web1")
        assert ip == "203.0.113.10", (
            f"External web1: expected 203.0.113.10, got {ip}"
        )

    def test_external_web2(self):
        """web2 should resolve to external IP in external view."""
        ip = _get_a_from_dump(self.zone_dump, "web2")
        assert ip == "203.0.113.11", (
            f"External web2: expected 203.0.113.11, got {ip}"
        )

    def test_external_vpn(self):
        """vpn should resolve to external IP in external view."""
        ip = _get_a_from_dump(self.zone_dump, "vpn")
        assert ip == "203.0.113.40", (
            f"External vpn: expected 203.0.113.40, got {ip}"
        )

    def test_external_nonsplit_host(self):
        """Hosts without external IPs return internal IP from external view."""
        ip = _get_a_from_dump(self.zone_dump, "db1")
        assert ip == "10.0.1.20", (
            f"External db1 (no ext IP): expected 10.0.1.20, got {ip}"
        )


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

class TestAccessControl:
    def test_zone_transfer_restriction(self):
        """AXFR from unauthorized source must be refused."""
        result = subprocess.run(
            [
                "dig", f"@{DNS_SERVER}", "-p", DNS_PORT,
                "infra.example.com", "AXFR", "+time=5",
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert "; XFR size:" not in result.stdout, (
            "Zone transfer should be restricted but AXFR succeeded"
        )

    def test_recursion_available_internal(self):
        """Internal clients should have recursion available (ra flag)."""
        output = dig_full("infra.example.com", "SOA")
        flags = get_flags(output)
        assert "ra" in flags, (
            f"Recursion not available for internal clients. Flags: {flags}"
        )

    def test_no_recursion_external(self):
        """Non-internal views must have recursion disabled in the config."""
        conf = _get_parsed_config()
        assert conf, "Could not parse BIND configuration via named-checkconf -p"
        assert "recursion no" in conf, (
            "Named configuration must include 'recursion no' for "
            "non-internal views"
        )

    def test_internal_view_matches_localhost(self):
        """Queries from 127.0.0.1 must match the internal view (not external)."""
        # If views are ordered correctly, localhost hits internal view
        # which serves internal IPs. If wrong, we'd get external IPs.
        result = dig("web1.infra.example.com", "A")
        assert result == "10.0.1.10", (
            f"View ordering may be wrong: web1 returned {result} instead of "
            f"10.0.1.10 from localhost (should match internal view)"
        )
