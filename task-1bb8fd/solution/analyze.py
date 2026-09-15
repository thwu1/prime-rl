#!/usr/bin/env python3

"""
Analyze /app/evidence/incident.pcap and /app/evidence/preliminary_report.json to:
1. Reconstruct the complete attack chain from pcap analysis
2. Audit the preliminary report and identify all factual errors
3. Generate Suricata IDS detection rules for each attack phase
4. Assess severity of each attack phase with technical justification

Produces:
  /app/output/corrected_report.json
  /app/output/detection.rules
"""

import json
import os
import re
from collections import defaultdict
from urllib.parse import unquote_plus

from scapy.all import rdpcap, IP, TCP, UDP, ICMP, DNS, DNSQR, DNSRR, Raw, conf

conf.verb = 0

PCAP = "/app/evidence/incident.pcap"
PRELIM_REPORT = "/app/evidence/preliminary_report.json"
OUTPUT_DIR = "/app/output"
CORRECTED_REPORT = os.path.join(OUTPUT_DIR, "corrected_report.json")
RULES_FILE = os.path.join(OUTPUT_DIR, "detection.rules")

pkts = rdpcap(PCAP)


# ═══════════════════════════════════════════════════════════════
# PHASE 1 — Identify port scan & attacker
# ═══════════════════════════════════════════════════════════════

syn_probes = defaultdict(lambda: defaultdict(set))

for p in pkts:
    if IP in p and TCP in p:
        if str(p[TCP].flags) == "S":
            syn_probes[p[IP].src][p[IP].dst].add(p[TCP].dport)

attacker_ip = None
victim_ip = None
scanned_ports = []
max_count = 0

for src, targets in syn_probes.items():
    for dst, ports in targets.items():
        if len(ports) > max_count:
            max_count = len(ports)
            attacker_ip = src
            victim_ip = dst
            scanned_ports = sorted(ports)

# Find open ports (SYN-ACK responses from victim to attacker)
open_ports = set()
for p in pkts:
    if IP in p and TCP in p:
        if str(p[TCP].flags) == "SA":
            if p[IP].src == victim_ip and p[IP].dst == attacker_ip:
                open_ports.add(p[TCP].sport)
open_ports = sorted(open_ports)

print(f"[+] Attacker: {attacker_ip}")
print(f"[+] Victim: {victim_ip}")
print(f"[+] Scanned ports: {scanned_ports}")
print(f"[+] Open ports: {open_ports}")


# ═══════════════════════════════════════════════════════════════
# PHASE 2 — Extract HTTP exploitation details
# ═══════════════════════════════════════════════════════════════

exploit_endpoint = None
exploit_parameter = None
exploit_payloads = []
malware_url = None

for p in pkts:
    if IP not in p or TCP not in p or Raw not in p:
        continue
    if p[IP].src != attacker_ip or p[TCP].dport not in (80, 8080, 8443):
        continue

    try:
        data = p[Raw].load.decode("utf-8", errors="ignore")
    except Exception:
        continue

    if "POST" not in data:
        continue

    uri_match = re.search(r"POST\s+(\S+)", data)
    body_idx = data.find("\r\n\r\n")
    if uri_match is None or body_idx < 0:
        continue

    uri = uri_match.group(1)
    body = data[body_idx + 4:]

    if "search=" not in body:
        continue

    raw_val = body.split("search=")[1].split("&")[0].split("\r")[0].split("\n")[0]
    decoded_val = unquote_plus(raw_val)

    # Skip benign queries
    if decoded_val == "test":
        continue

    if exploit_endpoint is None:
        exploit_endpoint = uri
        exploit_parameter = "search"

    exploit_payloads.append(decoded_val)

    # Check for malware download URL
    url_match = re.search(r"https?://[^\s&|;]+", decoded_val)
    if url_match:
        malware_url = url_match.group(0)

print(f"[+] Exploit endpoint: {exploit_endpoint}")
print(f"[+] Exploit parameter: {exploit_parameter}")
print(f"[+] Payloads: {exploit_payloads}")
print(f"[+] Malware URL: {malware_url}")


