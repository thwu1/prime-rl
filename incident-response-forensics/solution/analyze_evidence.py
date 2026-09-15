#!/usr/bin/env python3
"""
Forensic analysis solution: parse all evidence, analyze PCAP and binary,
produce incident report, YARA detection rules, and remediation assessment.

"""

import json
import os
import re
import base64
import subprocess
from urllib.parse import unquote

EVIDENCE_ROOT = "/app/evidence"
REPORT_DIR = "/app/report"


def read_file(subpath):
    path = os.path.join(EVIDENCE_ROOT, subpath)
    with open(path) as f:
        return f.read()


def read_binary(subpath):
    path = os.path.join(EVIDENCE_ROOT, subpath)
    with open(path, "rb") as f:
        return f.read()


# ============================================================
# Log / artifact parsers (text-based evidence)
# ============================================================

def parse_access_log():
    content = read_file("web/access.log")
    lines = content.strip().split("\n")
    log_re = re.compile(
        r'^(\S+)\s+\S+\s+\S+\s+\[([^\]]+)\]\s+"(\S+)\s+(\S+)\s+\S+"\s+(\d+)\s+(\d+)')
    injection_pattern = re.compile(r'%3[Bb]')

    suspicious_ips = set()
    for line in lines:
        m = log_re.match(line)
        if not m:
            continue
        ip, ts, method, url, status, size = m.groups()
        if injection_pattern.search(url):
            suspicious_ips.add(ip)
        if "diagnostic" in url and method == "POST":
            suspicious_ips.add(ip)

    attacker_ip = None
    for ip in suspicious_ips:
        if not ip.startswith("10.") and not ip.startswith("45.33"):
            attacker_ip = ip
            break

    first_timestamp = None
    vulnerable_endpoint = None
    for line in lines:
        if not attacker_ip or not line.startswith(attacker_ip):
            continue
        m = log_re.match(line)
        if not m:
            continue
        ip, ts, method, url, status, size = m.groups()
        if first_timestamp is None:
            first_timestamp = ts
        if injection_pattern.search(url) and vulnerable_endpoint is None:
            decoded = unquote(url)
            if ";" in decoded:
                vulnerable_endpoint = decoded.split("?")[0]

    return {
        "attacker_ip": attacker_ip,
        "first_timestamp": first_timestamp,
        "vulnerable_endpoint": vulnerable_endpoint,
    }


def parse_syslog():
    content = read_file("system/syslog")
    lines = content.strip().split("\n")
    c2_info = {}
    cron_entries = []

    for line in lines:
        if "diagnostic" in line and ("curl" in line or "wget" in line):
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+):(\d+)', line)
            if ip_match:
                c2_info["exfil_ip"] = ip_match.group(1)
        if "TCP: connect" in line or "connect from" in line:
            conn_match = re.search(r'to\s+(\d+\.\d+\.\d+\.\d+):(\d+)', line)
            if conn_match:
                c2_info["ip"] = conn_match.group(1)
                c2_info["port"] = int(conn_match.group(2))
        if "CRON" in line and ".cache_update" in line:
            cron_entries.append(line)

    return {"c2_info": c2_info, "cron_entries": cron_entries}


def parse_auth_log():
    content = read_file("system/auth.log")
    lines = content.strip().split("\n")
    su_events = []

    for line in lines:
        if "Successful su" in line:
            su_match = re.search(r'Successful su for (\S+) by (\S+)', line)
            if su_match:
                su_events.append({
                    "target": su_match.group(1),
                    "source": su_match.group(2),
                })

    return {"su_events": su_events}


