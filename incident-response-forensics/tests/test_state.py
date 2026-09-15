
"""Tests for forensic investigation and detection engineering deliverables."""

import json
import os
import base64
import subprocess
import pytest


REPORT_PATH = "/app/report/findings.json"
YARA_PATH = "/app/report/detection.yar"
REMEDIATION_PATH = "/app/report/remediation.json"


@pytest.fixture
def report():
    """Load the incident report JSON."""
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture
def remediation():
    """Load the remediation assessment JSON."""
    assert os.path.exists(REMEDIATION_PATH), f"Remediation not found at {REMEDIATION_PATH}"
    with open(REMEDIATION_PATH) as f:
        data = json.load(f)
    return data


def _normalize(s):
    return str(s).lower().strip()


def _contains_any(text, keywords):
    text = _normalize(text)
    return any(kw in text for kw in keywords)


# ============================================================
# Attacker Identification
# ============================================================

class TestAttackerIdentification:
    def test_attacker_source_ip(self, report):
        assert "attacker_source_ip" in report
        assert report["attacker_source_ip"] == "198.51.100.47"


# ============================================================
# C2 Servers (must find BOTH primary and secondary)
# ============================================================

class TestC2Servers:
    def test_c2_servers_exist(self, report):
        assert "c2_servers" in report
        c2s = report["c2_servers"]
        assert isinstance(c2s, list)
        assert len(c2s) >= 2, (
            f"Expected at least 2 C2 servers (primary + secondary), found {len(c2s)}"
        )

    def test_primary_c2_ip(self, report):
        c2s = report.get("c2_servers", [])
        c2_ips = [str(c.get("ip", "")) for c in c2s]
        assert "203.0.113.89" in c2_ips, (
            f"Primary C2 IP 203.0.113.89 not found in c2_servers: {c2_ips}"
        )

    def test_primary_c2_port(self, report):
        c2s = report.get("c2_servers", [])
        primary = next((c for c in c2s if c.get("ip") == "203.0.113.89"), {})
        assert int(primary.get("port", 0)) == 4444, (
            f"Primary C2 port should be 4444, got {primary.get('port')}"
        )

    def test_secondary_c2_ip(self, report):
        """Secondary C2 must be discovered from PCAP / binary analysis."""
        c2s = report.get("c2_servers", [])
        c2_ips = [str(c.get("ip", "")) for c in c2s]
        assert "192.0.2.100" in c2_ips, (
            f"Secondary C2 IP 192.0.2.100 not found in c2_servers: {c2_ips}. "
            "This requires PCAP or binary analysis to discover."
        )

    def test_secondary_c2_port(self, report):
        """Secondary C2 port 8443 must be discovered from PCAP / binary analysis."""
        c2s = report.get("c2_servers", [])
        secondary = next((c for c in c2s if c.get("ip") == "192.0.2.100"), {})
        assert int(secondary.get("port", 0)) == 8443, (
            f"Secondary C2 port should be 8443, got {secondary.get('port')}"
        )


# ============================================================
# Initial Access
# ============================================================

class TestInitialAccess:
    def test_initial_access_method(self, report):
        assert "initial_access" in report
        ia = report["initial_access"]
        method = _normalize(ia.get("method", ""))
        assert _contains_any(method, [
            "command injection", "command_injection", "cmd injection",
            "os command injection", "os_command_injection", "rce",
            "remote code execution", "code injection"
        ]), f"Initial access method '{ia.get('method')}' does not reference command injection"

    def test_vulnerable_endpoint(self, report):
        ia = report.get("initial_access", {})
        endpoint = _normalize(ia.get("vulnerable_endpoint", ""))
        assert "diagnostic" in endpoint
        assert "api" in endpoint

    def test_initial_access_timestamp(self, report):
        ia = report.get("initial_access", {})
        ts = ia.get("timestamp", "")
        assert "2024-03-15" in ts
        assert _contains_any(ts, ["02:14", "02:15"])


# ============================================================
# Privilege Escalation
# ============================================================

class TestPrivilegeEscalation:
    def test_privesc_method(self, report):
        assert "privilege_escalation" in report
        pe = report["privilege_escalation"]
        method = _normalize(pe.get("method", ""))
        binary = _normalize(pe.get("vulnerable_binary", ""))
        combined = method + " " + binary
        assert _contains_any(combined, [
            "pkexec", "pwnkit", "cve-2021-4034", "polkit", "suid", "setuid"
        ])


# ============================================================
# Persistence Mechanisms (all 4 required)
# ============================================================

