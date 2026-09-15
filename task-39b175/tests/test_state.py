
"""Verify forensic analysis, rule evaluation, and detection engineering output."""

import json
import os
import re

import pytest

REPORT_DIR = "/app/report"


@pytest.fixture
def findings():
    path = os.path.join(REPORT_DIR, "findings.json")
    assert os.path.isfile(path), f"findings.json not found at {path}"
    with open(path) as f:
        data = json.load(f)
    return data


@pytest.fixture
def exfil_text():
    path = os.path.join(REPORT_DIR, "exfiltrated_data.txt")
    assert os.path.isfile(path), f"exfiltrated_data.txt not found at {path}"
    with open(path) as f:
        return f.read()


@pytest.fixture
def rule_eval():
    path = os.path.join(REPORT_DIR, "rule_evaluation.json")
    assert os.path.isfile(path), f"rule_evaluation.json not found at {path}"
    with open(path) as f:
        data = json.load(f)
    return data


@pytest.fixture
def detection_rules():
    path = os.path.join(REPORT_DIR, "detection_rules.rules")
    assert os.path.isfile(path), f"detection_rules.rules not found at {path}"
    with open(path) as f:
        return f.read()


# ---- findings.json tests ----


class TestAttackerProfile:
    def test_attacker_ip(self, findings):
        assert findings.get("attacker_ip") == "10.13.37.100"

    def test_victim_ip(self, findings):
        assert findings.get("victim_ip") == "192.168.1.50"

    def test_c2_dns_server(self, findings):
        assert findings.get("c2_dns_server") == "198.51.100.53"

    def test_tunnel_domain(self, findings):
        td = findings.get("tunnel_domain", "")
        assert "c2-ops.net" in td, f"Expected 'c2-ops.net' in tunnel_domain, got '{td}'"


class TestReconnaissance:
    def test_open_ports(self, findings):
        ports = findings.get("open_ports", [])
        port_set = set(int(p) for p in ports)
        expected = {22, 80, 3306, 8080}
        assert port_set == expected, f"Expected open ports {expected}, got {port_set}"


class TestExploitation:
    def test_sqli_has_union(self, findings):
        payload = findings.get("sqli_payload", "")
        assert "UNION" in payload.upper(), f"Expected UNION in sqli_payload: {payload}"

    def test_sqli_has_select(self, findings):
        payload = findings.get("sqli_payload", "")
        assert "SELECT" in payload.upper(), f"Expected SELECT in sqli_payload: {payload}"

    def test_sqli_targets_table(self, findings):
        payload = findings.get("sqli_payload", "")
        upper = payload.upper()
        assert "USERS" in upper or "SECRETS" in upper, (
            f"Expected users or secrets table reference in sqli_payload: {payload}"
        )

    def test_sqli_tool(self, findings):
        tool = findings.get("sqli_tool", "")
        assert "sqlmap" in tool.lower(), f"Expected sqlmap in sqli_tool: {tool}"


class TestPostExploitation:
    def test_reverse_shell_port(self, findings):
        port = findings.get("reverse_shell_port")
        assert int(port) == 4444, f"Expected reverse_shell_port=4444, got {port}"

    def test_exfiltration_method(self, findings):
        method = findings.get("exfiltration_method", "")
        assert "dns" in method.lower(), (
            f"Expected 'dns' in exfiltration_method: {method}"
        )

    def test_compromised_creds_admin(self, findings):
        creds = findings.get("compromised_credentials", {})
        assert creds.get("admin") == "xK9#mR2$vL5@nQ8", (
            f"admin credential mismatch: {creds.get('admin')}"
        )

    def test_compromised_creds_app_svc(self, findings):
        creds = findings.get("compromised_credentials", {})
        assert creds.get("app_svc") == "Pr0d_Db_2024!", (
            f"app_svc credential mismatch: {creds.get('app_svc')}"
        )

    def test_compromised_creds_backup(self, findings):
        creds = findings.get("compromised_credentials", {})
        assert creds.get("backup_usr") == "b4ckup_r3st0re", (
            f"backup_usr credential mismatch: {creds.get('backup_usr')}"
        )

    def test_compromised_creds_monitor(self, findings):
        creds = findings.get("compromised_credentials", {})
        assert creds.get("monitor") == "m0n1t0r_@gent", (
            f"monitor credential mismatch: {creds.get('monitor')}"
        )