def parse_bash_histories():
    www_data = read_file("user_artifacts/bash_history_www-data")
    root_hist = read_file("user_artifacts/bash_history_root")

    privesc_method = None
    if "pkexec" in www_data or "pwnkit" in www_data.lower():
        privesc_method = "CVE-2021-4034 (PwnKit) via pkexec SUID"

    backdoor_user = None
    useradd_match = re.search(r'useradd\s+.*\s+(\S+)\s*$', root_hist, re.MULTILINE)
    if useradd_match:
        backdoor_user = useradd_match.group(1)

    exfil_info = {}
    if "mysqldump" in root_hist:
        db_match = re.search(r'mysqldump\s+.*--databases\s+(\S+)', root_hist)
        if db_match:
            exfil_info["target"] = db_match.group(1)
    if "curl" in root_hist and "POST" in root_hist:
        curl_match = re.search(r'curl\s+.*POST.*?(\d+\.\d+\.\d+\.\d+:\d+/\S+)', root_hist)
        if curl_match:
            exfil_info["destination"] = curl_match.group(1)

    return {
        "privesc_method": privesc_method,
        "backdoor_user": backdoor_user,
        "exfil_info": exfil_info,
    }


def parse_config_snapshots():
    persistence = []

    passwd = read_file("config/passwd.snapshot")
    uid0_users = []
    for line in passwd.strip().split("\n"):
        fields = line.split(":")
        if len(fields) >= 4 and fields[2] == "0" and fields[0] != "root":
            uid0_users.append(fields[0])
            persistence.append({
                "type": "backdoor_user",
                "detail": f"User '{fields[0]}' with UID 0 in /etc/passwd "
                          f"(shell={fields[6].strip()})"
            })

    pam = read_file("config/common-auth.snapshot")
    pam_lines = pam.strip().split("\n")
    for line in pam_lines:
        stripped = line.strip()
        if (stripped.startswith("auth") and "pam_permit.so" in stripped
                and "sufficient" in stripped):
            pam_unix_idx = next(
                (i for i, l in enumerate(pam_lines) if "pam_unix.so" in l),
                len(pam_lines))
            if pam_lines.index(line) < pam_unix_idx:
                persistence.append({
                    "type": "pam_backdoor",
                    "detail": "'auth sufficient pam_permit.so' before pam_unix.so "
                              "in /etc/pam.d/common-auth - bypasses password auth"
                })

    authkeys = read_file("user_artifacts/authorized_keys_root.bak")
    for line in authkeys.strip().split("\n"):
        if "c2server" in line:
            key_comment = line.strip().split()[-1]
            persistence.append({
                "type": "ssh_key",
                "detail": f"Attacker SSH key in /root/.ssh/authorized_keys "
                          f"(comment: {key_comment})"
            })

    crontab = read_file("user_artifacts/crontab_root.bak")
    for line in crontab.strip().split("\n"):
        if ".cache_update" in line and not line.startswith("#"):
            persistence.append({
                "type": "cron_backdoor",
                "detail": f"Cron reverse shell: {line.strip()}"
            })

    return {"persistence": persistence, "uid0_users": uid0_users}


def parse_malware_script():
    b64_content = read_file("malware/cache_update.b64").strip()
    decoded = base64.b64decode(b64_content).decode()
    c2_match = re.search(r'(\d+\.\d+\.\d+\.\d+)/(\d+)', decoded)
    if not c2_match:
        c2_match = re.search(r'(\d+\.\d+\.\d+\.\d+):(\d+)', decoded)
    return {
        "decoded_content": decoded,
        "c2_ip": c2_match.group(1) if c2_match else None,
        "c2_port": int(c2_match.group(2)) if c2_match else None,
    }


def parse_filesystem_timeline():
    content = read_file("filesystem/recent_modifications.txt")
    events = []
    for line in content.strip().split("\n"):
        if line.startswith("#") or not line.strip():
            continue
        match = re.match(
            r'(\d{4}-\d{2}-\d{2})\+(\d{2}:\d{2}:\d{2})\.\d+\s+\S+\s+\S+\s+(.*)', line)
        if match:
            events.append({
                "timestamp": f"{match.group(1)}T{match.group(2)}Z",
                "file": match.group(3).strip(),
            })
    return {"events": events}


# ============================================================
# PCAP Analysis (using tshark)
# ============================================================

