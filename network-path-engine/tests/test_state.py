
import json
import os
import pytest


@pytest.fixture(scope="module")
def report():
    path = "/app/report.json"
    assert os.path.exists(path), "report.json not found at /app/report.json"
    with open(path) as f:
        data = json.load(f)
    return data


# ---------------------------------------------------------------------------
# Structural integrity
# ---------------------------------------------------------------------------
class TestStructure:
    def test_all_top_level_keys(self, report):
        required = {
            "attack_timeline", "attacker_infrastructure", "compromised_hosts",
            "exfiltrated_data", "network_anomalies", "indicators_of_compromise",
            "traffic_summary",
        }
        missing = required - set(report.keys())
        assert not missing, f"Missing top-level keys: {missing}"


# ---------------------------------------------------------------------------
# Attack timeline
# ---------------------------------------------------------------------------
class TestAttackTimeline:
    EXPECTED_PHASES = [
        "reconnaissance", "initial_access", "c2_establishment",
        "internal_reconnaissance", "lateral_movement", "data_access",
        "data_exfiltration", "persistence",
    ]

    def test_timeline_is_list(self, report):
        assert isinstance(report["attack_timeline"], list)
        assert len(report["attack_timeline"]) >= 8

    def test_all_phases_present(self, report):
        phases = {p["phase"] for p in report["attack_timeline"]}
        for expected in self.EXPECTED_PHASES:
            assert expected in phases, f"Missing attack phase: {expected}"

    def test_phase_chronological_order(self, report):
        """Phases must appear in the order the attack progressed."""
        phases = [p["phase"] for p in report["attack_timeline"]]
        for i in range(len(self.EXPECTED_PHASES) - 1):
            a, b = self.EXPECTED_PHASES[i], self.EXPECTED_PHASES[i + 1]
            if a in phases and b in phases:
                assert phases.index(a) < phases.index(b), \
                    f"{a} must precede {b}"

    def test_recon_source(self, report):
        recon = next(p for p in report["attack_timeline"]
                     if p["phase"] == "reconnaissance")
        assert recon["source_ip"] == "203.0.113.50"

    def test_recon_target(self, report):
        recon = next(p for p in report["attack_timeline"]
                     if p["phase"] == "reconnaissance")
        assert "10.0.1.10" in json.dumps(recon)

    def test_initial_access_source(self, report):
        phase = next(p for p in report["attack_timeline"]
                     if p["phase"] == "initial_access")
        assert phase["source_ip"] == "203.0.113.50"

    def test_initial_access_target(self, report):
        phase = next(p for p in report["attack_timeline"]
                     if p["phase"] == "initial_access")
        assert "10.0.1.10" in json.dumps(phase)

    def test_c2_source(self, report):
        phase = next(p for p in report["attack_timeline"]
                     if p["phase"] == "c2_establishment")
        assert phase["source_ip"] == "10.0.1.10"

    def test_internal_recon_source(self, report):
        phase = next(p for p in report["attack_timeline"]
                     if p["phase"] == "internal_reconnaissance")
        assert phase["source_ip"] == "10.0.1.10"

    def test_lateral_movement_endpoints(self, report):
        phase = next(p for p in report["attack_timeline"]
                     if p["phase"] == "lateral_movement")
        text = json.dumps(phase)
        assert "10.0.1.10" in text, "lateral_movement must reference source 10.0.1.10"
        assert "10.0.2.20" in text, "lateral_movement must reference target 10.0.2.20"

    def test_data_access_target(self, report):
        phase = next(p for p in report["attack_timeline"]
                     if p["phase"] == "data_access")
        assert "10.0.3.10" in json.dumps(phase)

    def test_exfiltration_source(self, report):
        phase = next(p for p in report["attack_timeline"]
                     if p["phase"] == "data_exfiltration")
        assert phase["source_ip"] == "10.0.2.20"

    def test_persistence_technique(self, report):
        phase = next(p for p in report["attack_timeline"]
                     if p["phase"] == "persistence")
        text = json.dumps(phase).lower()
        assert "arp" in text or "10.0.2.20" in text


# ---------------------------------------------------------------------------
# Attacker infrastructure
# ---------------------------------------------------------------------------
class TestAttackerInfrastructure:
    def test_external_ip(self, report):
        assert report["attacker_infrastructure"]["external_ip"] == "203.0.113.50"

    def test_c2_domains(self, report):
        domains = [d.lower().rstrip(".")
                   for d in report["attacker_infrastructure"]["c2_domains"]]
        assert "c2.evil.example.com" in domains

    def test_exfil_domains(self, report):
        domains = [d.lower().rstrip(".")
                   for d in report["attacker_infrastructure"]["exfil_domains"]]
        assert "exfil.evil.example.com" in domains


