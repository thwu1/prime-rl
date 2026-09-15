"""
Verify Suricata IDS rule engineering task: correct detections, suppression,
and incident report content.

"""
import json
import os
import re
import shutil
import subprocess

import pytest

VERIFY_LOG_DIR = "/tmp/suricata_verify"


@pytest.fixture(scope="session")
def run_suricata():
    """Run Suricata with the agent's rules and threshold config against the
    incident PCAP, then return parsed alert events."""
    if os.path.exists(VERIFY_LOG_DIR):
        shutil.rmtree(VERIFY_LOG_DIR)
    os.makedirs(VERIFY_LOG_DIR)

    rules_file = "/app/rules/local.rules"
    threshold_file = "/app/threshold.config"
    pcap_file = "/app/incident.pcap"

    assert os.path.exists(rules_file), "Rules file not found at /app/rules/local.rules"
    assert os.path.exists(pcap_file), "PCAP file not found at /app/incident.pcap"

    # Build a test-specific suricata.yaml that includes the threshold file
    base_config = "/etc/suricata/suricata.yaml"
    test_config = os.path.join(VERIFY_LOG_DIR, "suricata.yaml")

    with open(base_config, "r") as f:
        config_text = f.read()

    if os.path.exists(threshold_file):
        # Uncomment and set threshold-file, or append if absent
        config_text = re.sub(
            r"#?\s*threshold-file:.*",
            f"threshold-file: {threshold_file}",
            config_text,
        )
        if "threshold-file" not in config_text:
            config_text += f"\nthreshold-file: {threshold_file}\n"

    with open(test_config, "w") as f:
        f.write(config_text)

    cmd = [
        "suricata",
        "-r", pcap_file,
        "-S", rules_file,
        "-l", VERIFY_LOG_DIR,
        "-k", "none",
        "-c", test_config,
        "--runmode", "single",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    eve_file = os.path.join(VERIFY_LOG_DIR, "eve.json")
    alerts = []
    if os.path.exists(eve_file):
        with open(eve_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("event_type") == "alert":
                        alerts.append(event)
                except json.JSONDecodeError:
                    pass

    return {
        "alerts": alerts,
        "returncode": result.returncode,
        "stderr": result.stderr,
        "stdout": result.stdout,
    }


# ------------------------------------------------------------------
# Structural checks
# ------------------------------------------------------------------

def test_rules_file_exists():
    assert os.path.exists("/app/rules/local.rules"), \
        "Rules file not found at /app/rules/local.rules"


def test_threshold_config_exists():
    assert os.path.exists("/app/threshold.config"), \
        "Threshold config not found at /app/threshold.config"


def test_rules_valid():
    """suricata -T must pass with the agent's rules."""
    os.makedirs("/tmp/suricata_tcheck", exist_ok=True)
    result = subprocess.run(
        [
            "suricata", "-T",
            "-S", "/app/rules/local.rules",
            "-l", "/tmp/suricata_tcheck",
            "-k", "none",
            "-c", "/etc/suricata/suricata.yaml",
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, \
        f"Rule validation failed:\n{result.stderr[-3000:]}"


# ------------------------------------------------------------------
# Detection accuracy: expected alert counts per SID
# ------------------------------------------------------------------

def test_dns_tunneling_detected(run_suricata):
    """3 DNS tunneling queries from 10.0.0.100 to evil-c2.example.net."""
    alerts = [a for a in run_suricata["alerts"]
              if a["alert"]["signature_id"] == 2100001]
    assert len(alerts) == 3, \
        f"Expected 3 DNS tunneling alerts (SID 2100001), got {len(alerts)}"
    src_ips = {a["src_ip"] for a in alerts}
    assert "10.0.0.100" in src_ips, \
        "DNS tunneling alerts should originate from 10.0.0.100"


def test_reverse_shell_detected(run_suricata):
    """2 reverse shells from 10.0.0.100 and 10.0.0.101."""
    alerts = [a for a in run_suricata["alerts"]
              if a["alert"]["signature_id"] == 2100002]
    assert len(alerts) == 2, \
        f"Expected 2 reverse shell alerts (SID 2100002), got {len(alerts)}"
    src_ips = {a["src_ip"] for a in alerts}
    assert "10.0.0.100" in src_ips, "Missing reverse shell from 10.0.0.100"
    assert "10.0.0.101" in src_ips, "Missing reverse shell from 10.0.0.101"


def test_icmp_scan_detected(run_suricata):
    """8 ICMP alerts, one per unique scanner IP (threshold limits to 1/src/60s)."""
    alerts = [a for a in run_suricata["alerts"]
              if a["alert"]["signature_id"] == 2100003]
    assert len(alerts) == 8, \
        f"Expected 8 ICMP scan alerts (SID 2100003), got {len(alerts)}"
    src_ips = {a["src_ip"] for a in alerts}
    expected = {f"192.168.1.{x}" for x in [10, 20, 30, 40, 50, 60, 70, 80]}
    assert src_ips == expected, \
        f"ICMP alerts from wrong sources: got {src_ips}, expected {expected}"


def test_trojan_ua_detected(run_suricata):
    """1 HTTP alert for Trojan User-Agent from 10.0.0.200."""
    alerts = [a for a in run_suricata["alerts"]
              if a["alert"]["signature_id"] == 2100004]
    assert len(alerts) == 1, \
        f"Expected 1 Trojan UA alert (SID 2100004), got {len(alerts)}"
    assert alerts[0]["src_ip"] == "10.0.0.200"


def test_binary_exfil_detected(run_suricata):
    """Binary exfiltration alert(s) from 10.0.0.100 only.

    Suricata's stream reassembly may produce 1 or 2 alerts for a single
    data segment depending on stream-flush timing, so we accept >= 1 and
    verify all alerts originate from the expected compromised host.
    """
    alerts = [a for a in run_suricata["alerts"]
              if a["alert"]["signature_id"] == 2100005]
    assert len(alerts) >= 1, \
        f"Expected at least 1 binary exfil alert (SID 2100005), got {len(alerts)}"
    src_ips = {a["src_ip"] for a in alerts}
    assert src_ips == {"10.0.0.100"}, \
        f"Binary exfil alerts should only come from 10.0.0.100, got {src_ips}"


# ------------------------------------------------------------------
# Suppression: trusted host must produce zero alerts
# ------------------------------------------------------------------

def test_trusted_host_suppressed(run_suricata):
    """No alerts from the trusted monitoring host 10.0.0.1."""
    trusted = [a for a in run_suricata["alerts"]
               if a.get("src_ip") == "10.0.0.1"]
    assert len(trusted) == 0, \
        f"Expected 0 alerts from 10.0.0.1, got {len(trusted)}"


# ------------------------------------------------------------------
# Incident report
# ------------------------------------------------------------------

def test_incident_report_exists():
    assert os.path.exists("/app/incident_report.txt"), \
        "Incident report not found at /app/incident_report.txt"


def test_incident_report_compromised_hosts():
    with open("/app/incident_report.txt") as f:
        content = f.read()
    assert "10.0.0.100" in content, \
        "Report must identify 10.0.0.100 as compromised"
    assert "10.0.0.101" in content, \
        "Report must identify 10.0.0.101 as compromised"


def test_incident_report_c2_domain():
    with open("/app/incident_report.txt") as f:
        content = f.read().lower()
    assert "evil-c2.example.net" in content, \
        "Report must mention the C2 tunneling domain evil-c2.example.net"


def test_incident_report_c2_ips():
    with open("/app/incident_report.txt") as f:
        content = f.read()
    assert "203.0.113.50" in content or "203.0.113.51" in content, \
        "Report must mention at least one C2 infrastructure IP (203.0.113.50 or 203.0.113.51)"