# ---- exfiltrated_data.txt tests ----


class TestExfiltratedData:
    def test_contains_start_marker(self, exfil_text):
        assert "EXFIL_START" in exfil_text

    def test_contains_end_marker(self, exfil_text):
        assert "EXFIL_END" in exfil_text

    def test_contains_hostname(self, exfil_text):
        assert "hostname=webprod01" in exfil_text

    def test_contains_db_user(self, exfil_text):
        assert "db_user=app_admin" in exfil_text

    def test_contains_db_pass(self, exfil_text):
        assert "db_pass=xK9#mR2" in exfil_text

    def test_contains_shadow_hash(self, exfil_text):
        assert "shadow_root=$6$rounds=656000" in exfil_text

    def test_contains_master_key(self, exfil_text):
        assert "master_key=a1b2c3d4e5f6a7b8" in exfil_text

    def test_contains_api_token(self, exfil_text):
        assert "api_token=eyJhbGciOiJIUzI1NiJ9" in exfil_text


# ---- rule_evaluation.json tests ----


class TestRuleEvaluationStructure:
    """Verify that all six candidate rules are evaluated."""

    def test_has_all_rule_keys(self, rule_eval):
        for key in ["R1", "R2", "R3", "R4", "R5", "R6"]:
            assert key in rule_eval, f"Missing evaluation for {key}"

    def test_all_rules_have_required_fields(self, rule_eval):
        for key in ["R1", "R2", "R3", "R4", "R5", "R6"]:
            entry = rule_eval[key]
            assert "fires_on_attack_traffic" in entry, f"{key} missing fires_on_attack_traffic"
            assert "verdict" in entry, f"{key} missing verdict"
            assert "primary_flaw" in entry, f"{key} missing primary_flaw"

    def test_verdicts_are_valid(self, rule_eval):
        valid = {"effective", "partially_effective", "ineffective"}
        for key in ["R1", "R2", "R3", "R4", "R5", "R6"]:
            v = rule_eval[key]["verdict"]
            assert v in valid, f"{key} verdict '{v}' not in {valid}"


class TestRuleEvaluationCorrectness:
    """Verify the solver correctly judged each rule's effectiveness."""

    # R1 targets 198.51.100.53:53 — matches the C2 DNS server, so it fires
    def test_r1_fires_on_attack(self, rule_eval):
        assert rule_eval["R1"]["fires_on_attack_traffic"] is True, (
            "R1 targets the correct C2 DNS server IP and should fire"
        )

    def test_r1_not_ineffective(self, rule_eval):
        assert rule_eval["R1"]["verdict"] in ("effective", "partially_effective"), (
            "R1 matches the C2 server; it fires and should not be rated ineffective"
        )

    # R2 targets port 443 but the SQLi happened on port 80 — does NOT fire
    def test_r2_does_not_fire(self, rule_eval):
        assert rule_eval["R2"]["fires_on_attack_traffic"] is False, (
            "R2 monitors port 443 but attack used port 80; should not fire"
        )

    def test_r2_is_ineffective(self, rule_eval):
        assert rule_eval["R2"]["verdict"] == "ineffective", (
            "R2 cannot detect the attack (wrong port); must be ineffective"
        )

    # R3 checks inbound to HOME_NET:4444 but reverse shell is outbound FROM
    # victim — does NOT fire
    def test_r3_does_not_fire(self, rule_eval):
        assert rule_eval["R3"]["fires_on_attack_traffic"] is False, (
            "R3 checks wrong direction — reverse shell SYN goes FROM victim, "
            "not TO victim"
        )

    def test_r3_is_ineffective(self, rule_eval):
        assert rule_eval["R3"]["verdict"] == "ineffective", (
            "R3 has reversed direction for reverse shell; must be ineffective"
        )

    # R4 targets 8.8.8.8 but tunnel uses 198.51.100.53 — does NOT fire
    def test_r4_does_not_fire(self, rule_eval):
        assert rule_eval["R4"]["fires_on_attack_traffic"] is False, (
            "R4 monitors 8.8.8.8 but tunnel queries go to 198.51.100.53"
        )

    def test_r4_is_ineffective(self, rule_eval):
        assert rule_eval["R4"]["verdict"] == "ineffective", (
            "R4 targets the wrong DNS server; must be ineffective"
        )

    # R5 detects SYN scans from external — fires on the observed scan
    def test_r5_fires_on_attack(self, rule_eval):
        assert rule_eval["R5"]["fires_on_attack_traffic"] is True, (
            "R5 detects SYN packets from external which matches the scan"
        )

    def test_r5_not_ineffective(self, rule_eval):
        assert rule_eval["R5"]["verdict"] in ("effective", "partially_effective"), (
            "R5 fires on the scan; should not be rated ineffective"
        )

    # R6 uses dsize threshold which catches long DNS tunnel queries
    def test_r6_fires_on_attack(self, rule_eval):
        assert rule_eval["R6"]["fires_on_attack_traffic"] is True, (
            "R6 dsize threshold should fire on the longer DNS tunnel queries"
        )

    def test_r6_not_ineffective(self, rule_eval):
        assert rule_eval["R6"]["verdict"] in ("effective", "partially_effective"), (
            "R6 fires on tunnel queries; should not be rated ineffective"
        )