# ---------------------------------------------------------------------------
# Compromised hosts
# ---------------------------------------------------------------------------
class TestCompromisedHosts:
    def test_web_server_compromised(self, report):
        ips = {h["ip"] for h in report["compromised_hosts"]}
        assert "10.0.1.10" in ips

    def test_workstation_compromised(self, report):
        ips = {h["ip"] for h in report["compromised_hosts"]}
        assert "10.0.2.20" in ips

    def test_exactly_two_hosts(self, report):
        assert len(report["compromised_hosts"]) == 2

    def test_methods_present(self, report):
        for h in report["compromised_hosts"]:
            assert "method" in h and h["method"], \
                f"Missing compromise method for {h.get('ip')}"


# ---------------------------------------------------------------------------
# Exfiltrated data — critical expert-level test
# ---------------------------------------------------------------------------
class TestExfiltratedData:
    def test_decoded_data(self, report):
        """Solver must decode base64 from DNS subdomain labels and concatenate."""
        assert report["exfiltrated_data"] == "CONFIDENTIAL:customer_db_dump_2024"


# ---------------------------------------------------------------------------
# Network anomalies
# ---------------------------------------------------------------------------
class TestNetworkAnomalies:
    VALID_TYPES = {"syn_scan", "dns_tunneling", "arp_poisoning", "cross_vlan_access"}

    def test_anomalies_is_list(self, report):
        assert isinstance(report["network_anomalies"], list)

    def test_syn_scan_detected(self, report):
        types = {a["type"] for a in report["network_anomalies"]}
        assert "syn_scan" in types

    def test_dns_tunneling_detected(self, report):
        types = {a["type"] for a in report["network_anomalies"]}
        assert "dns_tunneling" in types

    def test_arp_poisoning_detected(self, report):
        types = {a["type"] for a in report["network_anomalies"]}
        assert "arp_poisoning" in types

    def test_cross_vlan_detected(self, report):
        types = {a["type"] for a in report["network_anomalies"]}
        assert "cross_vlan_access" in types

    def test_no_invalid_types(self, report):
        for a in report["network_anomalies"]:
            assert a["type"] in self.VALID_TYPES, \
                f"Invalid anomaly type: {a['type']}"

    def test_anomaly_details_present(self, report):
        for a in report["network_anomalies"]:
            assert "details" in a, f"Anomaly {a['type']} missing details"
            assert isinstance(a["details"], dict)

    def test_arp_poisoning_details(self, report):
        """ARP poisoning must identify the spoofed gateway or attacker MAC."""
        arp = [a for a in report["network_anomalies"]
               if a["type"] == "arp_poisoning"]
        text = json.dumps(arp).lower()
        assert "10.0.2.1" in text or "02:00:02:00:02:14" in text


# ---------------------------------------------------------------------------
# Indicators of compromise
# ---------------------------------------------------------------------------
class TestIndicatorsOfCompromise:
    def test_malicious_ips(self, report):
        ips = report["indicators_of_compromise"]["malicious_ips"]
        assert "203.0.113.50" in ips

    def test_malicious_domains(self, report):
        domains = [d.lower().rstrip(".")
                   for d in report["indicators_of_compromise"]["malicious_domains"]]
        assert "c2.evil.example.com" in domains
        assert "exfil.evil.example.com" in domains

    def test_compromised_ips(self, report):
        ips = report["indicators_of_compromise"]["compromised_ips"]
        assert "10.0.1.10" in ips
        assert "10.0.2.20" in ips

    def test_targeted_services(self, report):
        services = report["indicators_of_compromise"]["targeted_services"]
        db_found = any(
            s.get("ip") == "10.0.3.10" and int(s.get("port", 0)) == 3306
            for s in services
        )
        assert db_found, "Must identify MySQL (10.0.3.10:3306) as targeted service"


# ---------------------------------------------------------------------------
# Traffic summary
# ---------------------------------------------------------------------------
class TestTrafficSummary:
    def test_total_packets(self, report):
        assert report["traffic_summary"]["total_packets"] == 40

    def test_per_capture_perimeter(self, report):
        assert report["traffic_summary"]["per_capture"]["perimeter"] == 14

    def test_per_capture_dmz(self, report):
        assert report["traffic_summary"]["per_capture"]["dmz_switch"] == 6

    def test_per_capture_core(self, report):
        assert report["traffic_summary"]["per_capture"]["core_switch"] == 12

    def test_per_capture_internal(self, report):
        assert report["traffic_summary"]["per_capture"]["internal_monitor"] == 8

    def test_tcp_count(self, report):
        assert report["traffic_summary"]["protocol_counts"]["tcp"] == 26

    def test_udp_count(self, report):
        assert report["traffic_summary"]["protocol_counts"]["udp"] == 8

    def test_arp_count(self, report):
        assert report["traffic_summary"]["protocol_counts"]["arp"] == 6

    def test_protocol_sum_equals_total(self, report):
        pc = report["traffic_summary"]["protocol_counts"]
        total = sum(pc.values())
        assert total == report["traffic_summary"]["total_packets"], \
            f"Protocol sum ({total}) != total ({report['traffic_summary']['total_packets']})"
