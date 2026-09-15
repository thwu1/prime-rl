
"""Tests for forensic log analysis: incident report, rule evaluation, and detection rules."""
import json
import os
import pytest

REPORT_PATH = "/app/incident_report.json"
RULES_PATH = "/app/detection_rules.json"
EVAL_PATH = "/app/rule_evaluation.json"

EXPECTED = {
    "attacker_ip": "198.51.100.73",
    "brute_force_start": "2024-03-15 02:14:07",
    "brute_force_success": "2024-03-15 02:47:33",
    "compromised_account": "deploy",
    "webshell_path": "/uploads/.sys_cache.php",
    "webshell_first_access": "2024-03-15 03:02:15",
    "exfiltrated_file": "/etc/shadow",
    "c2_domain": "cdn-telemetry.analytics-pool.net",
    "num_dns_exfil_queries": 15,
    "decrypted_exfil_sha256": "a6c4926d7c9a73b1c22e5d3ff00b381643676164b42b260fc9be4eca894eab6c",
}

REQUIRED_STAGES = {"initial_access", "execution", "exfiltration"}
REQUIRED_RULE_FIELDS = {"rule_id", "stage", "title", "log_source", "detection_logic", "indicator_value"}

# Ground truth IOCs that correct rules must reference per stage
STAGE_INDICATORS = {
    "initial_access": ["198.51.100.73"],
    "execution": [".sys_cache.php", "sys_cache"],
    "exfiltration": ["cdn-telemetry.analytics-pool.net", "exfil"],
}

# Log files that are valid sources per stage
STAGE_LOG_SOURCES = {
    "initial_access": ["auth.log"],
    "execution": ["access.log", "app_audit.log"],
    "exfiltration": ["dns_queries.log", "app_audit.log"],
}

# Expected verdicts for candidate rule evaluation
EXPECTED_VERDICTS = {
    "cand_ssh_any_ext_password": "noisy",
    "cand_ssh_ext_accepted": "noisy",
    "cand_ssh_brute_500": "effective",
    "cand_webshell_post_upload": "ineffective",
    "cand_php_dotfile": "effective",
    "cand_dns_analytics": "noisy",
    "cand_dns_txt_tunnel": "ineffective",
    "cand_audit_shadow_read": "effective",
}


def normalize_ts(ts):
    """Normalize timestamp: accept T or space separator."""
    if ts is None:
        return ""
    return str(ts).replace("T", " ").strip()


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture
def rules():
    assert os.path.exists(RULES_PATH), f"Detection rules not found at {RULES_PATH}"
    with open(RULES_PATH) as f:
        data = json.load(f)
    assert isinstance(data, list), "detection_rules.json must be a JSON array"
    return data


