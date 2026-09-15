#!/usr/bin/env python3
"""Solve the quickcalc supply chain forensics task.


Decodes all obfuscated payloads, extracts IOCs, correlates logs,
reconstructs the attack timeline, maps to MITRE ATT&CK, assesses
severity, and writes the analysis report and Semgrep detection rule.
"""

import base64
import json
import os
import re
import zlib


PACKAGES_DIR = "/app/packages"
LOGS_DIR = "/app/logs"
ARTIFACTS_DIR = "/app/artifacts"
REPORT_DIR = "/app/report"


def decode_v120_setup_py():
    """Decode the base64 payload from v1.2.0 setup.py."""
    with open(f"{PACKAGES_DIR}/quickcalc-1.2.0/setup.py") as f:
        content = f.read()

    # Extract the base64 string from exec(__import__('base64').b64decode('...').decode())
    match = re.search(r"b64decode\('([A-Za-z0-9+/=]+)'\)", content)
    if not match:
        return None
    encoded = match.group(1)
    return base64.b64decode(encoded).decode()


def decode_v121_pth():
    """Decode the double-base64 payload from v1.2.1 .pth file."""
    pth_path = f"{ARTIFACTS_DIR}/quickcalc_init.pth"
    with open(pth_path) as f:
        content = f.read()

    # Extract the outer base64 from b64decode(b64decode(b'...'))
    match = re.search(r"b64decode\(b'([A-Za-z0-9+/=]+)'\)", content)
    if not match:
        return None
    outer = match.group(1)
    inner = base64.b64decode(outer)
    return base64.b64decode(inner).decode()


def decode_v122_utils():
    """Decode the zlib+base64 payload from v1.2.2 utils.py."""
    with open(f"{PACKAGES_DIR}/quickcalc-1.2.2/quickcalc/utils.py") as f:
        content = f.read()

    # Extract the 4 config chunks
    chunks = []
    for var in ["_CFG_A", "_CFG_B", "_CFG_C", "_CFG_D"]:
        match = re.search(rf'{var} = "([^"]*)"', content)
        if match:
            chunks.append(match.group(1))

    combined = "".join(chunks)
    compressed = base64.b64decode(combined)
    return zlib.decompress(compressed).decode()


def extract_iocs_from_payload(payload_text):
    """Extract IOCs from a decoded payload string."""
    iocs = {
        "c2_domains": set(),
        "exfil_domains": set(),
        "exfil_endpoints": set(),
        "beacon_interval": None,
        "targeted_credentials": set(),
        "targeted_files": set(),
    }

    # C2 domain (freeddns pattern)
    c2_matches = re.findall(r'["\']([a-z0-9.-]+\.freeddns\.org)["\']', payload_text)
    for m in c2_matches:
        iocs["c2_domains"].add(m)

    # Exfil domain
    exfil_matches = re.findall(r'["\']([a-z0-9.-]+\.quickcalc\.cloud)["\']', payload_text)
    for m in exfil_matches:
        iocs["exfil_domains"].add(m)

    # Exfil endpoints (may be constructed via concatenation)
    url_matches = re.findall(r'https?://[a-z0-9.-]+\.quickcalc\.cloud/[a-z0-9/]+', payload_text)
    for m in url_matches:
        iocs["exfil_endpoints"].add(m)
    # Also look for path components combined with the exfil domain variable
    path_matches = re.findall(r'["\'](/v[0-9]+/[a-z]+)["\']', payload_text)
    for path in path_matches:
        for domain in iocs["exfil_domains"]:
            iocs["exfil_endpoints"].add(f"https://{domain}{path}")

    # Beacon interval
    bi_match = re.search(r'_BI=(\d+)', payload_text)
    if bi_match:
        iocs["beacon_interval"] = int(bi_match.group(1))

    # Targeted env vars
    env_matches = re.findall(r'"((?:AWS_|GITHUB_|PYPI_|NPM_|DOCKER_|CI_)[A-Z_]+)"', payload_text)
    for m in env_matches:
        iocs["targeted_credentials"].add(m)

    # Targeted files
    file_matches = re.findall(
        r'(?:expanduser\(["\']([^"\']+)["\']\)|["\'](/(?:root|var)[^"\']+)["\'])',
        payload_text
    )
    for groups in file_matches:
        for g in groups:
            if g:
                iocs["targeted_files"].add(g)

    return iocs


def parse_ci_logs():
    """Parse CI/CD logs to identify the compromised tool and credential exfiltration."""
    info = {
        "compromised_tool_name": "",
        "compromised_tool_version": "",
        "credential_exfil_destination": "",
    }

    build_328 = os.path.join(LOGS_DIR, "github_actions_build_328.log")
    with open(build_328) as f:
        content = f.read()

    # Find trivy version
    trivy_match = re.search(r'trivy-action@v([\d.]+)', content)
    if trivy_match:
        info["compromised_tool_name"] = "trivy"
        info["compromised_tool_version"] = trivy_match.group(1)

    # Find credential exfil destination
    post_match = re.search(r'POST https?://([a-z0-9.-]+)/api', content)
    if post_match:
        info["credential_exfil_destination"] = post_match.group(1)

    return info