# ---- detection_rules.rules tests ----


class TestDetectionRulesStructure:
    """Verify the created detection ruleset has proper Snort format."""

    def test_has_minimum_rules(self, detection_rules):
        alert_lines = [
            l for l in detection_rules.split("\n")
            if l.strip().startswith("alert")
        ]
        assert len(alert_lines) >= 4, (
            f"Expected at least 4 alert rules, found {len(alert_lines)}"
        )

    def test_all_rules_have_sid(self, detection_rules):
        alert_lines = [
            l for l in detection_rules.split("\n")
            if l.strip().startswith("alert")
        ]
        for line in alert_lines:
            assert "sid:" in line, f"Rule missing sid: {line[:80]}"

    def test_all_rules_have_msg(self, detection_rules):
        alert_lines = [
            l for l in detection_rules.split("\n")
            if l.strip().startswith("alert")
        ]
        for line in alert_lines:
            assert "msg:" in line, f"Rule missing msg: {line[:80]}"


class TestDetectionRulesCoverage:
    """Verify the ruleset covers all four observed attack phases."""

    def test_covers_reconnaissance(self, detection_rules):
        lower = detection_rules.lower()
        assert any(w in lower for w in ["scan", "recon", "probe"]), (
            "Detection rules must include a rule for reconnaissance/scanning"
        )

    def test_covers_exploitation(self, detection_rules):
        lower = detection_rules.lower()
        assert any(w in lower for w in ["sql", "injection", "union"]), (
            "Detection rules must include a rule for SQL injection"
        )

    def test_covers_reverse_shell_port(self, detection_rules):
        assert "4444" in detection_rules, (
            "Detection rules must reference reverse shell port 4444"
        )

    def test_covers_reverse_shell_concept(self, detection_rules):
        lower = detection_rules.lower()
        assert any(w in lower for w in ["reverse", "shell", "callback", "backdoor"]), (
            "Detection rules must reference reverse shell / callback concept"
        )

    def test_covers_dns_exfiltration(self, detection_rules):
        lower = detection_rules.lower()
        has_dns = "dns" in lower
        has_exfil = any(w in lower for w in ["tunnel", "exfil", "c2"])
        assert has_dns and has_exfil, (
            "Detection rules must include a rule for DNS tunnel exfiltration"
        )

    def test_references_attack_infrastructure(self, detection_rules):
        has_c2_ip = "198.51.100.53" in detection_rules
        has_c2_domain = "c2-ops" in detection_rules
        assert has_c2_ip or has_c2_domain, (
            "Detection rules must reference the C2 infrastructure "
            "(198.51.100.53 or c2-ops domain)"
        )