# ═══════════════════════════════════════════════════════════════
# PHASE 3 — Decode DNS C2 tunneling
# ═══════════════════════════════════════════════════════════════

HEX_CHARS = set("0123456789abcdef")


def is_hex_str(s):
    return len(s) >= 4 and len(s) % 2 == 0 and all(c in HEX_CHARS for c in s.lower())


def try_hex_decode(s):
    """Try to hex-decode a string to UTF-8."""
    try:
        return bytes.fromhex(s).decode("utf-8")
    except Exception:
        return None


# Pass 1: identify C2 domain from TXT queries with hex subdomains
c2_domain = None
c2_query_data = []

for p in pkts:
    if IP not in p or UDP not in p or DNS not in p:
        continue
    dns = p[DNS]
    if dns.qr != 0 or dns.qdcount < 1:
        continue
    qr = dns.qd
    if qr.qtype != 16:  # TXT
        continue

    qname = qr.qname.decode() if isinstance(qr.qname, bytes) else qr.qname
    qname = qname.rstrip(".")
    parts = qname.split(".")
    if len(parts) < 3:
        continue

    subdomain = parts[0]
    rest = ".".join(parts[1:])

    if is_hex_str(subdomain):
        decoded = try_hex_decode(subdomain)
        if decoded:
            if c2_domain is None:
                c2_domain = rest
            c2_query_data.append(decoded)

print(f"[+] C2 domain: {c2_domain}")
print(f"[+] C2 victim messages: {c2_query_data}")

# Pass 2: extract C2 commands from TXT responses
c2_commands = []

for p in pkts:
    if IP not in p or UDP not in p or DNS not in p:
        continue
    dns = p[DNS]
    if dns.qr != 1 or dns.ancount < 1:
        continue

    try:
        qname = dns.qd.qname.decode() if isinstance(dns.qd.qname, bytes) else dns.qd.qname
        qname = qname.rstrip(".")
    except Exception:
        continue

    if c2_domain is None or not qname.endswith(c2_domain):
        continue

    an = dns.an
    while an and hasattr(an, "type"):
        if an.type == 16:  # TXT
            rdata = an.rdata
            candidates = []
            if isinstance(rdata, bytes):
                candidates.append(rdata)
                if len(rdata) > 1:
                    candidates.append(rdata[1:])  # skip length prefix
            elif isinstance(rdata, str):
                candidates.append(rdata.encode("latin-1"))
            elif isinstance(rdata, list):
                joined = b"".join(
                    x if isinstance(x, bytes) else x.encode("latin-1") for x in rdata
                )
                candidates.append(joined)
                if len(joined) > 1:
                    candidates.append(joined[1:])

            for cand in candidates:
                try:
                    text = cand.decode("ascii").strip()
                except Exception:
                    continue
                if is_hex_str(text):
                    decoded = try_hex_decode(text)
                    if decoded:
                        c2_commands.append(decoded)
                        break

        if hasattr(an, "payload") and isinstance(an.payload, DNSRR):
            an = an.payload
        else:
            break

print(f"[+] C2 commands received: {c2_commands}")


# ═══════════════════════════════════════════════════════════════
# PHASE 4 — Extract exfil parameters from C2, decode ICMP
# ═══════════════════════════════════════════════════════════════

exfil_ip = None
xor_key_hex = None

for cmd in c2_commands:
    if "EXFIL" in cmd and "ICMP" in cmd:
        parts = cmd.split(":")
        for part in parts:
            if re.match(r"\d+\.\d+\.\d+\.\d+$", part):
                exfil_ip = part
            if re.match(r"^[0-9a-f]{8}$", part, re.IGNORECASE):
                xor_key_hex = part.lower()

if xor_key_hex is None:
    print("[!] Could not find XOR key in C2 commands")
    xor_key = b"\x00\x00\x00\x00"
else:
    xor_key = bytes.fromhex(xor_key_hex)

print(f"[+] Exfil relay IP: {exfil_ip}")
print(f"[+] XOR key: {xor_key_hex}")

# Decode ICMP exfiltration payloads
exfil_data = []