def parse_whois():
    """Parse WHOIS data for registrar and C2 decoy IP."""
    info = {
        "registrar": "",
        "c2_decoy_ip": "",
    }

    whois_path = os.path.join(LOGS_DIR, "whois_data.txt")
    with open(whois_path) as f:
        content = f.read()

    reg_match = re.search(r'Registrar: (.+)', content)
    if reg_match:
        info["registrar"] = reg_match.group(1).strip()

    # C2 decoy IP for freeddns domain
    freeddns_section = content[content.find("freeddns.org"):]
    ip_match = re.search(r'IN A (\d+\.\d+\.\d+\.\d+)', freeddns_section)
    if ip_match:
        info["c2_decoy_ip"] = ip_match.group(1)

    return info


def build_timeline():
    """Build the attack timeline from log correlation."""
    events = []

    # From WHOIS: domain registration
    events.append({
        "timestamp": "2026-03-14T22:15:00Z",
        "event": "Attacker registers quickcalc.cloud and checkmarx.zone domains via Namecheap"
    })

    # From CI log: compromised trivy runs
    events.append({
        "timestamp": "2026-03-19T14:30:33Z",
        "event": "Build #328 runs compromised trivy-action v0.69.4"
    })

    # From CI log + DNS: credential exfiltration
    events.append({
        "timestamp": "2026-03-19T14:30:46Z",
        "event": "Compromised trivy exfiltrates PYPI_TOKEN to checkmarx.zone"
    })

    # From PyPI log: malicious uploads
    events.append({
        "timestamp": "2026-03-19T15:01:33Z",
        "event": "Malicious quickcalc v1.2.0 published to PyPI using stolen credentials"
    })

    events.append({
        "timestamp": "2026-03-19T15:02:01Z",
        "event": "v1.2.0 payload executes and exfiltrates data to api-cdn.quickcalc.cloud"
    })

    events.append({
        "timestamp": "2026-03-19T15:02:15Z",
        "event": "DNS TXT C2 beaconing begins to updates.quickcalc-cdn.freeddns.org"
    })

    events.append({
        "timestamp": "2026-03-19T15:14:22Z",
        "event": "Malicious quickcalc v1.2.1 published with .pth persistence mechanism"
    })

    events.append({
        "timestamp": "2026-03-19T15:22:41Z",
        "event": "Malicious quickcalc v1.2.2 published with encrypted exfil and k8s worm"
    })

    events.append({
        "timestamp": "2026-03-19T18:42:17Z",
        "event": "C2 delivers active command via DNS TXT: curl bootstrap payload"
    })

    return sorted(events, key=lambda e: e["timestamp"])


def build_mitre_mapping():
    """Map observed attacker behaviors to MITRE ATT&CK techniques."""
    return [
        {
            "technique_id": "T1195.002",
            "technique_name": "Supply Chain Compromise: Compromise Software Supply Chain",
            "description": "Attacker compromised the quickcalc package build pipeline via a "
                           "trojanized CI security scanning tool to steal publishing credentials "
                           "and publish malicious package versions"
        },
        {
            "technique_id": "T1059.006",
            "technique_name": "Command and Scripting Interpreter: Python",
            "description": "Malicious payloads executed via Python exec() calls in setup.py, "
                           ".pth files, and utils.py modules"
        },
        {
            "technique_id": "T1027",
            "technique_name": "Obfuscated Files or Information",
            "description": "Payloads obfuscated using base64 encoding, double-base64 encoding, "
                           "and zlib compression with variable splitting across multiple identifiers"
        },
        {
            "technique_id": "T1071.004",
            "technique_name": "Application Layer Protocol: DNS",
            "description": "C2 commands delivered via DNS TXT record queries to "
                           "updates.quickcalc-cdn.freeddns.org with 300-second beacon interval"
        },
        {
            "technique_id": "T1041",
            "technique_name": "Exfiltration Over C2 Channel",
            "description": "Stolen credentials and files exfiltrated via HTTPS POST requests "
                           "to api-cdn.quickcalc.cloud/v2/telemetry"
        },
        {
            "technique_id": "T1552.001",
            "technique_name": "Unsecured Credentials: Credentials In Files",
            "description": "Targeted SSH keys (~/.ssh/id_rsa, id_ed25519), AWS credentials, "
                           "Docker config, Kubernetes service account tokens, and /etc/shadow"
        },
        {
            "technique_id": "T1546",
            "technique_name": "Event Triggered Execution",
            "description": "Persistence via .pth file placed in Python site-packages that "
                           "executes automatically on interpreter startup"
        },
        {
            "technique_id": "T1078",
            "technique_name": "Valid Accounts",
            "description": "Used stolen PYPI_TOKEN credentials to authenticate and publish "
                           "malicious package versions to the official PyPI repository"
        },
    ]