@pytest.fixture
def evaluation():
    assert os.path.exists(EVAL_PATH), f"Rule evaluation not found at {EVAL_PATH}"
    with open(EVAL_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "rule_evaluation.json must be a JSON object"
    return data


# =================== INCIDENT REPORT TESTS ===================

def test_report_has_all_fields(report):
    for key in EXPECTED:
        assert key in report, f"Missing field: {key}"


def test_attacker_ip(report):
    assert report["attacker_ip"] == EXPECTED["attacker_ip"], (
        f"Expected {EXPECTED['attacker_ip']}, got {report['attacker_ip']}")


def test_brute_force_start(report):
    assert normalize_ts(report["brute_force_start"]) == EXPECTED["brute_force_start"], (
        f"Expected {EXPECTED['brute_force_start']}, got {report['brute_force_start']}")


def test_brute_force_success(report):
    assert normalize_ts(report["brute_force_success"]) == EXPECTED["brute_force_success"], (
        f"Expected {EXPECTED['brute_force_success']}, got {report['brute_force_success']}")


def test_compromised_account(report):
    assert report["compromised_account"] == EXPECTED["compromised_account"], (
        f"Expected {EXPECTED['compromised_account']}, got {report['compromised_account']}")


def test_webshell_path(report):
    assert report["webshell_path"] == EXPECTED["webshell_path"], (
        f"Expected {EXPECTED['webshell_path']}, got {report['webshell_path']}")


def test_webshell_first_access(report):
    assert normalize_ts(report["webshell_first_access"]) == EXPECTED["webshell_first_access"], (
        f"Expected {EXPECTED['webshell_first_access']}, got {report['webshell_first_access']}")


def test_exfiltrated_file(report):
    assert report["exfiltrated_file"] == EXPECTED["exfiltrated_file"], (
        f"Expected {EXPECTED['exfiltrated_file']}, got {report['exfiltrated_file']}")


def test_c2_domain(report):
    assert report["c2_domain"] == EXPECTED["c2_domain"], (
        f"Expected {EXPECTED['c2_domain']}, got {report['c2_domain']}")


def test_num_dns_exfil_queries(report):
    assert int(report["num_dns_exfil_queries"]) == EXPECTED["num_dns_exfil_queries"], (
        f"Expected {EXPECTED['num_dns_exfil_queries']}, got {report['num_dns_exfil_queries']}")


def test_decrypted_exfil_sha256(report):
    """Critical test: proves correct key recovery and decryption."""
    actual = str(report.get("decrypted_exfil_sha256", "")).lower().strip()
    assert actual == EXPECTED["decrypted_exfil_sha256"], (
        f"SHA256 mismatch: expected {EXPECTED['decrypted_exfil_sha256']}, got {actual}")


# =================== LOG SANITY CHECKS ===================

def test_attacker_ip_in_auth_log():
    with open("/app/logs/auth.log") as f:
        content = f.read()
    assert "198.51.100.73" in content, "Attacker IP missing from auth.log"
    assert "Accepted password" in content, "No successful password login in auth.log"


def test_webshell_in_access_log():
    with open("/app/logs/access.log") as f:
        content = f.read()
    assert ".sys_cache.php" in content, "Web shell not found in access.log"


def test_c2_domain_in_dns_log():
    with open("/app/logs/dns_queries.log") as f:
        content = f.read()
    assert "cdn-telemetry.analytics-pool.net" in content, "C2 domain missing from dns_queries.log"
    assert ".exfil." in content, "Exfil subdomain pattern missing from dns_queries.log"


# =================== RULE EVALUATION TESTS ===================

def test_evaluation_all_rules_present(evaluation):
    """All 8 candidate rules must be evaluated."""
    for rid in EXPECTED_VERDICTS:
        assert rid in evaluation, f"Missing evaluation for candidate rule: {rid}"


@pytest.mark.parametrize("rule_id,expected_verdict", list(EXPECTED_VERDICTS.items()))
def test_evaluation_verdict(evaluation, rule_id, expected_verdict):
    """Each candidate rule must be classified with the correct verdict."""
    assert rule_id in evaluation, f"Missing evaluation for {rule_id}"
    entry = evaluation[rule_id]
    assert "verdict" in entry, f"Missing 'verdict' field for {rule_id}"
    actual = str(entry["verdict"]).lower().strip()
    assert actual == expected_verdict, (
        f"Rule {rule_id}: expected verdict '{expected_verdict}', got '{actual}'")


def test_evaluation_justifications_present(evaluation):
    """Each rule evaluation must include a substantive justification."""
    for rid in EXPECTED_VERDICTS:
        if rid not in evaluation:
            continue
        entry = evaluation[rid]
        assert "justification" in entry, f"Missing 'justification' field for {rid}"
        j = entry["justification"]
        assert isinstance(j, str) and len(j) >= 30, (
            f"Rule {rid}: justification must be a string of at least 30 characters, "
            f"got length {len(j) if isinstance(j, str) else 0}")


def test_evaluation_noisy_rules_identify_fp_source(evaluation):
    """Noisy rule justifications must reference concrete false-positive sources."""
    noisy_rules = {rid for rid, v in EXPECTED_VERDICTS.items() if v == "noisy"}
    fp_keywords = {
        "cand_ssh_any_ext_password": ["scanner", "scanning", "80", "multiple", "external"],
        "cand_ssh_ext_accepted": ["203.0.113.42", "contractor"],
        "cand_dns_analytics": ["analytics.google", "analytics.amplitude",
                               "cdn-analytics.pinpoint", "legitimate"],
    }
    for rid in noisy_rules:
        if rid not in evaluation:
            continue
        j = evaluation[rid].get("justification", "").lower()
        expected_kw = fp_keywords.get(rid, [])
        if expected_kw:
            assert any(kw.lower() in j for kw in expected_kw), (
                f"Noisy rule {rid} justification should reference specific false-positive "
                f"sources (expected one of: {expected_kw})")


# =================== DETECTION RULES TESTS ===================

def test_detection_rules_minimum_count(rules):
    """Must have at least 3 rules (one per required stage)."""
    assert len(rules) >= 3, f"Expected at least 3 detection rules, got {len(rules)}"


def test_detection_rules_have_required_fields(rules):
    """Every rule must have all required fields."""
    for i, rule in enumerate(rules):
        for field in REQUIRED_RULE_FIELDS:
            assert field in rule, f"Rule {i} missing required field: {field}"
            assert rule[field], f"Rule {i} has empty field: {field}"


def test_detection_rules_cover_all_stages(rules):
    """Must have at least one rule per required attack stage."""
    stages_present = {r.get("stage", "").lower().strip() for r in rules}
    for stage in REQUIRED_STAGES:
        assert stage in stages_present, (
            f"Missing detection rule for stage: {stage}. "
            f"Found stages: {stages_present}")


def test_detection_rules_valid_log_sources(rules):
    """Each rule must reference a log file that exists."""
    valid_logs = {"auth.log", "access.log", "dns_queries.log", "app_audit.log"}
    for i, rule in enumerate(rules):
        log_src = rule.get("log_source", "")
        assert log_src in valid_logs, (
            f"Rule {i} references invalid log_source '{log_src}'. "
            f"Valid sources: {valid_logs}")


def test_initial_access_rule_accuracy(rules):
    """Initial access rules must reference the correct attacker IP."""
    ia_rules = [r for r in rules if r.get("stage", "").lower().strip() == "initial_access"]
    assert len(ia_rules) >= 1, "No initial_access rules found"
    combined = " ".join(
        str(r.get("indicator_value", "")) + " " + str(r.get("detection_logic", ""))
        for r in ia_rules
    )
    assert any(ioc in combined for ioc in STAGE_INDICATORS["initial_access"]), (
        f"Initial access rules must reference the attacker IP {STAGE_INDICATORS['initial_access']}")


def test_execution_rule_accuracy(rules):
    """Execution rules must reference the webshell indicator."""
    exec_rules = [r for r in rules if r.get("stage", "").lower().strip() == "execution"]
    assert len(exec_rules) >= 1, "No execution rules found"
    combined = " ".join(
        str(r.get("indicator_value", "")) + " " + str(r.get("detection_logic", ""))
        for r in exec_rules
    )
    assert any(ioc in combined for ioc in STAGE_INDICATORS["execution"]), (
        f"Execution rules must reference the webshell: {STAGE_INDICATORS['execution']}")


def test_exfiltration_rule_accuracy(rules):
    """Exfiltration rules must reference the C2 domain or exfil pattern."""
    exfil_rules = [r for r in rules if r.get("stage", "").lower().strip() == "exfiltration"]
    assert len(exfil_rules) >= 1, "No exfiltration rules found"
    combined = " ".join(
        str(r.get("indicator_value", "")) + " " + str(r.get("detection_logic", ""))
        for r in exfil_rules
    )
    assert any(ioc in combined for ioc in STAGE_INDICATORS["exfiltration"]), (
        f"Exfiltration rules must reference C2/exfil indicators: {STAGE_INDICATORS['exfiltration']}")


def test_initial_access_rule_log_source(rules):
    """Initial access rules must reference an appropriate log source."""
    ia_rules = [r for r in rules if r.get("stage", "").lower().strip() == "initial_access"]
    valid = STAGE_LOG_SOURCES["initial_access"]
    for rule in ia_rules:
        assert rule.get("log_source", "") in valid, (
            f"Initial access rule should reference {valid}, got '{rule.get('log_source')}'")


def test_exfiltration_rule_log_source(rules):
    """Exfiltration rules must reference an appropriate log source."""
    exfil_rules = [r for r in rules if r.get("stage", "").lower().strip() == "exfiltration"]
    valid = STAGE_LOG_SOURCES["exfiltration"]
    for rule in exfil_rules:
        assert rule.get("log_source", "") in valid, (
            f"Exfiltration rule should reference {valid}, got '{rule.get('log_source')}'")


def test_detection_rules_unique_ids(rules):
    """All rule IDs must be unique."""
    ids = [r.get("rule_id", "") for r in rules]
    assert len(ids) == len(set(ids)), f"Duplicate rule_id values found: {ids}"


def test_detection_rules_indicators_in_logs(rules):
    """Each rule's indicator_value must actually appear in the referenced log."""
    log_cache = {}
    for rule in rules:
        log_src = rule.get("log_source", "")
        indicator = str(rule.get("indicator_value", ""))
        if not log_src or not indicator:
            continue
        log_path = f"/app/logs/{log_src}"
        if log_path not in log_cache:
            with open(log_path) as f:
                log_cache[log_path] = f.read()
        assert indicator in log_cache[log_path], (
            f"Indicator '{indicator}' not found in {log_src}")