for p in pkts:
    if IP not in p or ICMP not in p or Raw not in p:
        continue
    if p[ICMP].type != 8:  # echo request only
        continue
    if exfil_ip and p[IP].dst != exfil_ip:
        continue

    payload = p[Raw].load
    decoded = bytes(
        [payload[i] ^ xor_key[i % len(xor_key)] for i in range(len(payload))]
    )
    try:
        exfil_data.append(decoded.decode("utf-8"))
    except UnicodeDecodeError:
        exfil_data.append(decoded.decode("latin-1"))

print(f"[+] Exfiltrated data lines: {exfil_data}")


# ═══════════════════════════════════════════════════════════════
# PHASE 5 — Audit preliminary report for errors
# ═══════════════════════════════════════════════════════════════

with open(PRELIM_REPORT) as f:
    prelim = json.load(f)

findings = prelim["findings"]
preliminary_errors = []

# Check each finding against ground truth derived from pcap analysis
if findings.get("suspected_attacker_ip") != attacker_ip:
    preliminary_errors.append("suspected_attacker_ip")

attack_type = findings.get("attack_type", "").lower().replace(" ", "_").replace("-", "_")
if attack_type != "command_injection":
    preliminary_errors.append("attack_type")

if findings.get("target_parameter") != exploit_parameter:
    preliminary_errors.append("target_parameter")

if findings.get("c2_protocol", "").lower() != "dns":
    preliminary_errors.append("c2_protocol")

if findings.get("c2_destination", "").rstrip(".").lower() != c2_domain.lower():
    preliminary_errors.append("c2_destination")

if findings.get("exfil_protocol", "").lower() != "icmp":
    preliminary_errors.append("exfil_protocol")

if findings.get("exfil_encoding", "").lower() != "xor":
    preliminary_errors.append("exfil_encoding")

if findings.get("overall_severity", "").lower() not in ("critical", "high"):
    preliminary_errors.append("overall_severity")

if findings.get("reconnaissance_activity") is not True:
    preliminary_errors.append("reconnaissance_activity")

# Check if credentials were actually exfiltrated
has_creds = any(":" in line and line != "CREDENTIALS_DUMP_v2" and line != "END_DUMP"
                for line in exfil_data)
if has_creds and findings.get("credentials_at_risk") is not True:
    preliminary_errors.append("credentials_at_risk")

print(f"[+] Preliminary report errors ({len(preliminary_errors)}): {preliminary_errors}")


# ═══════════════════════════════════════════════════════════════
# PHASE 6 — Generate Suricata detection rules
# ═══════════════════════════════════════════════════════════════

suricata_rules = f"""# Suricata IDS rules for multi-stage network intrusion detection
# Generated from forensic analysis of incident capture

# Phase 1: Reconnaissance - TCP SYN port scan
# Detects systematic SYN probing from a single source to multiple ports
alert tcp any any -> {victim_ip} any (msg:"RECON SYN port scan targeting victim host"; flags:S; threshold:type both, track by_src, count 5, seconds 300; sid:2000001; rev:1;)

# Phase 2a: Exploitation - OS command injection via HTTP POST
# Detects URL-encoded semicolon in POST body to /api/query search parameter
alert tcp any any -> {victim_ip} 8080 (msg:"EXPLOIT Command injection in web application search parameter"; content:"POST"; content:"{exploit_endpoint}"; content:"{exploit_parameter}="; content:"%3B"; sid:2000002; rev:1;)

# Phase 2b: Exploitation - Malware delivery via injected wget command
# Detects wget + implant download in HTTP POST body
alert tcp any any -> {victim_ip} 8080 (msg:"EXPLOIT Malware implant download via command injection"; content:"POST"; content:"wget"; content:"implant"; sid:2000003; rev:1;)

# Phase 3: C2 - DNS TXT query tunneling to C2 domain
# Detects DNS queries containing the C2 domain used for command-and-control
alert udp {victim_ip} any -> any 53 (msg:"C2 DNS TXT tunnel to {c2_domain}"; content:"update-check"; nocase; sid:2000004; rev:1;)

# Phase 4: Exfiltration - ICMP covert channel to external relay
# Detects echo requests with data payloads sent to the exfiltration relay
alert icmp {victim_ip} any -> {exfil_ip} any (msg:"EXFIL ICMP covert channel data exfiltration to relay"; itype:8; dsize:>5; sid:2000005; rev:1;)
"""