def build_severity_assessment():
    """Assess threat severity of each malicious version."""
    return [
        {
            "version": "1.2.0",
            "severity": "high",
            "justification": "Single-stage credential harvesting targeting 7 environment "
                             "variables and 5 sensitive file paths with cleartext HTTP "
                             "exfiltration. No persistence or C2 capability limits ongoing "
                             "threat, but immediate credential exposure is high-impact."
        },
        {
            "version": "1.2.1",
            "severity": "high",
            "justification": "Adds DNS TXT-based C2 beaconing with 300-second polling interval "
                             "enabling arbitrary remote command execution, .pth file persistence "
                             "for automatic re-execution on Python startup, and kubectl secrets "
                             "enumeration. Persistent backdoor access significantly escalates "
                             "threat over v1.2.0."
        },
        {
            "version": "1.2.2",
            "severity": "critical",
            "justification": "Most advanced payload combining AES-256-CBC + RSA encrypted "
                             "exfiltration (defeating network-level detection), /etc/shadow and "
                             "auth log theft for system-level credential access, and Kubernetes "
                             "lateral movement via pod deployment across all namespaces. Active "
                             "worm capability can propagate across the entire cluster, making "
                             "this a critical infrastructure-level threat."
        },
    ]


def write_semgrep_rule():
    """Write Semgrep detection rules for the obfuscation patterns used."""
    rule_yaml = """rules:
  - id: exec-base64-inline-import
    languages:
      - python
    message: >-
      Suspicious exec() with inline base64 import and decode - likely obfuscated malware payload
    pattern: "exec(__import__('base64').b64decode($DATA).decode())"
    severity: ERROR
    metadata:
      description: >-
        Detects exec() calls that inline-import base64 for dynamic code execution
  - id: exec-decompress-base64
    languages:
      - python
    message: >-
      Suspicious exec() with zlib decompression and base64 decode - likely obfuscated malware payload
    pattern: "exec($A.decompress($B.b64decode($C)).decode())"
    severity: ERROR
    metadata:
      description: >-
        Detects exec() calls combining zlib decompression with base64 decoding
"""

    rule_path = os.path.join(REPORT_DIR, "detect_malware.yaml")
    with open(rule_path, "w") as f:
        f.write(rule_yaml)


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)

    # Decode all payloads
    payload_v120 = decode_v120_setup_py()
    payload_v121 = decode_v121_pth()
    payload_v122 = decode_v122_utils()

    # Merge IOCs from all payloads
    all_iocs = {
        "c2_domains": set(),
        "exfil_domains": set(),
        "exfil_endpoints": set(),
        "beacon_interval": None,
        "targeted_credentials": set(),
        "targeted_files": set(),
    }

    for payload in [payload_v120, payload_v121, payload_v122]:
        if payload:
            iocs = extract_iocs_from_payload(payload)
            all_iocs["c2_domains"] |= iocs["c2_domains"]
            all_iocs["exfil_domains"] |= iocs["exfil_domains"]
            all_iocs["exfil_endpoints"] |= iocs["exfil_endpoints"]
            if iocs["beacon_interval"]:
                all_iocs["beacon_interval"] = iocs["beacon_interval"]
            all_iocs["targeted_credentials"] |= iocs["targeted_credentials"]
            all_iocs["targeted_files"] |= iocs["targeted_files"]

    # Parse supplementary evidence
    ci_info = parse_ci_logs()
    whois_info = parse_whois()
    timeline = build_timeline()
    mitre_techniques = build_mitre_mapping()
    severity = build_severity_assessment()

    # Build the final report
    report = {
        "malicious_versions": ["1.2.0", "1.2.1", "1.2.2"],
        "clean_versions": ["1.0.0", "1.0.1", "1.1.0"],
        "c2_domains": sorted(all_iocs["c2_domains"]),
        "exfil_domains": sorted(all_iocs["exfil_domains"]),
        "exfil_endpoints": sorted(all_iocs["exfil_endpoints"]),
        "beacon_interval_seconds": all_iocs["beacon_interval"],
        "targeted_credentials": sorted(all_iocs["targeted_credentials"]),
        "targeted_files": sorted(all_iocs["targeted_files"]),
        "persistence_mechanism": "pth_file",
        "initial_access_vector": "compromised_trivy_github_action",
        "attacker_infrastructure_domain_registrar": whois_info["registrar"],
        "attacker_c2_decoy_ip": whois_info["c2_decoy_ip"],
        "compromised_tool_name": ci_info["compromised_tool_name"],
        "compromised_tool_version": ci_info["compromised_tool_version"],
        "credential_exfil_destination": ci_info["credential_exfil_destination"],
        "attack_timeline": timeline,
        "mitre_attack_techniques": mitre_techniques,
        "severity_assessment": severity,
    }

    with open(os.path.join(REPORT_DIR, "analysis.json"), "w") as f:
        json.dump(report, f, indent=2)

    # Write Semgrep detection rule
    write_semgrep_rule()

    print("Analysis complete. Report written to /app/report/analysis.json")
    print("Semgrep rule written to /app/report/detect_malware.yaml")


if __name__ == "__main__":
    main()
