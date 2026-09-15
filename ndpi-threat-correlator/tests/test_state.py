
import json
import os
import re
import pytest
from jsonschema import validate, ValidationError

REPORT_PATH = "/app/report.json"
SCHEMA_PATH = "/app/schema.json"
RULES_PATH = "/app/rules.rules"


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture
def schema():
    assert os.path.exists(SCHEMA_PATH), f"Schema not found at {SCHEMA_PATH}"
    with open(SCHEMA_PATH) as f:
        return json.load(f)


@pytest.fixture
def rules_text():
    assert os.path.exists(RULES_PATH), f"Suricata rules not found at {RULES_PATH}"
    with open(RULES_PATH) as f:
        return f.read()


def json_str(obj):
    return json.dumps(obj, default=str).lower()


# ── Schema Validation ──────────────────────────────────────────────


class TestSchemaCompliance:
    def test_report_valid_json(self, report):
        assert isinstance(report, dict), "Report must be a JSON object"

    def test_report_conforms_to_schema(self, report, schema):
        try:
            validate(instance=report, schema=schema)
        except ValidationError as e:
            pytest.fail(f"Report does not conform to schema: {e.message} at {list(e.absolute_path)}")

    def test_meta_total_flows(self, report):
        assert report["meta"]["total_flows"] == 35, (
            f"Expected 35 flows, got {report['meta']['total_flows']}"
        )

    def test_meta_data_sources(self, report):
        sources = report["meta"]["data_sources"]
        assert len(sources) >= 2, "Must list at least 2 data sources"


# ── Threat Intelligence Correlation ────────────────────────────────


class TestThreatIntelMatches:
    def test_correct_number_of_matches(self, report):
        matches = report["threat_intel_matches"]
        matched_values = {m["indicator_value"] for m in matches}
        # 5 indicators should match, 2 should not
        assert len(matched_values) == 5, (
            f"Expected 5 matched indicators, got {len(matched_values)}: {matched_values}"
        )

    def test_c2_ip_matched(self, report):
        matches = report["threat_intel_matches"]
        c2_matches = [m for m in matches if m["indicator_value"] == "185.141.27.93"]
        assert len(c2_matches) == 1, "Must match C2 IP 185.141.27.93"
        assert c2_matches[0]["indicator_type"] == "ip"
        flow_ids = c2_matches[0]["matched_flow_ids"]
        assert len(flow_ids) >= 5, f"C2 IP should match at least 5 flows, got {len(flow_ids)}"

    def test_exfil_domain_matched(self, report):
        matches = report["threat_intel_matches"]
        dom_matches = [m for m in matches if "exfil-srv" in m["indicator_value"]]
        assert len(dom_matches) == 1, "Must match exfil-srv.net domain"
        assert dom_matches[0]["indicator_type"] == "domain"
        flow_ids = dom_matches[0]["matched_flow_ids"]
        assert len(flow_ids) >= 3, f"Exfil domain should match at least 3 flows, got {len(flow_ids)}"

    def test_ja4_matched(self, report):
        matches = report["threat_intel_matches"]
        ja4_matches = [m for m in matches if m["indicator_type"] == "ja4"]
        assert len(ja4_matches) >= 1, "Must match JA4 fingerprint indicator"

    def test_darkproxy_ip_matched(self, report):
        matches = report["threat_intel_matches"]
        dp_matches = [m for m in matches if m["indicator_value"] == "198.51.100.200"]
        assert len(dp_matches) == 1, "Must match DarkProxy IP 198.51.100.200"

    def test_cert_sha1_matched(self, report):
        matches = report["threat_intel_matches"]
        cert_matches = [m for m in matches if m["indicator_type"] == "cert_sha1"]
        assert len(cert_matches) >= 1, "Must match cert SHA-1 indicator"

    def test_unmatched_indicators_excluded(self, report):
        matches = report["threat_intel_matches"]
        matched_values = {m["indicator_value"] for m in matches}
        assert "45.33.32.156" not in matched_values, "ScanBot IP should not match any flow"
        assert "malware-cdn.evil.com" not in matched_values, "MalDist domain should not match any flow"


# ── C2 Beaconing ──────────────────────────────────────────────────


class TestC2Beaconing:
    def test_c2_server_ip(self, report):
        assert report["c2_beaconing"]["server_ip"] == "185.141.27.93"

    def test_c2_server_port(self, report):
        assert report["c2_beaconing"]["server_port"] == 443

    def test_c2_beacon_count(self, report):
        assert report["c2_beaconing"]["beacon_count"] == 6, (
            f"Expected 6 beacons, got {report['c2_beaconing']['beacon_count']}"
        )

    def test_c2_mean_interval(self, report):
        interval = report["c2_beaconing"]["mean_interval_sec"]
        assert 55.0 <= interval <= 65.0, (
            f"Expected mean interval ~60s, got {interval}"
        )

    def test_c2_hostname(self, report):
        hostname = report["c2_beaconing"]["hostname"]
        assert "service-analytics" in hostname or "cdn-metrics" in hostname, (
            f"C2 hostname should reference service-analytics.net, got {hostname}"
        )

    def test_c2_ja4(self, report):
        ja4 = report["c2_beaconing"]["ja4_fingerprint"]
        assert "5b57614c22b0" in ja4, (
            f"C2 JA4 fingerprint incorrect: {ja4}"
        )