os.makedirs(OUTPUT_DIR, exist_ok=True)

with open(RULES_FILE, "w") as f:
    f.write(suricata_rules)

print(f"[+] Suricata rules written to {RULES_FILE}")


# ═══════════════════════════════════════════════════════════════
# PHASE 7 — Severity assessment
# ═══════════════════════════════════════════════════════════════

cred_count = len([d for d in exfil_data if ":" in d
                  and d != "CREDENTIALS_DUMP_v2" and d != "END_DUMP"])

phase_severity = {
    "reconnaissance": {
        "rating": "medium",
        "justification": (
            f"Slow SYN scan of {len(scanned_ports)} TCP ports with ~15-second "
            f"intervals indicates deliberate stealth reconnaissance. While port "
            f"scanning causes no direct damage, the slow timing and targeted scope "
            f"indicate an experienced adversary performing pre-exploitation mapping. "
            f"Discovery of open ports {open_ports} directly enabled the exploitation phase."
        ),
    },
    "exploitation": {
        "rating": "critical",
        "justification": (
            f"OS command injection via the '{exploit_parameter}' parameter at "
            f"{exploit_endpoint} achieved remote code execution as the web application "
            f"user (www-data). The attacker progressed from information disclosure "
            f"(reading /etc/passwd, executing id) to downloading and executing a "
            f"remote implant from {malware_url}, establishing persistent unauthorized "
            f"access. Command injection yielding RCE with payload staging represents "
            f"a critical-severity exploitation chain."
        ),
    },
    "c2": {
        "rating": "high",
        "justification": (
            f"DNS TXT-based C2 tunneling to {c2_domain} with hex-encoded subdomains "
            f"demonstrates sophisticated evasion capabilities. DNS as a transport "
            f"protocol makes blocking difficult without disrupting legitimate name "
            f"resolution. The channel delivered {len(c2_commands)} operational commands "
            f"including the ICMP exfiltration configuration (relay IP and XOR key), "
            f"creating a critical dependency chain between C2 and exfiltration phases."
        ),
    },
    "exfiltration": {
        "rating": "critical",
        "justification": (
            f"ICMP echo request covert channel with 4-byte rotating XOR key "
            f"({xor_key_hex}) exfiltrated {cred_count} credential pairs including "
            f"administrative (admin), database (dbuser), CI/CD deployment (deploy), "
            f"backup service (svc_backup), and infrastructure vault tokens "
            f"(root_token). The XOR key was transmitted exclusively via the DNS C2 "
            f"channel, creating a cross-channel dependency that complicates isolated "
            f"detection. Compromised credentials of this breadth enable lateral "
            f"movement, privilege escalation, and persistent access across the "
            f"entire infrastructure."
        ),
    },
}


# ═══════════════════════════════════════════════════════════════
# Write corrected incident report
# ═══════════════════════════════════════════════════════════════

report = {
    "attacker_ip": attacker_ip,
    "victim_ip": victim_ip,
    "recon_ports_scanned": scanned_ports,
    "recon_ports_open": open_ports,
    "exploit_vector": "command_injection",
    "exploit_endpoint": exploit_endpoint,
    "exploit_parameter": exploit_parameter,
    "malware_download_url": malware_url,
    "c2_protocol": "dns",
    "c2_domain": c2_domain,
    "c2_encoding": "hex",
    "c2_commands": c2_commands,
    "exfil_method": "icmp",
    "exfil_dest_ip": exfil_ip,
    "exfil_encoding": "xor",
    "exfil_key": xor_key_hex,
    "exfil_decoded_data": exfil_data,
    "preliminary_errors": preliminary_errors,
    "phase_severity": phase_severity,
}

with open(CORRECTED_REPORT, "w") as f:
    json.dump(report, f, indent=2)

print(f"\n[+] Corrected report written to {CORRECTED_REPORT}")
print(f"[+] Identified {len(preliminary_errors)} errors in preliminary report")
print(json.dumps(report, indent=2))