class TestPersistenceMechanisms:
    def test_persistence_exists(self, report):
        assert "persistence_mechanisms" in report
        mechs = report["persistence_mechanisms"]
        assert isinstance(mechs, list)
        assert len(mechs) >= 4, f"Expected >= 4 persistence mechanisms, found {len(mechs)}"

    def _all_persistence_text(self, report):
        mechs = report.get("persistence_mechanisms", [])
        parts = []
        for m in mechs:
            if isinstance(m, dict):
                parts.append(_normalize(json.dumps(m)))
            else:
                parts.append(_normalize(str(m)))
        return " ".join(parts)

    def test_cron_persistence(self, report):
        text = self._all_persistence_text(report)
        assert _contains_any(text, ["cron", "crontab"])
        assert _contains_any(text, ["cache_update", ".cache"])

    def test_ssh_key_persistence(self, report):
        text = self._all_persistence_text(report)
        assert _contains_any(text, ["ssh", "authorized_keys", "public key", "publickey"])

    def test_backdoor_user_persistence(self, report):
        text = self._all_persistence_text(report)
        assert _contains_any(text, ["svc_backup", "backdoor user", "uid 0", "uid=0", "user account"])

    def test_pam_persistence(self, report):
        text = self._all_persistence_text(report)
        assert _contains_any(text, ["pam", "pam_permit", "authentication bypass", "common-auth"])


# ============================================================
# Backdoor User and Compromised Accounts
# ============================================================

class TestBackdoorUser:
    def test_backdoor_username(self, report):
        assert "backdoor_user" in report
        assert _normalize(report["backdoor_user"]) == "svc_backup"


class TestCompromisedAccounts:
    def test_compromised_accounts_exist(self, report):
        assert "compromised_accounts" in report
        accounts = report["compromised_accounts"]
        assert isinstance(accounts, list)
        assert len(accounts) >= 2

    def test_www_data_compromised(self, report):
        accounts = [_normalize(a) for a in report.get("compromised_accounts", [])]
        assert any("www-data" in a or "www_data" in a for a in accounts)

    def test_root_compromised(self, report):
        accounts = [_normalize(a) for a in report.get("compromised_accounts", [])]
        assert "root" in accounts


# ============================================================
# Exfiltration (including DNS domain from PCAP)
# ============================================================

class TestExfiltration:
    def test_exfiltration_target(self, report):
        assert "exfiltration" in report
        exfil = report["exfiltration"]
        combined = _normalize(json.dumps(exfil))
        assert _contains_any(combined, [
            "database", "db", "mysqldump", "app_db", "mysql"
        ])

    def test_exfiltration_destination(self, report):
        exfil = report.get("exfiltration", {})
        combined = _normalize(json.dumps(exfil))
        assert "203.0.113.89" in combined

    def test_dns_exfiltration_domain(self, report):
        """DNS exfiltration domain must be identified from PCAP analysis."""
        exfil = report.get("exfiltration", {})
        dns_domain = _normalize(exfil.get("dns_domain", ""))
        assert _contains_any(dns_domain, [
            "updates-cdn", "updates-cdn.example.net",
            "exfil.updates-cdn", "exfil.updates-cdn.example.net"
        ]), (
            f"DNS exfiltration domain should reference 'updates-cdn.example.net', "
            f"got '{exfil.get('dns_domain')}'. Requires PCAP analysis."
        )


# ============================================================
# Malware Indicators (from binary reverse engineering)
# ============================================================

class TestMalwareIndicators:
    def test_indicators_exist(self, report):
        assert "malware_indicators" in report

    def test_user_agent(self, report):
        mi = report.get("malware_indicators", {})
        ua = mi.get("user_agent", "")
        assert "SystemUpdater" in ua, (
            f"User agent should contain 'SystemUpdater', got '{ua}'. "
            "Requires binary/PCAP analysis."
        )

    def test_xor_key(self, report):
        mi = report.get("malware_indicators", {})
        key = _normalize(mi.get("xor_key_hex", "")).replace("0x", "")
        assert key == "5a3c7e1d", (
            f"XOR key should be '5a3c7e1d', got '{key}'. "
            "Requires binary reverse engineering."
        )

    def test_mutex(self, report):
        mi = report.get("malware_indicators", {})
        mutex = _normalize(mi.get("mutex", ""))
        assert "cache_update" in mutex, (
            f"Mutex should contain 'cache_update', got '{mutex}'. "
            "Requires binary analysis with strings."
        )

    def test_beacon_interval(self, report):
        mi = report.get("malware_indicators", {})
        interval = int(mi.get("beacon_interval_sec", 0))
        assert interval == 300, (
            f"Beacon interval should be 300, got {interval}. "
            "Requires PCAP timestamp analysis."
        )


