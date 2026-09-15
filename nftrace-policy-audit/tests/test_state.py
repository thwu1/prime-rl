
import json
import os
import pytest


@pytest.fixture(scope="session")
def report():
    with open("/app/audit_report.json") as f:
        return json.load(f)


def get_flow(report, trace_id):
    return next(f for f in report["flows"] if f["trace_id"] == trace_id)


# ---------------------------------------------------------------------------
# Report structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists("/app/audit_report.json"), "audit_report.json not found"

    def test_report_valid_json(self):
        with open("/app/audit_report.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)
        for key in ("flows", "policy_violations", "stale_rules",
                     "conntrack_anomalies", "summary"):
            assert key in data, f"Missing top-level key: {key}"

    def test_flows_count(self, report):
        assert len(report["flows"]) == 8

    def test_flows_have_required_fields(self, report):
        required = {
            "trace_id", "protocol", "src_addr", "dst_addr",
            "verdict", "ingress_interface", "egress_interface",
            "from_zone", "to_zone", "policy_compliant",
            "chain_path", "nat_type",
        }
        for flow in report["flows"]:
            missing = required - set(flow.keys())
            assert not missing, (
                f"Flow {flow.get('trace_id', '?')} missing: {missing}"
            )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_total_flows(self, report):
        assert report["summary"]["total_flows"] == 8

    def test_accepted_flows(self, report):
        assert report["summary"]["accepted_flows"] == 7

    def test_dropped_flows(self, report):
        assert report["summary"]["dropped_flows"] == 1

    def test_snat_flows(self, report):
        assert report["summary"]["snat_flows"] == 3

    def test_dnat_flows(self, report):
        assert report["summary"]["dnat_flows"] == 2

    def test_violation_count(self, report):
        assert report["summary"]["policy_violations"] == 2

    def test_stale_rules_count(self, report):
        assert report["summary"]["stale_rules"] == 3

    def test_conntrack_anomalies_count(self, report):
        assert report["summary"]["conntrack_anomalies"] == 3


# ---------------------------------------------------------------------------
# Flow: a1b2c3d4 — TCP LAN->WAN with SNAT masquerade
# ---------------------------------------------------------------------------

class TestFlowA1B2C3D4:
    def test_protocol(self, report):
        flow = get_flow(report, "a1b2c3d4")
        assert flow["protocol"] == "tcp"

    def test_addresses(self, report):
        flow = get_flow(report, "a1b2c3d4")
        assert flow["src_addr"] == "192.168.10.50"
        assert flow["dst_addr"] == "203.0.113.80"

    def test_ports(self, report):
        flow = get_flow(report, "a1b2c3d4")
        assert flow["src_port"] == 45678
        assert flow["dst_port"] == 443

    def test_interfaces(self, report):
        flow = get_flow(report, "a1b2c3d4")
        assert flow["ingress_interface"] == "eth1"
        assert flow["egress_interface"] == "eth0"

    def test_zones(self, report):
        flow = get_flow(report, "a1b2c3d4")
        assert flow["from_zone"] == "LAN"
        assert flow["to_zone"] == "WAN"

    def test_verdict_and_compliance(self, report):
        flow = get_flow(report, "a1b2c3d4")
        assert flow["verdict"] == "accept"
        assert flow["policy_compliant"] is True

    def test_nat(self, report):
        flow = get_flow(report, "a1b2c3d4")
        assert flow["nat_type"] == "snat"

    def test_chain_path_length(self, report):
        flow = get_flow(report, "a1b2c3d4")
        assert len(flow["chain_path"]) >= 4


# ---------------------------------------------------------------------------
# Flow: e5f6a7b8 — UDP DNS LAN->WAN with SNAT masquerade
# ---------------------------------------------------------------------------

class TestFlowE5F6A7B8:
    def test_protocol(self, report):
        flow = get_flow(report, "e5f6a7b8")
        assert flow["protocol"] == "udp"

    def test_addresses(self, report):
        flow = get_flow(report, "e5f6a7b8")
        assert flow["src_addr"] == "192.168.10.50"
        assert flow["dst_addr"] == "1.1.1.1"

    def test_ports(self, report):
        flow = get_flow(report, "e5f6a7b8")
        assert flow["src_port"] == 49152
        assert flow["dst_port"] == 53

    def test_zones(self, report):
        flow = get_flow(report, "e5f6a7b8")
        assert flow["from_zone"] == "LAN"
        assert flow["to_zone"] == "WAN"

    def test_verdict_and_compliance(self, report):
        flow = get_flow(report, "e5f6a7b8")
        assert flow["verdict"] == "accept"
        assert flow["policy_compliant"] is True

    def test_nat(self, report):
        flow = get_flow(report, "e5f6a7b8")
        assert flow["nat_type"] == "snat"


# ---------------------------------------------------------------------------
# Flow: c9d0e1f2 — TCP WAN->DMZ with DNAT 8080->80
# ---------------------------------------------------------------------------

class TestFlowC9D0E1F2:
    def test_protocol(self, report):
        flow = get_flow(report, "c9d0e1f2")
        assert flow["protocol"] == "tcp"

    def test_original_addresses(self, report):
        flow = get_flow(report, "c9d0e1f2")
        assert flow["src_addr"] == "198.51.100.99"
        assert flow["dst_addr"] == "10.0.0.1"

    def test_original_ports(self, report):
        flow = get_flow(report, "c9d0e1f2")
        assert flow["src_port"] == 12345
        assert flow["dst_port"] == 8080

    def test_zones(self, report):
        flow = get_flow(report, "c9d0e1f2")
        assert flow["from_zone"] == "WAN"
        assert flow["to_zone"] == "DMZ"

    def test_verdict_and_compliance(self, report):
        flow = get_flow(report, "c9d0e1f2")
        assert flow["verdict"] == "accept"
        assert flow["policy_compliant"] is True

    def test_nat(self, report):
        flow = get_flow(report, "c9d0e1f2")
        assert flow["nat_type"] == "dnat"


# ---------------------------------------------------------------------------
# Flow: 13243546 — TCP LAN->DMZ SSH, correctly dropped
# ---------------------------------------------------------------------------

class TestFlow13243546:
    def test_protocol(self, report):
        flow = get_flow(report, "13243546")
        assert flow["protocol"] == "tcp"

    def test_addresses(self, report):
        flow = get_flow(report, "13243546")
        assert flow["src_addr"] == "192.168.10.50"
        assert flow["dst_addr"] == "172.16.0.10"

    def test_ports(self, report):
        flow = get_flow(report, "13243546")
        assert flow["dst_port"] == 22

    def test_zones(self, report):
        flow = get_flow(report, "13243546")
        assert flow["from_zone"] == "LAN"
        assert flow["to_zone"] == "DMZ"

    def test_verdict_and_compliance(self, report):
        flow = get_flow(report, "13243546")
        assert flow["verdict"] == "drop"
        assert flow["policy_compliant"] is True


# ---------------------------------------------------------------------------
# Flow: 57687980 — TCP DMZ->LAN MySQL — POLICY VIOLATION
# ---------------------------------------------------------------------------

class TestFlow57687980:
    def test_protocol(self, report):
        flow = get_flow(report, "57687980")
        assert flow["protocol"] == "tcp"

    def test_addresses(self, report):
        flow = get_flow(report, "57687980")
        assert flow["src_addr"] == "172.16.0.10"
        assert flow["dst_addr"] == "192.168.10.50"

    def test_ports(self, report):
        flow = get_flow(report, "57687980")
        assert flow["dst_port"] == 3306

    def test_zones(self, report):
        flow = get_flow(report, "57687980")
        assert flow["from_zone"] == "DMZ"
        assert flow["to_zone"] == "LAN"

    def test_violation(self, report):
        flow = get_flow(report, "57687980")
        assert flow["verdict"] == "accept"
        assert flow["policy_compliant"] is False


# ---------------------------------------------------------------------------
# Flow: 9a8b7c6d — ICMP LAN->WAN with SNAT masquerade
# ---------------------------------------------------------------------------

class TestFlow9A8B7C6D:
    def test_protocol(self, report):
        flow = get_flow(report, "9a8b7c6d")
        assert flow["protocol"] == "icmp"

    def test_addresses(self, report):
        flow = get_flow(report, "9a8b7c6d")
        assert flow["src_addr"] == "192.168.10.50"
        assert flow["dst_addr"] == "8.8.8.8"

    def test_ports_null(self, report):
        flow = get_flow(report, "9a8b7c6d")
        assert flow["src_port"] is None
        assert flow["dst_port"] is None

    def test_zones(self, report):
        flow = get_flow(report, "9a8b7c6d")
        assert flow["from_zone"] == "LAN"
        assert flow["to_zone"] == "WAN"

    def test_verdict_and_compliance(self, report):
        flow = get_flow(report, "9a8b7c6d")
        assert flow["verdict"] == "accept"
        assert flow["policy_compliant"] is True

    def test_nat(self, report):
        flow = get_flow(report, "9a8b7c6d")
        assert flow["nat_type"] == "snat"


# ---------------------------------------------------------------------------
# Flow: 0f1e2d3c — TCP LAN->DMZ HTTP
# ---------------------------------------------------------------------------

class TestFlow0F1E2D3C:
    def test_protocol(self, report):
        flow = get_flow(report, "0f1e2d3c")
        assert flow["protocol"] == "tcp"

    def test_addresses(self, report):
        flow = get_flow(report, "0f1e2d3c")
        assert flow["src_addr"] == "192.168.10.50"
        assert flow["dst_addr"] == "172.16.0.10"

    def test_ports(self, report):
        flow = get_flow(report, "0f1e2d3c")
        assert flow["dst_port"] == 80

    def test_zones(self, report):
        flow = get_flow(report, "0f1e2d3c")
        assert flow["from_zone"] == "LAN"
        assert flow["to_zone"] == "DMZ"

    def test_verdict_and_compliance(self, report):
        flow = get_flow(report, "0f1e2d3c")
        assert flow["verdict"] == "accept"
        assert flow["policy_compliant"] is True


# ---------------------------------------------------------------------------
# Flow: 4b5a6978 — TCP WAN->LAN RDP via DNAT — POLICY VIOLATION
# ---------------------------------------------------------------------------

class TestFlow4B5A6978:
    def test_protocol(self, report):
        flow = get_flow(report, "4b5a6978")
        assert flow["protocol"] == "tcp"

    def test_original_addresses(self, report):
        flow = get_flow(report, "4b5a6978")
        assert flow["src_addr"] == "198.51.100.77"
        assert flow["dst_addr"] == "10.0.0.1"

    def test_original_ports(self, report):
        flow = get_flow(report, "4b5a6978")
        assert flow["dst_port"] == 3389

    def test_zones(self, report):
        flow = get_flow(report, "4b5a6978")
        assert flow["from_zone"] == "WAN"
        assert flow["to_zone"] == "LAN"

    def test_nat(self, report):
        flow = get_flow(report, "4b5a6978")
        assert flow["nat_type"] == "dnat"

    def test_violation(self, report):
        flow = get_flow(report, "4b5a6978")
        assert flow["verdict"] == "accept"
        assert flow["policy_compliant"] is False


# ---------------------------------------------------------------------------
# Policy violations
# ---------------------------------------------------------------------------

class TestPolicyViolations:
    def test_violation_count(self, report):
        assert len(report["policy_violations"]) == 2

    def test_violation_trace_ids(self, report):
        ids = {v["trace_id"] for v in report["policy_violations"]}
        assert ids == {"57687980", "4b5a6978"}

    def test_violations_have_required_fields(self, report):
        required = {"trace_id", "from_zone", "to_zone",
                     "expected_action", "actual_verdict"}
        for v in report["policy_violations"]:
            missing = required - set(v.keys())
            assert not missing, f"Violation {v.get('trace_id', '?')} missing: {missing}"

    def test_dmz_lan_violation_detail(self, report):
        v = next(
            x for x in report["policy_violations"] if x["trace_id"] == "57687980"
        )
        assert v["from_zone"] == "DMZ"
        assert v["to_zone"] == "LAN"
        assert v["expected_action"] == "drop"
        assert v["actual_verdict"] == "accept"

    def test_wan_lan_violation_detail(self, report):
        v = next(
            x for x in report["policy_violations"] if x["trace_id"] == "4b5a6978"
        )
        assert v["from_zone"] == "WAN"
        assert v["to_zone"] == "LAN"
        assert v["expected_action"] == "drop"
        assert v["actual_verdict"] == "accept"


# ---------------------------------------------------------------------------
# Stale rules
# ---------------------------------------------------------------------------

class TestStaleRules:
    def test_stale_rules_count(self, report):
        assert len(report["stale_rules"]) == 3

    def test_stale_rule_handles(self, report):
        handles = {r["handle"] for r in report["stale_rules"]}
        assert handles == {56, 115, 130}

    def test_stale_rules_have_required_fields(self, report):
        required = {"handle", "table", "chain"}
        for r in report["stale_rules"]:
            missing = required - set(r.keys())
            assert not missing, f"Stale rule handle={r.get('handle')} missing: {missing}"

    def test_stale_handle_56(self, report):
        r = next(x for x in report["stale_rules"] if x["handle"] == 56)
        assert r["table"] == "vyos_nat"
        assert r["chain"] == "VYOS_PRE_DNAT_HOOK"

    def test_stale_handle_115(self, report):
        r = next(x for x in report["stale_rules"] if x["handle"] == 115)
        assert r["table"] == "vyos_filter"
        assert r["chain"] == "VYOS_FORWARD_filter"

    def test_stale_handle_130(self, report):
        r = next(x for x in report["stale_rules"] if x["handle"] == 130)
        assert r["table"] == "vyos_filter"
        assert r["chain"] == "VYOS_FORWARD_filter"


# ---------------------------------------------------------------------------
# Conntrack anomalies
# ---------------------------------------------------------------------------

class TestConntrackAnomalies:
    def test_anomaly_count(self, report):
        assert len(report["conntrack_anomalies"]) == 3

    def test_anomalies_have_required_fields(self, report):
        required = {"protocol", "src", "dst", "sport", "dport"}
        for a in report["conntrack_anomalies"]:
            missing = required - set(a.keys())
            assert not missing, f"Anomaly {a.get('src','?')} missing: {missing}"

    def test_wan_ssh_anomaly(self, report):
        match = [a for a in report["conntrack_anomalies"]
                 if a["dst"] == "10.0.0.1" and a["dport"] == 22]
        assert len(match) == 1
        a = match[0]
        assert a["protocol"] == "tcp"
        assert a["src"] == "10.20.30.40"
        assert a["sport"] == 9999

    def test_dmz_lan_postgres_anomaly(self, report):
        match = [a for a in report["conntrack_anomalies"]
                 if a["dport"] == 5432]
        assert len(match) == 1
        a = match[0]
        assert a["protocol"] == "tcp"
        assert a["src"] == "172.16.0.10"
        assert a["dst"] == "192.168.10.100"
        assert a["sport"] == 44444

    def test_dmz_snmp_anomaly(self, report):
        match = [a for a in report["conntrack_anomalies"]
                 if a["dport"] == 161]
        assert len(match) == 1
        a = match[0]
        assert a["protocol"] == "udp"
        assert a["src"] == "172.16.0.10"
        assert a["dst"] == "10.0.0.1"
        assert a["sport"] == 12345


# ---------------------------------------------------------------------------
# Chain paths
# ---------------------------------------------------------------------------

class TestChainPaths:
    def test_chain_path_ordering(self, report):
        flow = get_flow(report, "a1b2c3d4")
        path = flow["chain_path"]
        raw_indices = [i for i, c in enumerate(path) if "raw" in c.lower()]
        fwd_indices = [
            i for i, c in enumerate(path)
            if "forward" in c.lower() or "FORWARD" in c
        ]
        assert len(raw_indices) > 0, "No raw chain in path"
        assert len(fwd_indices) > 0, "No forward chain in path"
        assert min(raw_indices) < min(fwd_indices)

    def test_dnat_flow_has_nat_chain(self, report):
        flow = get_flow(report, "c9d0e1f2")
        path_str = " ".join(flow["chain_path"]).lower()
        assert "nat" in path_str or "dnat" in path_str

    def test_snat_flow_has_postrouting_nat(self, report):
        flow = get_flow(report, "a1b2c3d4")
        path_str = " ".join(flow["chain_path"]).lower()
        assert "nat" in path_str or "snat" in path_str
