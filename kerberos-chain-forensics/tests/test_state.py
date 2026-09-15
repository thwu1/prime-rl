
import json
import os
import pytest
import yaml

ATTACK_FILE = "/app/answers/attack_analysis.json"
ASSESSMENT_FILE = "/app/answers/security_assessment.json"


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def attack():
    assert os.path.exists(ATTACK_FILE), (
        f"{ATTACK_FILE} does not exist."
    )
    with open(ATTACK_FILE) as f:
        data = json.load(f)
    assert isinstance(data, dict)
    return data


@pytest.fixture
def assessment():
    assert os.path.exists(ASSESSMENT_FILE), (
        f"{ASSESSMENT_FILE} does not exist."
    )
    with open(ASSESSMENT_FILE) as f:
        data = json.load(f)
    assert isinstance(data, dict)
    return data


# ============================================================
# Part 1: Attack Reconstruction (same deterministic checks)
# ============================================================
class TestAttackReconstruction:
    def test_initial_compromise(self, attack):
        val = attack.get("initial_compromise", "").strip().lower()
        assert val == "t.chen", f"Expected 't.chen', got '{val}'"

    def test_compromised_service_account(self, attack):
        val = attack.get("compromised_service_account", "").strip().lower()
        assert val == "svc_sqlprod", f"Expected 'svc_sqlprod', got '{val}'"

    def test_compromised_spn(self, attack):
        val = attack.get("compromised_spn", "").strip().lower()
        assert "mssqlsvc" in val, f"SPN must contain 'MSSQLSvc', got '{val}'"
        assert "sql01" in val, f"SPN must contain 'SQL01', got '{val}'"

    def test_recovered_password(self, attack):
        val = attack.get("recovered_password", "").strip()
        assert val == "Producti0n!", f"Expected 'Producti0n!', got '{val}'"

    def test_exploited_template(self, attack):
        val = attack.get("exploited_template", "").strip().lower()
        assert val == "vpnaccess", f"Expected 'VPNAccess', got '{val}'"

    def test_vulnerability_class(self, attack):
        val = attack.get("vulnerability_class", "").strip().upper().replace("-", "").replace(" ", "")
        assert val == "ESC1", f"Expected 'ESC1', got '{val}'"

    def test_impersonated_user(self, attack):
        val = attack.get("impersonated_user", "").strip().lower()
        assert val == "j.rodriguez", f"Expected 'j.rodriguez', got '{val}'"

    def test_attack_chain_mentions_kerberoasting(self, attack):
        val = attack.get("attack_chain_summary", "").lower()
        assert "kerberoast" in val, "Summary must mention Kerberoasting"

    def test_attack_chain_mentions_adcs(self, attack):
        val = attack.get("attack_chain_summary", "").lower()
        has_adcs = "adcs" in val or "ad cs" in val
        has_cert = "certificate" in val or "cert" in val
        has_esc = "esc1" in val or "esc 1" in val
        assert has_adcs or has_cert or has_esc, "Summary must mention AD CS or certificate abuse"

    def test_attack_chain_length(self, attack):
        val = attack.get("attack_chain_summary", "").strip()
        assert len(val) >= 100, f"Summary too short ({len(val)} chars)"


# ============================================================
# Part 2: Security Posture Assessment (evaluate + create)
# ============================================================
class TestAlternativeAttackPaths:
    """Evaluate: solver must identify viable escalation routes beyond the one used."""

    def test_paths_exist_and_sufficient(self, assessment):
        paths = assessment.get("alternative_attack_paths", [])
        assert isinstance(paths, list), "alternative_attack_paths must be a list"
        assert len(paths) >= 3, (
            f"Must identify at least 3 alternative attack paths, got {len(paths)}"
        )

    def test_paths_have_required_fields(self, assessment):
        paths = assessment.get("alternative_attack_paths", [])
        required = {"path_name", "technique", "entry_account_or_object", "target",
                     "risk_level", "justification"}
        for i, p in enumerate(paths):
            missing = required - set(p.keys())
            assert not missing, f"Path {i} missing fields: {missing}"
            assert p["risk_level"] in ("critical", "high", "medium", "low"), (
                f"Path {i} risk_level must be critical/high/medium/low, got '{p['risk_level']}'"
            )

    def test_identifies_constrained_delegation(self, assessment):
        paths = assessment.get("alternative_attack_paths", [])
        blob = json.dumps(paths).lower()
        has_constrained = "constrained" in blob or "s4u" in blob
        has_target = "svc_sqlprod" in blob or "db-analytics" in blob or "db_analytics" in blob
        assert has_constrained and has_target, (
            "Must identify constrained delegation abuse via svc_sqlprod to DB-ANALYTICS"
        )

    def test_identifies_unconstrained_delegation(self, assessment):
        paths = assessment.get("alternative_attack_paths", [])
        blob = json.dumps(paths).lower()
        has_unconstrained = "unconstrained" in blob
        has_target = "backup01" in blob or "dc01" in blob
        assert has_unconstrained and has_target, (
            "Must identify unconstrained delegation on BACKUP01 or DC01"
        )

    def test_identifies_dnsadmins(self, assessment):
        paths = assessment.get("alternative_attack_paths", [])
        blob = json.dumps(paths).lower()
        has_dns = "dnsadmin" in blob or "dns admin" in blob
        has_user = "m.oconnor" in blob or "oconnor" in blob
        assert has_dns and has_user, (
            "Must identify DnsAdmins abuse via m.oconnor"
        )