# ============================================================
# Timeline
# ============================================================

class TestTimeline:
    def test_timeline_exists(self, report):
        assert "timeline" in report
        tl = report["timeline"]
        assert isinstance(tl, list)
        assert len(tl) >= 6

    def test_timeline_has_timestamps(self, report):
        tl = report.get("timeline", [])
        for i, event in enumerate(tl):
            assert "timestamp" in event, f"Timeline event {i} missing 'timestamp'"
            assert "event" in event, f"Timeline event {i} missing 'event'"

    def test_timeline_covers_attack_start(self, report):
        tl = report.get("timeline", [])
        timestamps = " ".join(_normalize(e.get("timestamp", "")) for e in tl)
        assert _contains_any(timestamps, ["02:14", "02:15"])

    def test_timeline_covers_exfiltration(self, report):
        tl = report.get("timeline", [])
        events_text = " ".join(_normalize(e.get("event", "")) for e in tl)
        assert _contains_any(events_text, [
            "exfil", "dump", "mysqldump", "database", "data theft", "stole"
        ])


# ============================================================
# YARA Detection Rules
# ============================================================

class TestYaraRules:
    def test_yara_file_exists(self):
        assert os.path.exists(YARA_PATH), f"YARA rules not found at {YARA_PATH}"

    def test_yara_detects_binary(self):
        """YARA rules must detect the backdoor ELF binary."""
        binary_path = "/app/evidence/malware/backdoor"
        if not os.path.exists(binary_path):
            pytest.skip("Backdoor binary not found")

        result = subprocess.run(
            ["yara", YARA_PATH, binary_path],
            capture_output=True, text=True, timeout=30
        )
        assert result.stdout.strip(), (
            f"YARA rules did not match the backdoor binary. "
            f"stderr: {result.stderr[:500]}"
        )

    def test_yara_detects_script(self):
        """YARA rules must detect the decoded cache_update dropper script."""
        b64_path = "/app/evidence/malware/cache_update.b64"
        if not os.path.exists(b64_path):
            pytest.skip("cache_update.b64 not found")

        with open(b64_path) as f:
            encoded = f.read().strip()
        decoded = base64.b64decode(encoded)

        tmp_script = "/tmp/test_decoded_cache_update.sh"
        with open(tmp_script, "wb") as f:
            f.write(decoded)

        result = subprocess.run(
            ["yara", YARA_PATH, tmp_script],
            capture_output=True, text=True, timeout=30
        )
        assert result.stdout.strip(), (
            f"YARA rules did not match the decoded cache_update script. "
            f"stderr: {result.stderr[:500]}"
        )


# ============================================================
# Remediation Assessment
# ============================================================

class TestRemediation:
    def test_remediation_file_exists(self):
        assert os.path.exists(REMEDIATION_PATH), (
            f"Remediation assessment not found at {REMEDIATION_PATH}"
        )

    def test_remediation_structure(self, remediation):
        assert "findings" in remediation
        findings = remediation["findings"]
        assert isinstance(findings, list)
        assert len(findings) >= 8, (
            f"Need at least 8 remediation findings, got {len(findings)}"
        )

    def test_remediation_fields(self, remediation):
        required_fields = ["id", "severity", "category",
                           "remediation_action", "priority"]
        for i, finding in enumerate(remediation["findings"]):
            for field in required_fields:
                assert field in finding, (
                    f"Finding {i} missing required field '{field}'"
                )
            assert finding["severity"] in ("critical", "high", "medium", "low"), (
                f"Finding {i} has invalid severity: {finding['severity']}"
            )
            assert finding["priority"] in ("immediate", "short_term", "long_term"), (
                f"Finding {i} has invalid priority: {finding['priority']}"
            )

    def test_has_critical_findings(self, remediation):
        severities = [f["severity"] for f in remediation["findings"]]
        assert "critical" in severities, "Must have at least one critical finding"

    def test_covers_persistence(self, remediation):
        all_text = _normalize(json.dumps(remediation))
        assert _contains_any(all_text, [
            "persist", "cron", "backdoor", "pam", "authorized_keys"
        ]), "Remediation must address persistence mechanisms"

    def test_covers_vulnerability(self, remediation):
        all_text = _normalize(json.dumps(remediation))
        assert _contains_any(all_text, [
            "injection", "input valid", "sanitiz", "diagnostic", "command injection"
        ]), "Remediation must address the initial access vulnerability"

    def test_covers_egress(self, remediation):
        all_text = _normalize(json.dumps(remediation))
        assert _contains_any(all_text, [
            "egress", "outbound", "firewall", "network filter", "exfiltration prevention"
        ]), "Remediation must address missing egress filtering"