# ── DNS Exfiltration with Payload Decoding ─────────────────────────


class TestDNSExfiltration:
    def test_tunnel_domain(self, report):
        assert "exfil-srv" in report["dns_exfiltration"]["tunnel_domain"]

    def test_query_count(self, report):
        assert report["dns_exfiltration"]["query_count"] == 4

    def test_decoded_payloads_count(self, report):
        payloads = report["dns_exfiltration"]["decoded_payloads"]
        assert len(payloads) >= 4, f"Expected 4 decoded payloads, got {len(payloads)}"

    def test_decoded_johndoe(self, report):
        payloads = report["dns_exfiltration"]["decoded_payloads"]
        all_decoded = " ".join(p["decoded_text"] for p in payloads).lower()
        assert "johndoe" in all_decoded, (
            f"Must decode 'JohnDoe12345' from hex subdomain. Decoded: {all_decoded}"
        )

    def test_decoded_secretpass(self, report):
        payloads = report["dns_exfiltration"]["decoded_payloads"]
        all_decoded = " ".join(p["decoded_text"] for p in payloads).lower()
        assert "secretpass" in all_decoded, (
            f"Must decode 'SecretPass@1' from hex subdomain. Decoded: {all_decoded}"
        )

    def test_decoded_confidential(self, report):
        payloads = report["dns_exfiltration"]["decoded_payloads"]
        all_decoded = " ".join(p["decoded_text"] for p in payloads).lower()
        assert "confidential" in all_decoded, (
            f"Must decode 'Confidential' from hex subdomain. Decoded: {all_decoded}"
        )

    def test_decoded_projectalpha(self, report):
        payloads = report["dns_exfiltration"]["decoded_payloads"]
        all_decoded = " ".join(p["decoded_text"] for p in payloads).lower()
        assert "projectalpha" in all_decoded or "project" in all_decoded, (
            f"Must decode 'ProjectAlpha' from hex subdomain. Decoded: {all_decoded}"
        )

    def test_raw_labels_present(self, report):
        payloads = report["dns_exfiltration"]["decoded_payloads"]
        for p in payloads:
            assert len(p["raw_labels"]) > 10, (
                f"raw_labels should contain the hex-encoded subdomain, got: {p['raw_labels']}"
            )


# ── Credential Exposure ───────────────────────────────────────────


class TestCredentialExposure:
    def test_has_credentials(self, report):
        creds = report["credential_exposure"]
        assert len(creds) >= 2, f"Expected at least 2 credential exposures, got {len(creds)}"

    def test_admin_credential(self, report):
        creds = report["credential_exposure"]
        admin = [c for c in creds if c["username"] == "admin"]
        assert len(admin) >= 1, "Must detect 'admin' credential exposure"
        assert admin[0]["dst_ip"] == "10.0.1.100"
        assert admin[0]["dst_port"] == 80

    def test_svc_deploy_credential(self, report):
        creds = report["credential_exposure"]
        svc = [c for c in creds if "svc" in c["username"].lower() or "deploy" in c["username"].lower()]
        assert len(svc) >= 1, "Must detect 'svc-deploy' credential exposure"
        assert svc[0]["dst_port"] == 8080


# ── TLS Anomalies ─────────────────────────────────────────────────


class TestTLSAnomalies:
    def test_has_multiple_anomalies(self, report):
        anomalies = report["tls_anomalies"]
        assert len(anomalies) >= 3, (
            f"Expected at least 3 TLS anomalies, got {len(anomalies)}"
        )

    def test_excessive_validity(self, report):
        anomalies = report["tls_anomalies"]
        long_cert = [a for a in anomalies
                     if a["dst_ip"] == "203.0.113.50"
                     and ("validity" in a["anomaly_type"].lower() or "excessive" in a["anomaly_type"].lower()
                          or "long" in a["anomaly_type"].lower())]
        assert len(long_cert) >= 1, (
            "Must detect excessive certificate validity at 203.0.113.50"
        )
        assert "1000" in long_cert[0]["details"] or "validity" in long_cert[0]["details"].lower(), (
            f"Details should mention 1000-day validity: {long_cert[0]['details']}"
        )

    def test_self_signed(self, report):
        anomalies = report["tls_anomalies"]
        self_signed = [a for a in anomalies
                       if a["dst_ip"] == "198.51.100.200"
                       and ("self" in a["anomaly_type"].lower() or "sign" in a["anomaly_type"].lower())]
        assert len(self_signed) >= 1, (
            "Must detect self-signed certificate at 198.51.100.200"
        )

    def test_version_downgrade(self, report):
        anomalies = report["tls_anomalies"]
        downgrade = [a for a in anomalies
                     if a["dst_ip"] == "203.0.113.50"
                     and ("downgrade" in a["anomaly_type"].lower()
                          or "version" in a["anomaly_type"].lower())]
        assert len(downgrade) >= 1, (
            "Must detect TLS version downgrade at 203.0.113.50 "
            "(client offered TLSv1.3 but server negotiated TLSv1.2)"
        )


