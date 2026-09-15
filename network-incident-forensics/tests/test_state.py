
import json
import os
import re
import pytest


def load_report():
    report_path = "/app/report.json"
    assert os.path.exists(report_path), (
        f"Report file not found at {report_path}. "
        "The analysis must produce this file."
    )
    with open(report_path, "r") as f:
        return json.load(f)


class TestForensicDiagnosis:
    """Verify forensic findings from diagnostic text files."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report()

    def test_all_required_fields_present(self):
        required = [
            "conntrack_drops", "conntrack_max", "accept_overflow_port",
            "accept_overflow_count", "listen_backlog", "syn_cookies_sent",
            "syn_cookies_recv", "ephemeral_range_size", "ephemeral_ports_used",
            "unique_outbound_destinations", "eaddrinuse_count", "eperm_count",
            "eperm_caused_by_conntrack", "time_wait_count",
            "uses_bind_before_connect", "root_causes",
            "syn_flood_source_cidrs", "syn_flood_total_packets",
            "legitimate_syn_rate_pps", "udp_reflection_sources",
            "recommended_conntrack_max", "recommended_syn_backlog",
            "recommended_rate_limit_pps", "recommended_port_range",
            "nftables_hook", "nftables_priority",
        ]
        for field in required:
            assert field in self.report, f"Missing required field: {field}"

    def test_conntrack_drops(self):
        assert self.report["conntrack_drops"] == 7822

    def test_conntrack_max(self):
        assert self.report["conntrack_max"] == 10000

    def test_accept_overflow_port(self):
        assert self.report["accept_overflow_port"] == 8080

    def test_accept_overflow_count(self):
        assert self.report["accept_overflow_count"] == 4271

    def test_listen_backlog(self):
        assert self.report["listen_backlog"] == 128

    def test_syn_cookies_sent(self):
        assert self.report["syn_cookies_sent"] == 892

    def test_syn_cookies_recv(self):
        assert self.report["syn_cookies_recv"] == 743

    def test_ephemeral_range_size(self):
        assert self.report["ephemeral_range_size"] == 28232

    def test_ephemeral_ports_used(self):
        assert self.report["ephemeral_ports_used"] == 28230

    def test_unique_outbound_destinations(self):
        assert self.report["unique_outbound_destinations"] == 3

    def test_eaddrinuse_count(self):
        assert self.report["eaddrinuse_count"] == 7

    def test_eperm_count(self):
        assert self.report["eperm_count"] == 2

    def test_eperm_caused_by_conntrack(self):
        assert self.report["eperm_caused_by_conntrack"] is True

    def test_time_wait_count(self):
        assert self.report["time_wait_count"] == 14

    def test_uses_bind_before_connect(self):
        assert self.report["uses_bind_before_connect"] is True

    def test_root_causes(self):
        causes = set(self.report["root_causes"])
        expected = {
            "conntrack_overflow",
            "accept_queue_overflow",
            "ephemeral_port_exhaustion",
        }
        assert causes == expected, (
            f"Expected root causes {expected}, got {causes}"
        )


class TestTrafficAnalysis:
    """Verify findings derived from pcap analysis."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report()

    def test_syn_flood_source_cidrs(self):
        expected = sorted([
            "192.0.2.0/24",
            "198.51.100.0/24",
            "203.0.113.0/24",
        ])
        actual = sorted(self.report["syn_flood_source_cidrs"])
        assert actual == expected, (
            f"Expected attack CIDRs {expected}, got {actual}"
        )

    def test_syn_flood_total_packets(self):
        assert self.report["syn_flood_total_packets"] == 4500

    def test_legitimate_syn_rate_pps(self):
        assert self.report["legitimate_syn_rate_pps"] == 5

    def test_udp_reflection_sources(self):
        assert self.report["udp_reflection_sources"] == 18


class TestRemediationDesign:
    """Verify remediation values computed per policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report()

    def test_recommended_conntrack_max(self):
        assert self.report["recommended_conntrack_max"] == 30000

    def test_recommended_syn_backlog(self):
        assert self.report["recommended_syn_backlog"] == 2048

    def test_recommended_rate_limit_pps(self):
        assert self.report["recommended_rate_limit_pps"] == 50

    def test_recommended_port_range(self):
        assert self.report["recommended_port_range"] == "1024 65535"

    def test_nftables_hook(self):
        assert self.report["nftables_hook"] == "prerouting"

    def test_nftables_priority(self):
        assert self.report["nftables_priority"] == -300


class TestMitigationRuleset:
    """Verify the created nftables mitigation ruleset."""

    @pytest.fixture(autouse=True)
    def setup(self):
        path = "/app/mitigation.nft"
        assert os.path.exists(path), (
            "Mitigation ruleset not found at /app/mitigation.nft"
        )
        with open(path, "r") as f:
            self.ruleset = f.read()

    def test_defines_nftables_table(self):
        """Must define an nftables table in inet or ip family."""
        assert re.search(r'table\s+(inet|ip)\s+\w+', self.ruleset), (
            "Ruleset must define an nftables table (inet or ip family)"
        )

    def test_chain_hook_prerouting(self):
        """Chain must attach to prerouting hook."""
        assert re.search(r'hook\s+prerouting', self.ruleset, re.IGNORECASE), (
            "Chain must use the prerouting hook"
        )

    def test_chain_priority_raw(self):
        """Priority must be -300 (raw, before conntrack at -200)."""
        assert re.search(r'priority\s+-300', self.ruleset), (
            "Chain priority must be -300"
        )

    def test_blocks_all_attack_cidrs(self):
        """All identified attack /24 CIDRs must appear in the ruleset."""
        for cidr in ["192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"]:
            assert cidr in self.ruleset, (
                f"Attack CIDR {cidr} not found in ruleset"
            )

    def test_rate_limit_value(self):
        """Rate limit must be 50 packets per second."""
        assert re.search(r'50\s*/\s*second', self.ruleset), (
            "Rate limit of 50/second not found in ruleset"
        )

    def test_contains_drop_action(self):
        """Must include drop action for attack traffic."""
        assert "drop" in self.ruleset.lower(), (
            "Ruleset must include drop action"
        )