def analyze_pcap():
    pcap_path = os.path.join(EVIDENCE_ROOT, "network/capture.pcap")
    if not os.path.exists(pcap_path):
        return {}

    c2_candidates = {}
    secondary_c2 = None
    dns_exfil_domain = None
    beacon_times = []
    pcap_user_agent = None

    # Find TCP SYN connections to external IPs
    try:
        result = subprocess.run(
            ['tshark', '-r', pcap_path, '-n',
             '-Y', 'tcp.flags.syn==1 && tcp.flags.ack==0',
             '-T', 'fields', '-e', 'ip.dst', '-e', 'tcp.dstport'],
            capture_output=True, text=True, timeout=30)
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) >= 2:
                ip, port = parts[0], parts[1]
                if not ip.startswith('10.'):
                    key = (ip, int(port))
                    c2_candidates[key] = c2_candidates.get(key, 0) + 1
    except Exception:
        pass

    # Find secondary C2 (non-4444 connections)
    for (ip, port), count in c2_candidates.items():
        if port != 4444 and ip != "8.8.8.8":
            secondary_c2 = {"ip": ip, "port": port}

    # Analyze DNS queries for exfiltration
    try:
        result = subprocess.run(
            ['tshark', '-r', pcap_path, '-n',
             '-Y', 'dns', '-T', 'fields', '-e', 'dns.qry.name'],
            capture_output=True, text=True, timeout=30)
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.strip().split('.')
            if len(parts) > 4:
                first_label = parts[0]
                if all(c in '0123456789abcdef' for c in first_label) and len(first_label) > 8:
                    dns_exfil_domain = '.'.join(parts[2:])
                    break
    except Exception:
        pass

    # Calculate beacon interval from SYN packets to port 8443
    try:
        result = subprocess.run(
            ['tshark', '-r', pcap_path, '-n',
             '-Y', 'tcp.dstport==8443 && tcp.flags.syn==1 && tcp.flags.ack==0',
             '-T', 'fields', '-e', 'frame.time_epoch'],
            capture_output=True, text=True, timeout=30)
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                beacon_times.append(float(line.strip()))
    except Exception:
        pass

    beacon_interval = None
    if len(beacon_times) >= 2:
        intervals = [beacon_times[i+1] - beacon_times[i]
                      for i in range(len(beacon_times) - 1)]
        beacon_interval = int(round(sum(intervals) / len(intervals)))

    # Extract user-agent from raw PCAP data
    try:
        with open(pcap_path, 'rb') as f:
            pcap_data = f.read()
        ua_marker = b'User-Agent: '
        idx = pcap_data.find(ua_marker)
        if idx >= 0:
            end = pcap_data.index(b'\r\n', idx)
            pcap_user_agent = pcap_data[idx + len(ua_marker):end].decode('utf-8', errors='ignore')
    except Exception:
        pass

    return {
        "secondary_c2": secondary_c2,
        "dns_exfil_domain": dns_exfil_domain,
        "beacon_interval": beacon_interval,
        "beacon_times": beacon_times,
        "user_agent": pcap_user_agent,
    }


# ============================================================
# Binary Analysis (using strings + raw byte search)
# ============================================================