# ── DGA Domains ───────────────────────────────────────────────────


class TestDGADomains:
    DGA_DOMAINS = ["xkjf7qwp3m", "bvp2kd9xr", "m3ntr89xvw", "qw8fp2lk7n", "zt5mx9hj3c"]

    def test_identifies_dga_domains(self, report):
        dga = report["dga_domains"]
        found_domains = json_str(dga)
        found_count = sum(1 for d in self.DGA_DOMAINS if d in found_domains)
        assert found_count >= 4, (
            f"Expected at least 4/5 DGA domains, found {found_count}. "
            f"Missing: {[d for d in self.DGA_DOMAINS if d not in found_domains]}"
        )

    def test_entropy_values_present(self, report):
        dga = report["dga_domains"]
        for entry in dga:
            assert isinstance(entry["entropy"], (int, float)), (
                f"Entropy must be numeric, got {type(entry['entropy'])}"
            )
            assert 2.0 <= entry["entropy"] <= 5.0, (
                f"Entropy {entry['entropy']} for {entry['domain']} is outside expected range"
            )

    def test_flow_ids_valid(self, report):
        dga = report["dga_domains"]
        for entry in dga:
            assert 1 <= entry["flow_id"] <= 35, (
                f"Flow ID {entry['flow_id']} out of range"
            )


# ── Attack Timeline ───────────────────────────────────────────────


class TestAttackTimeline:
    def test_timeline_not_empty(self, report):
        timeline = report["attack_timeline"]
        assert len(timeline) >= 5, (
            f"Timeline should have at least 5 events, got {len(timeline)}"
        )

    def test_timeline_chronological(self, report):
        timeline = report["attack_timeline"]
        timestamps = [e["timestamp"] for e in timeline]
        assert timestamps == sorted(timestamps), (
            "Attack timeline must be in chronological order"
        )

    def test_timeline_covers_c2(self, report):
        timeline = report["attack_timeline"]
        s = json_str(timeline)
        assert "185.141.27.93" in s or "c2" in s or "beacon" in s, (
            "Timeline must include C2 beaconing events"
        )

    def test_timeline_covers_exfil(self, report):
        timeline = report["attack_timeline"]
        s = json_str(timeline)
        assert "exfil" in s or "tunnel" in s or "dns" in s, (
            "Timeline must include DNS exfiltration events"
        )

    def test_timeline_covers_credentials(self, report):
        timeline = report["attack_timeline"]
        s = json_str(timeline)
        assert "credential" in s or "admin" in s or "cleartext" in s or "password" in s, (
            "Timeline must include credential exposure events"
        )


# ── Suricata Rules ────────────────────────────────────────────────


class TestSuricataRules:
    def test_rules_file_exists(self):
        assert os.path.exists(RULES_PATH), f"Suricata rules file not found at {RULES_PATH}"

    def test_rules_minimum_count(self, rules_text):
        rules = [l.strip() for l in rules_text.strip().split("\n")
                 if l.strip() and not l.strip().startswith("#")]
        assert len(rules) >= 3, (
            f"Expected at least 3 Suricata rules, got {len(rules)}"
        )

    def test_rules_valid_syntax(self, rules_text):
        rules = [l.strip() for l in rules_text.strip().split("\n")
                 if l.strip() and not l.strip().startswith("#")]
        for rule in rules:
            assert rule.startswith("alert "), (
                f"Suricata rule must start with 'alert': {rule[:80]}"
            )
            assert "sid:" in rule, f"Rule missing 'sid:' keyword: {rule[:80]}"
            assert "msg:" in rule, f"Rule missing 'msg:' keyword: {rule[:80]}"
            assert "rev:" in rule, f"Rule missing 'rev:' keyword: {rule[:80]}"
            assert rule.rstrip().endswith(")"), (
                f"Rule must end with ')': {rule[-20:]}"
            )

    def test_rules_cover_c2(self, rules_text):
        rt = rules_text.lower()
        assert "185.141.27.93" in rt or "service-analytics" in rt or "cdn-metrics" in rt, (
            "Rules must include detection for C2 infrastructure"
        )

    def test_rules_cover_tunnel(self, rules_text):
        rt = rules_text.lower()
        assert "exfil-srv" in rt or "tunnel" in rt, (
            "Rules must include detection for DNS tunneling"
        )
