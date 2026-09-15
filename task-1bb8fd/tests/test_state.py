
import json
import os
import subprocess

import pytest

REPORT_PATH = "/app/output/corrected_report.json"
RULES_PATH = "/app/output/detection.rules"
PCAP_PATH = "/app/evidence/incident.pcap"


@pytest.fixture
def report():
    with open(REPORT_PATH) as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════
# IoC ACCURACY TESTS (core forensic analysis)
# ═══════════════════════════════════════════════════════════════


def test_attacker_ip(report):
    assert report["attacker_ip"] == "10.13.37.100"


def test_victim_ip(report):
    assert report["victim_ip"] == "192.168.1.50"


def test_scanned_ports(report):
    expected = {22, 80, 443, 3306, 5432, 8080, 8443, 9090}
    actual = set(report["recon_ports_scanned"])
    assert actual == expected, f"Expected {sorted(expected)}, got {sorted(actual)}"


def test_open_ports(report):
    actual = set(report["recon_ports_open"])
    assert actual == {22, 8080}, f"Expected {{22, 8080}}, got {actual}"


def test_exploit_vector(report):
    vector = report["exploit_vector"].lower().replace("_", " ").replace("-", " ")
    assert "command" in vector and "injection" in vector, \
        f"Expected 'command injection' variant, got '{report['exploit_vector']}'"


def test_exploit_endpoint(report):
    assert report["exploit_endpoint"] == "/api/query"


def test_exploit_parameter(report):
    assert report["exploit_parameter"] == "search"


def test_malware_url(report):
    url = report["malware_download_url"]
    assert "10.13.37.100" in url, "Malware URL must contain attacker IP"
    assert "4444" in url, "Malware URL must contain port 4444"
    assert "implant.sh" in url, "Malware URL must reference implant.sh"


def test_c2_protocol(report):
    assert report["c2_protocol"].lower() == "dns", \
        f"Expected 'dns', got '{report['c2_protocol']}'"


def test_c2_domain(report):
    domain = report["c2_domain"].rstrip(".")
    assert domain == "srv.update-check.net"


def test_c2_encoding(report):
    assert "hex" in report["c2_encoding"].lower(), \
        f"Expected 'hex' in encoding, got '{report['c2_encoding']}'"


def test_c2_commands(report):
    cmds = report["c2_commands"]
    assert isinstance(cmds, list), "c2_commands must be a list"
    assert len(cmds) >= 5, f"Expected at least 5 C2 commands, got {len(cmds)}"

    all_cmds = " ".join(cmds)
    assert any("id" in c for c in cmds), f"Missing 'id' command in: {cmds}"
    assert any("crontab" in c for c in cmds), f"Missing 'crontab' command in: {cmds}"
    assert any("/home" in c for c in cmds), f"Missing '/home' reference in: {cmds}"
    assert any("10.13.37.200" in c and "d3a75e11" in c for c in cmds), \
        f"Missing EXFIL directive with relay IP and XOR key in: {cmds}"
    assert any("HARVEST" in c for c in cmds), f"Missing 'HARVEST' command in: {cmds}"


def test_exfil_method(report):
    assert "icmp" in report["exfil_method"].lower(), \
        f"Expected 'icmp', got '{report['exfil_method']}'"


def test_exfil_dest_ip(report):
    assert report["exfil_dest_ip"] == "10.13.37.200"


def test_exfil_key(report):
    assert report["exfil_key"].lower() == "d3a75e11", \
        f"Expected 'd3a75e11', got '{report['exfil_key']}'"


def test_exfil_credentials(report):
    data = report["exfil_decoded_data"]
    assert isinstance(data, list), "exfil_decoded_data must be a list"
    all_data = "\n".join(str(x) for x in data)
    expected_creds = [
        "admin:SuperS3cretP@ss!",
        "dbuser:MySQL_R00t_2024#",
        "deploy:CI_CD_t0ken_X9f2",
        "svc_backup:Bkup_key_7Hj$mN",
        "root_token:vault_s.X8k2mNpQ9rT1wV",
    ]
    for cred in expected_creds:
        assert cred in all_data, f"Missing credential: {cred}"


# ═══════════════════════════════════════════════════════════════
# EVALUATION TESTS (preliminary report audit & severity)
# ═══════════════════════════════════════════════════════════════