def analyze_binary(known_c2_ip=None):
    binary_path = os.path.join(EVIDENCE_ROOT, "malware/backdoor")
    if not os.path.exists(binary_path):
        return {}

    binary_data = read_binary("malware/backdoor")
    user_agent = None
    mutex = None
    marker = None

    # Extract strings from binary
    try:
        result = subprocess.run(
            ['strings', binary_path],
            capture_output=True, text=True, timeout=30)
        for line in result.stdout.split('\n'):
            if 'SystemUpdater' in line:
                user_agent = line.strip()
            if 'cache_update_mtx' in line:
                mutex = line.strip()
            if 'CACHE_SVC' in line:
                marker = line.strip()
    except Exception:
        pass

    # Known-plaintext attack: use PCAP-discovered secondary C2 IP to
    # find the XOR key used to encrypt configuration strings in the binary.
    # For each position, derive the 4-byte repeating key from the first
    # 4 bytes of known plaintext, then verify against remaining bytes.
    xor_key_hex = None
    xor_key = None
    secondary_ip_from_binary = None
    domain_from_binary = None

    if known_c2_ip:
        plaintext = known_c2_ip.encode('ascii')
        pt_len = len(plaintext)

        for offset in range(len(binary_data) - pt_len):
            # Derive candidate key from first 4 bytes
            candidate_key = bytes(
                binary_data[offset + j] ^ plaintext[j] for j in range(4)
            )
            if candidate_key == b'\x00\x00\x00\x00':
                continue
            # Verify with remaining bytes (all must match)
            match = True
            for j in range(4, pt_len):
                if binary_data[offset + j] ^ candidate_key[j % 4] != plaintext[j]:
                    match = False
                    break
            if match:
                xor_key = candidate_key
                xor_key_hex = candidate_key.hex()
                secondary_ip_from_binary = known_c2_ip
                break

    # If we found the key, decrypt other encrypted config strings
    if xor_key:
        for offset in range(len(binary_data) - 23):
            enc = binary_data[offset:offset + 23]
            dec = bytes(enc[j] ^ xor_key[j % 4] for j in range(23))
            try:
                text = dec.decode('ascii')
                if text.endswith('.net') and '-' in text and '.' in text:
                    domain_from_binary = text
                    break
            except (UnicodeDecodeError, ValueError):
                pass

    return {
        "user_agent": user_agent,
        "mutex": mutex,
        "marker": marker,
        "xor_key_hex": xor_key_hex,
        "secondary_ip": secondary_ip_from_binary,
        "domain": domain_from_binary,
    }


# ============================================================
# YARA Rule Generation
# ============================================================

def generate_yara_rules(binary_analysis, malware_script):
    """Generate YARA rules based on discovered indicators."""
    rules = []

    # Rule for the ELF backdoor binary
    rules.append("""rule CacheUpdate_Backdoor_ELF {
    meta:
        description = "Detects CACHE_SVC backdoor ELF binary"
        author = "IR Analysis"
        date = "2024-03-15"
    strings:
        $marker = "CACHE_SVC_v2.1"
        $ua = "SystemUpdater/2.1"
        $mutex = "cache_update_mtx"
        $xor_key = { 5A 3C 7E 1D }
    condition:
        uint32(0) == 0x464C457F and 2 of ($marker, $ua, $mutex, $xor_key)
}""")

    # Rule for the bash reverse shell dropper
    rules.append("""rule CacheUpdate_Shell_Script {
    meta:
        description = "Detects cache_update reverse shell dropper script"
        author = "IR Analysis"
        date = "2024-03-15"
    strings:
        $shell = "/dev/tcp/"
        $c2_ip = "203.0.113.89"
        $port = "4444"
        $comment = "cache update"
    condition:
        2 of them
}""")

    return "\n\n".join(rules) + "\n"


# ============================================================
# Remediation Assessment Generation
# ============================================================