class TestHighestRiskMisconfiguration:
    """Evaluate: solver must judge which misconfiguration is most dangerous."""

    def test_field_exists(self, assessment):
        val = assessment.get("highest_risk_misconfiguration", "")
        assert isinstance(val, str) and len(val) >= 20, (
            "highest_risk_misconfiguration must be a substantive explanation"
        )

    def test_identifies_adcs_esc1(self, assessment):
        val = assessment.get("highest_risk_misconfiguration", "").lower()
        has_template = "vpnaccess" in val or "vpn access" in val
        has_esc = "esc1" in val or "esc 1" in val
        has_adcs = "adcs" in val or "ad cs" in val or "certificate" in val
        has_subject = "enrollee_supplies_subject" in val or "supplies subject" in val or "supply subject" in val
        assert (has_template or has_esc) and (has_adcs or has_subject), (
            "Must identify the VPNAccess ESC1 template as the highest risk misconfiguration"
        )


class TestSigmaRules:
    """Create: solver must produce valid Sigma detection rules."""

    def test_rules_exist(self, assessment):
        rules = assessment.get("sigma_rules", [])
        assert isinstance(rules, list) and len(rules) >= 1, (
            "Must provide at least 1 Sigma detection rule"
        )

    def test_rules_are_valid_yaml(self, assessment):
        rules = assessment.get("sigma_rules", [])
        for i, rule_str in enumerate(rules):
            assert isinstance(rule_str, str), f"Rule {i} must be a YAML string"
            try:
                parsed = yaml.safe_load(rule_str)
            except yaml.YAMLError as e:
                pytest.fail(f"Rule {i} is not valid YAML: {e}")
            assert isinstance(parsed, dict), f"Rule {i} YAML must parse to a dict"

    def test_rules_have_required_sections(self, assessment):
        rules = assessment.get("sigma_rules", [])
        for i, rule_str in enumerate(rules):
            parsed = yaml.safe_load(rule_str)
            for field in ("title", "logsource", "detection", "level"):
                assert field in parsed, f"Rule {i} missing required field '{field}'"
            assert isinstance(parsed["detection"], dict), (
                f"Rule {i} detection must be a dict"
            )
            assert isinstance(parsed["logsource"], dict), (
                f"Rule {i} logsource must be a dict"
            )

    def test_kerberoasting_detection_rule(self, assessment):
        rules = assessment.get("sigma_rules", [])
        found = False
        for rule_str in rules:
            parsed = yaml.safe_load(rule_str)
            blob = json.dumps(parsed).lower()
            if ("4769" in blob) and ("0x17" in blob or "rc4" in blob):
                found = True
                break
        assert found, (
            "Must include a Sigma rule detecting Kerberoasting (EventID 4769 + RC4/0x17)"
        )


class TestRemediationPlan:
    """Create: solver must design a prioritized hardening plan."""

    def test_plan_exists_and_sufficient(self, assessment):
        plan = assessment.get("remediation_plan", [])
        assert isinstance(plan, list) and len(plan) >= 4, (
            f"Must provide at least 4 remediation actions, got {len(plan)}"
        )

    def test_plan_has_required_fields(self, assessment):
        plan = assessment.get("remediation_plan", [])
        required = {"priority", "action", "target_object", "specific_change", "rationale"}
        for i, item in enumerate(plan):
            missing = required - set(item.keys())
            assert not missing, f"Remediation item {i} missing fields: {missing}"
            assert isinstance(item["priority"], int), (
                f"Remediation item {i} priority must be an integer"
            )

    def test_plan_addresses_adcs_template(self, assessment):
        plan = assessment.get("remediation_plan", [])
        blob = json.dumps(plan).lower()
        has_template = "vpnaccess" in blob or "vpn access" in blob
        has_fix = ("enrollee_supplies_subject" in blob or "supplies subject" in blob
                   or "disable" in blob or "remove" in blob or "ra-signature" in blob
                   or "ra_signature" in blob)
        assert has_template and has_fix, (
            "Remediation must address the VPNAccess template misconfiguration"
        )

    def test_plan_addresses_password_rotation(self, assessment):
        plan = assessment.get("remediation_plan", [])
        blob = json.dumps(plan).lower()
        has_account = "svc_sqlprod" in blob
        has_rotate = "rotat" in blob or "reset" in blob or "change" in blob or "new password" in blob
        assert has_account and has_rotate, (
            "Remediation must rotate/reset the svc_sqlprod password"
        )

    def test_plan_addresses_encryption(self, assessment):
        plan = assessment.get("remediation_plan", [])
        blob = json.dumps(plan).lower()
        has_rc4 = "rc4" in blob or "arcfour" in blob
        has_aes = "aes" in blob or "encryption" in blob
        assert has_rc4 or has_aes, (
            "Remediation must address disabling RC4 or enforcing AES encryption"
        )

    def test_plan_is_prioritized(self, assessment):
        plan = assessment.get("remediation_plan", [])
        priorities = [item["priority"] for item in plan]
        assert len(set(priorities)) > 1, (
            "Remediation plan must have differentiated priorities, not all the same"
        )