def test_preliminary_errors_identified(report):
    """Agent must identify which fields in the preliminary report are wrong."""
    errors = set(report["preliminary_errors"])
    expected_errors = {
        "suspected_attacker_ip",
        "attack_type",
        "target_parameter",
        "c2_protocol",
        "c2_destination",
        "exfil_protocol",
        "exfil_encoding",
        "overall_severity",
        "reconnaissance_activity",
        "credentials_at_risk",
    }
    found = errors & expected_errors
    assert len(found) >= 8, \
        f"Expected at least 8 of {sorted(expected_errors)} to be identified as errors, " \
        f"but only found {sorted(found)} ({len(found)}/10)"


def test_phase_severity_structure(report):
    """Severity assessment must exist for all four attack phases."""
    assert "phase_severity" in report, "Missing phase_severity in report"
    for phase in ["reconnaissance", "exploitation", "c2", "exfiltration"]:
        assert phase in report["phase_severity"], f"Missing severity for phase: {phase}"
        entry = report["phase_severity"][phase]
        assert "rating" in entry, f"Missing rating for {phase}"
        assert "justification" in entry, f"Missing justification for {phase}"
        assert len(entry["justification"]) >= 20, \
            f"Justification for {phase} is too brief ({len(entry['justification'])} chars)"


def test_severity_exploitation_rating(report):
    """Exploitation (RCE via command injection) should be rated high or critical."""
    rating = report["phase_severity"]["exploitation"]["rating"].lower()
    assert rating in ("high", "critical"), \
        f"Exploitation severity should be high or critical, got '{rating}'"


def test_severity_exfiltration_rating(report):
    """Credential exfiltration should be rated high or critical."""
    rating = report["phase_severity"]["exfiltration"]["rating"].lower()
    assert rating in ("high", "critical"), \
        f"Exfiltration severity should be high or critical, got '{rating}'"


# ═══════════════════════════════════════════════════════════════
# CREATION TESTS (Suricata detection rules)
# ═══════════════════════════════════════════════════════════════


def test_rules_file_exists():
    assert os.path.exists(RULES_PATH), \
        f"Detection rules file not found at {RULES_PATH}"


def test_rules_minimum_count():
    """Must have at least 4 rules (one per attack phase)."""
    with open(RULES_PATH) as f:
        content = f.read()
    rules = [l.strip() for l in content.split("\n")
             if l.strip() and l.strip().startswith("alert")]
    assert len(rules) >= 4, \
        f"Expected at least 4 Suricata rules, got {len(rules)}"


def test_rules_valid_structure():
    """Each rule must have msg and sid keywords and end with closing paren."""
    with open(RULES_PATH) as f:
        content = f.read()
    rules = [l.strip() for l in content.split("\n")
             if l.strip() and l.strip().startswith("alert")]
    for rule in rules:
        assert "msg:" in rule, f"Rule missing msg keyword: {rule[:80]}..."
        assert "sid:" in rule, f"Rule missing sid keyword: {rule[:80]}..."
        assert rule.endswith(")"), f"Rule not properly terminated: {rule[-40:]}"


def test_rules_cover_attack_phases():
    """Rules should reference at least 3 of the 4 attack phases."""
    with open(RULES_PATH) as f:
        content = f.read().lower()
    phases_found = 0
    if any(term in content for term in ["recon", "scan", "probe", "syn"]):
        phases_found += 1
    if any(term in content for term in ["exploit", "injection", "rce", "command"]):
        phases_found += 1
    if any(term in content for term in ["c2", "c&c", "tunnel", "beacon", "command and control"]):
        phases_found += 1
    if any(term in content for term in ["exfil", "covert", "icmp", "data theft"]):
        phases_found += 1
    assert phases_found >= 3, \
        f"Rules should reference at least 3 of 4 attack phases, found {phases_found}"


def test_suricata_syntax_valid():
    """Rules must pass Suricata syntax validation."""
    logdir = "/tmp/suricata-syntax-test"
    os.makedirs(logdir, exist_ok=True)
    try:
        result = subprocess.run(
            ["suricata", "-T", "-S", RULES_PATH, "-l", logdir],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, \
            f"Suricata syntax validation failed (exit {result.returncode}):\n" \
            f"{result.stderr[-1000:]}"
    except FileNotFoundError:
        pytest.fail("suricata binary not found in PATH")
    except subprocess.TimeoutExpired:
        pytest.fail("Suricata syntax check timed out after 30 seconds")