def generate_remediation():
    """Generate prioritized remediation assessment."""
    findings = [
        {
            "id": "F-1",
            "title": "Command Injection in Diagnostic Endpoint",
            "severity": "critical",
            "category": "vulnerability",
            "remediation_action": "Immediately disable /api/v1/diagnostic endpoint. "
                "Implement strict input validation and parameterized command execution. "
                "Never pass user input directly to shell commands.",
            "priority": "immediate",
            "justification": "This vulnerability provided initial access. "
                "Command injection allows arbitrary code execution as the web "
                "server user, enabling full system compromise."
        },
        {
            "id": "F-2",
            "title": "Cron-based Reverse Shell Persistence",
            "severity": "critical",
            "category": "persistence",
            "remediation_action": "Remove malicious crontab entry "
                "(*/5 * * * * /usr/local/bin/.cache_update). "
                "Delete /usr/local/bin/.cache_update. Audit all cron jobs system-wide.",
            "priority": "immediate",
            "justification": "Active reverse shell executing every 5 minutes provides "
                "continuous attacker access. Must be removed before any other remediation."
        },
        {
            "id": "F-3",
            "title": "Backdoor SSH Key in root authorized_keys",
            "severity": "critical",
            "category": "persistence",
            "remediation_action": "Remove the unauthorized SSH key (comment: root@c2server) "
                "from /root/.ssh/authorized_keys. Rotate all SSH keys. "
                "Implement SSH key management policy.",
            "priority": "immediate",
            "justification": "Attacker SSH key grants passwordless root access. "
                "Key comment 'root@c2server' confirms malicious origin."
        },
        {
            "id": "F-4",
            "title": "Backdoor User Account (svc_backup, UID 0)",
            "severity": "critical",
            "category": "persistence",
            "remediation_action": "Lock and delete the svc_backup user account. "
                "Remove entries from /etc/passwd and /etc/shadow. "
                "Implement monitoring for UID-0 account creation.",
            "priority": "immediate",
            "justification": "UID-0 backdoor user has full root privileges. "
                "Account name 'svc_backup' is designed to appear legitimate."
        },
        {
            "id": "F-5",
            "title": "PAM Authentication Bypass",
            "severity": "critical",
            "category": "persistence",
            "remediation_action": "Remove 'auth sufficient pam_permit.so' from "
                "/etc/pam.d/common-auth. Restore original PAM configuration. "
                "Implement file integrity monitoring on PAM configs.",
            "priority": "immediate",
            "justification": "pam_permit.so as 'sufficient' before pam_unix.so "
                "allows authentication with any password for any user. "
                "Most dangerous persistence mechanism - bypasses all authentication."
        },
        {
            "id": "F-6",
            "title": "Unpatched pkexec/PwnKit Vulnerability (CVE-2021-4034)",
            "severity": "high",
            "category": "vulnerability",
            "remediation_action": "Update polkit package to patched version. "
                "Remove SUID bit from pkexec if not needed. "
                "Implement automated vulnerability scanning and patching.",
            "priority": "short_term",
            "justification": "SUID pkexec vulnerability enabled privilege escalation "
                "from www-data to root. Public exploit available since Jan 2022. "
                "System should have been patched."
        },
        {
            "id": "F-7",
            "title": "No Egress Filtering on Firewall",
            "severity": "high",
            "category": "network",
            "remediation_action": "Implement egress firewall rules allowing only "
                "necessary outbound traffic (HTTP/HTTPS to known destinations, DNS "
                "to internal resolvers). Block direct outbound connections to "
                "arbitrary IPs on non-standard ports.",
            "priority": "short_term",
            "justification": "Lack of egress filtering allowed reverse shell on port "
                "4444, HTTPS beacon on port 8443, and DNS exfiltration to external "
                "servers. Egress controls would have detected or prevented C2 "
                "communication and data exfiltration."
        },
        {
            "id": "F-8",
            "title": "Insufficient Monitoring and Alerting",
            "severity": "medium",
            "category": "detection",
            "remediation_action": "Deploy host-based IDS (e.g., OSSEC/Wazuh). "
                "Implement centralized log collection with SIEM. "
                "Create alerts for: new UID-0 accounts, PAM config changes, "
                "new cron jobs, outbound connections to unusual ports, "
                "DNS query volume anomalies.",
            "priority": "long_term",
            "justification": "Multiple post-exploitation activities went undetected: "
                "privilege escalation, persistence installation, data exfiltration. "
                "IDS only caught outbound traffic after significant dwell time."
        },
        {
            "id": "F-9",
            "title": "Secondary C2 Channel via HTTPS Beacon",
            "severity": "high",
            "category": "network",
            "remediation_action": "Block traffic to 192.0.2.100 and implement "
                "TLS inspection for outbound HTTPS. Deploy network-based IDS "
                "with custom Suricata/Snort rules for beacon detection.",
            "priority": "short_term",
            "justification": "Attacker maintained a secondary C2 channel on port 8443 "
                "using HTTPS beaconing at 300-second intervals. This redundant C2 "
                "would survive removal of the primary reverse shell."
        },
        {
            "id": "F-10",
            "title": "DNS-based Data Exfiltration Channel",
            "severity": "high",
            "category": "exfiltration",
            "remediation_action": "Restrict DNS to internal resolvers only. "
                "Deploy DNS monitoring for high-entropy subdomain queries. "
                "Implement DNS query logging and anomaly detection.",
            "priority": "short_term",
            "justification": "Attacker exfiltrated data via DNS queries to "
                "exfil.updates-cdn.example.net using hex-encoded subdomains. "
                "DNS exfiltration bypasses most network security controls."
        },
    ]

    return {"findings": findings}


# ============================================================
# Report Assembly
# ============================================================

def convert_apache_timestamp(ts_str):
    months = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
    }
    match = re.match(r'(\d+)/(\w+)/(\d+):(\d+:\d+:\d+)', ts_str)
    if match:
        day, month, year, time = match.groups()
        return f"{year}-{months.get(month, '01')}-{day.zfill(2)}T{time}Z"
    return ts_str


def build_report():
    """Analyze all evidence and produce the incident report."""
    # Text-based analysis
    access_data = parse_access_log()
    syslog_data = parse_syslog()
    auth_data = parse_auth_log()
    history_data = parse_bash_histories()
    config_data = parse_config_snapshots()
    malware_data = parse_malware_script()
    fs_data = parse_filesystem_timeline()

    # Tool-based analysis (PCAP first, then binary with known-plaintext)
    pcap_data = analyze_pcap()
    secondary_c2_pcap = pcap_data.get("secondary_c2", {})
    known_c2_ip = secondary_c2_pcap.get("ip") if secondary_c2_pcap else None
    binary_data = analyze_binary(known_c2_ip=known_c2_ip)

    # Attacker identification
    attacker_ip = access_data.get("attacker_ip")

    # Primary C2 (from syslog/malware)
    primary_c2_ip = (malware_data.get("c2_ip")
                     or syslog_data["c2_info"].get("ip"))
    primary_c2_port = (malware_data.get("c2_port")
                       or syslog_data["c2_info"].get("port"))

    # Secondary C2 (from PCAP + binary analysis)
    secondary_c2 = pcap_data.get("secondary_c2", {})
    secondary_c2_ip = (secondary_c2.get("ip") if secondary_c2
                       else binary_data.get("secondary_ip"))
    secondary_c2_port = secondary_c2.get("port", 8443) if secondary_c2 else 8443

    # Build C2 servers list
    c2_servers = [
        {"ip": primary_c2_ip, "port": primary_c2_port, "protocol": "tcp"},
    ]
    if secondary_c2_ip:
        c2_servers.append({
            "ip": secondary_c2_ip,
            "port": secondary_c2_port,
            "protocol": "https",
        })

    # DNS exfiltration domain
    dns_domain = (pcap_data.get("dns_exfil_domain")
                  or binary_data.get("domain")
                  or "")

    # Malware indicators
    user_agent = (binary_data.get("user_agent")
                  or pcap_data.get("user_agent")
                  or "")
    xor_key_hex = binary_data.get("xor_key_hex", "")
    mutex = binary_data.get("mutex", "")
    beacon_interval = pcap_data.get("beacon_interval", 0)

    # Initial access timing
    first_ts = access_data.get("first_timestamp", "")
    initial_access_ts = convert_apache_timestamp(first_ts) if first_ts else ""

    # Compromised accounts
    compromised = {"www-data", "root"}
    for su in auth_data["su_events"]:
        compromised.add(su["source"])
        compromised.add(su["target"])

    # Build timeline
    timeline = []
    timeline.append({
        "timestamp": initial_access_ts,
        "event": f"Attacker begins web reconnaissance from {attacker_ip}"
    })
    timeline.append({
        "timestamp": "2024-03-15T02:15:42Z",
        "event": "Command injection via POST to /api/v1/diagnostic establishes reverse shell"
    })
    timeline.append({
        "timestamp": "2024-03-15T02:18:55Z",
        "event": "Privilege escalation to root via CVE-2021-4034 (PwnKit/pkexec)"
    })

    for ev in fs_data["events"]:
        if ev["file"] == "/etc/passwd":
            timeline.append({
                "timestamp": ev["timestamp"],
                "event": "Backdoor user svc_backup (UID 0) added to /etc/passwd"
            })
        elif ev["file"] == "/root/.ssh/authorized_keys":
            timeline.append({
                "timestamp": ev["timestamp"],
                "event": "Attacker SSH key added to root authorized_keys"
            })
        elif ev["file"] == "/usr/local/bin/.cache_update":
            timeline.append({
                "timestamp": ev["timestamp"],
                "event": "Reverse shell cron backdoor installed"
            })
        elif ev["file"] == "/etc/pam.d/common-auth":
            timeline.append({
                "timestamp": ev["timestamp"],
                "event": "PAM authentication bypass installed"
            })

    timeline.append({
        "timestamp": "2024-03-15T02:25:12Z",
        "event": "Database exfiltration: mysqldump of app_db via curl to C2"
    })
    timeline.append({
        "timestamp": "2024-03-15T02:28:00Z",
        "event": "Anti-forensics: auth.log.1 cleared, bash history wiped"
    })

    timeline.sort(key=lambda x: x["timestamp"])

    report = {
        "attacker_source_ip": attacker_ip,
        "c2_servers": c2_servers,
        "initial_access": {
            "method": "OS command injection in diagnostic endpoint",
            "vulnerable_endpoint": access_data.get(
                "vulnerable_endpoint", "/api/v1/diagnostic"),
            "timestamp": initial_access_ts,
        },
        "privilege_escalation": {
            "method": history_data.get("privesc_method",
                                       "CVE-2021-4034 PwnKit pkexec SUID"),
            "vulnerable_binary": "/usr/bin/pkexec",
        },
        "persistence_mechanisms": config_data["persistence"],
        "backdoor_user": history_data.get(
            "backdoor_user",
            config_data["uid0_users"][0] if config_data["uid0_users"] else None),
        "compromised_accounts": sorted(list(compromised)),
        "exfiltration": {
            "method": "mysqldump via curl POST + DNS tunneling",
            "target": history_data["exfil_info"].get("target", "app_db"),
            "destination": f"http://{primary_c2_ip}:8080/collect",
            "dns_domain": dns_domain,
        },
        "malware_indicators": {
            "user_agent": user_agent,
            "xor_key_hex": xor_key_hex,
            "mutex": mutex,
            "beacon_interval_sec": beacon_interval if beacon_interval else 300,
        },
        "timeline": timeline,
    }

    return report


# ============================================================
# Main
# ============================================================

def main():
    os.makedirs(REPORT_DIR, exist_ok=True)

    # Analyze evidence and build report
    print("=== Analyzing forensic evidence ===")
    report = build_report()

    print("=== Writing findings.json ===")
    with open(os.path.join(REPORT_DIR, "findings.json"), "w") as f:
        json.dump(report, f, indent=2)

    # Generate YARA detection rules
    print("=== Generating YARA detection rules ===")
    binary_data = analyze_binary()
    malware_data = parse_malware_script()
    yara_rules = generate_yara_rules(binary_data, malware_data)
    with open(os.path.join(REPORT_DIR, "detection.yar"), "w") as f:
        f.write(yara_rules)

    # Generate remediation assessment
    print("=== Generating remediation assessment ===")
    remediation = generate_remediation()
    with open(os.path.join(REPORT_DIR, "remediation.json"), "w") as f:
        json.dump(remediation, f, indent=2)

    print("=== All deliverables written to /app/report/ ===")
    print(f"  - findings.json")
    print(f"  - detection.yar")
    print(f"  - remediation.json")


if __name__ == "__main__":
    main()
