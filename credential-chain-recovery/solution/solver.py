#!/usr/bin/env python3

"""
Adversarial Incident Forensics Solver

Recovers the genuine proof flag by discriminating honeypot from genuine
artifacts, tracing the correct credential chain, implementing a custom
XOR decryptor, and designing firewall countermeasures.

Steps:
  1. Analyze server logs -> identify honeypot (THPot) vs genuine (prod-api)
  2. Parse PCAP -> extract Basic Auth creds, label via log correlation
  3. Query DB metadata -> identify genuine table and hash algorithm
  4. Crack genuine service_accounts hashes (sha256(password:salt))
  5. Unlock ZIP with svc_archive password
  6. Read engagement notes -> learn cipher_fragment.bin decryption method
  7. Derive XOR key from SHA-256(genuine_operator_password)[:16]
  8. Decrypt cipher_fragment.bin -> identify genuine GPG report
  9. Crack production host shadow entries -> root password
  10. Construct GPG passphrase and decrypt genuine report -> flag
  11. Write classification.json and firewall_rules.sh
"""

import base64
import crypt
import hashlib
import json
import os
import re
import sqlite3
import struct
import subprocess
import sys


# ── Step 1: Analyze server access logs ─────────────────────────────────────

print("=" * 60)
print("Step 1: Analyzing server access logs for honeypot indicators")
print("=" * 60)

with open("/app/incident/server_access.log") as f:
    log_lines = [line.strip() for line in f if line.strip()]

honeypot_ips = set()
genuine_ips = set()

for line in log_lines:
    src_match = re.search(r'src=(\S+)', line)
    tag_match = re.search(r'tag=(\S+)', line)
    if src_match and tag_match:
        ip = src_match.group(1)
        tag = tag_match.group(1)
        if tag.startswith("THPot"):
            honeypot_ips.add(ip)
        elif tag == "prod-api":
            genuine_ips.add(ip)

# Remove internal infrastructure IPs (10.10.14.x servers)
genuine_external = {ip for ip in genuine_ips if not ip.startswith("10.10.14.")}
print(f"[+] Honeypot source IPs: {honeypot_ips}")
print(f"[+] Genuine external attacker IPs: {genuine_external}")


# ── Step 2: Parse PCAP and extract credentials ────────────────────────────

print()
print("=" * 60)
print("Step 2: Extracting credentials from PCAP")
print("=" * 60)


def parse_pcap(filepath):
    """Parse PCAP, return list of (src_ip, dst_port, payload_text)."""
    results = []
    with open(filepath, 'rb') as f:
        ghdr = f.read(24)
        if len(ghdr) < 24:
            return results
        magic = struct.unpack('<I', ghdr[:4])[0]
        if magic == 0xa1b2c3d4:
            endian = '<'
        elif magic == 0xd4c3b2a1:
            endian = '>'
        else:
            return results

        while True:
            pkt_hdr = f.read(16)
            if len(pkt_hdr) < 16:
                break
            _, _, caplen, _ = struct.unpack(f'{endian}IIII', pkt_hdr)
            pkt_data = f.read(caplen)
            if len(pkt_data) < caplen:
                break
            if len(pkt_data) <= 54:
                continue
            eth_type = struct.unpack('!H', pkt_data[12:14])[0]
            if eth_type != 0x0800:
                continue
            ip_ihl = (pkt_data[14] & 0x0F) * 4
            ip_proto = pkt_data[14 + 9]
            if ip_proto != 6:  # TCP only
                continue
            src_ip = '.'.join(str(b) for b in pkt_data[26:30])
            tcp_start = 14 + ip_ihl
            if len(pkt_data) < tcp_start + 13:
                continue
            dst_port = struct.unpack('!H', pkt_data[tcp_start+2:tcp_start+4])[0]
            tcp_doff = ((pkt_data[tcp_start + 12] >> 4) & 0x0F) * 4
            payload_start = tcp_start + tcp_doff
            if payload_start >= len(pkt_data):
                continue
            payload = pkt_data[payload_start:]
            try:
                text = payload.decode('ascii', errors='ignore')
                if text:
                    results.append((src_ip, dst_port, text))
            except Exception:
                pass
    return results


packets = parse_pcap("/app/incident/capture.pcap")

pcap_credentials = {}
for src_ip, dst_port, text in packets:
    m = re.search(r'Authorization:\s*Basic\s+(\S+)', text)
    if m:
        decoded = base64.b64decode(m.group(1)).decode()
        user, password = decoded.split(':', 1)
        if src_ip in honeypot_ips:
            label = "HONEYPOT"
        elif src_ip in genuine_external:
            label = "GENUINE"
        else:
            label = "UNKNOWN"
        pcap_credentials[src_ip] = {
            "user": user, "password": password,
            "dst_port": dst_port, "label": label
        }
        print(f"[+] [{label}] PCAP: {src_ip} -> :{dst_port}  "
              f"{user}:{password}")

genuine_pcap_cred = None
honeypot_pcap_cred = None
for ip, cred in pcap_credentials.items():
    if cred["label"] == "GENUINE":
        genuine_pcap_cred = cred
        genuine_pcap_ip = ip
    elif cred["label"] == "HONEYPOT":
        honeypot_pcap_cred = cred
        honeypot_pcap_ip = ip

if not genuine_pcap_cred:
    print("[-] FATAL: Could not identify genuine PCAP credential")
    sys.exit(1)

genuine_operator_password = genuine_pcap_cred["password"]
print(f"[+] Genuine operator password: {genuine_operator_password}")


# ── Step 3: Query database metadata and identify correct table ─────────────

print()
print("=" * 60)
print("Step 3: Analyzing database schema and cracking genuine hashes")
print("=" * 60)

conn = sqlite3.connect("/app/incident/app_database.db")
cur = conn.cursor()

cur.execute("SELECT table_name, environment, hash_algorithm "
            "FROM schema_metadata")
metadata = {row[0]: {"env": row[1], "hash_alg": row[2]}
            for row in cur.fetchall()}

print("[*] Database schema metadata:")
for table, info in metadata.items():
    print(f"    {table}: env={info['env']}, hash={info['hash_alg']}")

genuine_table = None
honeypot_table = None
for table, info in metadata.items():
    if "production" in info["env"]:
        genuine_table = table
    if "honeypot" in info["env"]:
        honeypot_table = table

print(f"[+] Genuine table: {genuine_table}")
print(f"[+] Honeypot table: {honeypot_table}")

# Load wordlist
with open("/app/incident/recon_wordlist.txt") as f:
    wordlist = [line.strip() for line in f if line.strip()]
print(f"[*] Loaded {len(wordlist)} words from wordlist")

# Crack service_accounts using sha256(password + ":" + salt)
cur.execute("SELECT account_name, credential_hash, salt "
            "FROM service_accounts")
service_accounts = cur.fetchall()

cracked_genuine = {}
for account_name, pw_hash, salt in service_accounts:
    for word in wordlist:
        test_hash = hashlib.sha256(
            (word + ":" + salt).encode()).hexdigest()
        if test_hash == pw_hash:
            cracked_genuine[account_name] = word
            print(f"[+] Cracked: {account_name}:{word}")
            break

conn.close()

zip_password = cracked_genuine.get("svc_archive")
if not zip_password:
    print("[-] FATAL: Could not crack svc_archive password")
    sys.exit(1)
print(f"[+] ZIP password (svc_archive): {zip_password}")


# ── Step 4: Unlock ZIP archive ────────────────────────────────────────────

print()
print("=" * 60)
print("Step 4: Extracting loot archive")
print("=" * 60)

os.makedirs("/tmp/loot", exist_ok=True)
result = subprocess.run(
    ["unzip", "-o", "-P", zip_password,
     "/app/incident/loot_archive.zip", "-d", "/tmp/loot"],
    capture_output=True, text=True)
if result.returncode != 0:
    print(f"[-] FATAL: unzip failed: {result.stderr}")
    sys.exit(1)

with open("/tmp/loot/engagement_notes.txt") as f:
    notes = f.read()
print("[+] Archive extracted. Engagement notes read.")


# ── Step 5: Decrypt cipher_fragment.bin with custom XOR ───────────────────

print()
print("=" * 60)
print("Step 5: Decrypting cipher fragment (custom XOR)")
print("=" * 60)

# Key: first 16 bytes of SHA-256 of genuine operator password
xor_key = hashlib.sha256(genuine_operator_password.encode()).digest()[:16]

with open("/app/incident/cipher_fragment.bin", "rb") as f:
    encrypted = f.read()

decrypted = bytes(
    encrypted[i] ^ xor_key[i % len(xor_key)] for i in range(len(encrypted)))
cipher_text = decrypted.decode('utf-8', errors='replace')
print("[+] Decrypted cipher fragment:")
print(cipher_text)

# Parse which report is genuine
genuine_report = None
decoy_report = None
for line in cipher_text.split('\n'):
    if 'GENUINE' in line and '->' in line:
        genuine_report = line.split('->')[-1].strip()
    if 'DECOY' in line and '->' in line:
        decoy_report = line.split('->')[-1].strip()

print(f"[+] Genuine report: {genuine_report}")
print(f"[+] Decoy report: {decoy_report}")


# ── Step 6: Crack production host shadow entries ──────────────────────────

print()
print("=" * 60)
print("Step 6: Cracking production host shadow entries")
print("=" * 60)

with open("/app/incident/shadow_dump.txt") as f:
    shadow_content = f.read()

current_host = None
shadow_entries = []
for line in shadow_content.split('\n'):
    line = line.strip()
    if line.startswith("# === Host:"):
        current_host = line.split("Host:")[1].strip().rstrip("=").strip()
    elif line and not line.startswith("#"):
        parts = line.split(':')
        if (len(parts) >= 2 and parts[1]
                and parts[1] not in ('*', '!', '!!', 'x')):
            shadow_entries.append((current_host, parts[0], parts[1]))

# Only crack entries from the production host
prod_host = "prod-web01.internal"
shadow_cracked = {}
for host, username, hash_val in shadow_entries:
    if host != prod_host:
        continue
    for word in wordlist:
        if crypt.crypt(word, hash_val) == hash_val:
            shadow_cracked[username] = word
            print(f"[+] Cracked {host} {username}:{word}")
            break

root_password = shadow_cracked.get("root")
if not root_password:
    print("[-] FATAL: Could not crack production root password")
    sys.exit(1)


# ── Step 7: Decrypt genuine GPG report ────────────────────────────────────

print()
print("=" * 60)
print("Step 7: Decrypting genuine assessment report")
print("=" * 60)

gpg_passphrase = f"{genuine_operator_password}:{root_password}"
print(f"[*] GPG passphrase: {gpg_passphrase}")

gnupg_home = "/tmp/_gnupg_solve"
os.makedirs(gnupg_home, mode=0o700, exist_ok=True)
env = dict(os.environ, GNUPGHOME=gnupg_home)

result = subprocess.run(
    ["gpg", "--batch",
     "--passphrase", gpg_passphrase,
     "--pinentry-mode", "loopback",
     "-d", f"/app/incident/{genuine_report}"],
    capture_output=True, text=True, env=env)

if result.returncode != 0:
    print(f"[-] FATAL: GPG decryption failed: {result.stderr}")
    sys.exit(1)

report = result.stdout
print("[+] Report decrypted successfully")

# Extract flag
m = re.search(r'ACME-REDTEAM-FLAG\{[a-f0-9-]+\}', report)
if not m:
    print("[-] FATAL: Could not find proof flag in report")
    sys.exit(1)

flag = m.group(0)
with open("/app/answer.txt", 'w') as f:
    f.write(flag + '\n')
print(f"[+] Flag: {flag}")


# ── Step 8: Write classification JSON ─────────────────────────────────────

print()
print("=" * 60)
print("Step 8: Writing artifact classification")
print("=" * 60)

# Determine honeypot shadow host (the non-production one)
honeypot_shadow = None
for host, _, _ in shadow_entries:
    if host and host != prod_host:
        honeypot_shadow = host
        break

classification = {
    "genuine": {
        "pcap_session": genuine_pcap_ip,
        "database_table": genuine_table,
        "shadow_host": prod_host,
        "encrypted_report": genuine_report
    },
    "honeypot": {
        "pcap_session": honeypot_pcap_ip,
        "database_table": honeypot_table,
        "shadow_host": honeypot_shadow,
        "encrypted_report": decoy_report
    }
}

with open("/app/classification.json", 'w') as f:
    json.dump(classification, f, indent=2)
print("[+] Classification written to /app/classification.json")
print(json.dumps(classification, indent=2))


# ── Step 9: Design firewall countermeasures ───────────────────────────────

print()
print("=" * 60)
print("Step 9: Designing firewall countermeasures")
print("=" * 60)

firewall_script = f"""#!/bin/bash
# ACME Corp Incident Response - Firewall Countermeasures
# Based on forensic analysis of engagement ACME-2024-RT-007
#
# Blocks identified attack vectors while preserving legitimate services.

# Flush existing INPUT rules for clean state
iptables -F INPUT

# Block the identified attacker source IP
iptables -A INPUT -s {genuine_pcap_ip} -j DROP

# Rate-limit new connections to the attacked service port (8443)
iptables -A INPUT -p tcp --dport 8443 -m conntrack --ctstate NEW \\
    -m limit --limit 5/minute --limit-burst 3 -j ACCEPT
iptables -A INPUT -p tcp --dport 8443 -m conntrack --ctstate NEW -j DROP

# Allow established and related connections
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# Allow legitimate services (from network scan)
iptables -A INPUT -p tcp --dport 22 -j ACCEPT
iptables -A INPUT -p tcp --dport 80 -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j ACCEPT

# Allow loopback
iptables -A INPUT -i lo -j ACCEPT

# Default deny all other inbound
iptables -A INPUT -j DROP
"""

firewall_path = "/app/firewall_rules.sh"
with open(firewall_path, 'w') as f:
    f.write(firewall_script)
os.chmod(firewall_path, 0o755)
print(f"[+] Firewall rules written to {firewall_path}")


# ── Step 10: Evaluate threat and deception ──────────────────────────────

print()
print("=" * 60)
print("Step 10: Evaluating attack chain and deception infrastructure")
print("=" * 60)

# The 'operator' credential (from PCAP) is the most critical single link:
#   - Used to derive XOR key for cipher_fragment.bin decryption (step 5)
#   - Used as part of GPG passphrase construction (step 7)
# All other credentials (svc_archive, root) affect only ONE downstream step.
# Rotating just the operator credential would break TWO chain steps.
critical_cred = "operator"

# The 'tag' field in server_access.log is the primary honeypot indicator.
# It directly labels sessions as THPot-* (honeypot) vs prod-api (genuine).
# Other indicators exist (different DB hash algorithms, different paths)
# but require more analysis. The tag field is the most direct signal.
honeypot_indicator = "tag"

# Deception rating: The honeypot has realistic credential tables, its own
# shadow host, and a convincing decoy report with a valid-looking flag.
# However, the 'THPot' tag prefix in the server logs is a dead giveaway
# for anyone examining the logs. Rating: 5/10 — decent infrastructure
# undermined by overt logging indicators.
deception_rating = 5

# The highest-impact single remediation: enforce mutual TLS on the
# production API to prevent credential capture via network sniffing.
# The operator password capture was the entry point for the entire chain.
priority_fix = (
    "Enforce mutual TLS authentication on the production service API "
    "(port 8443) to prevent plaintext credential capture from network "
    "traffic, which was the initial entry point for the entire attack chain"
)

threat_assessment = {
    "critical_entry_credential": critical_cred,
    "honeypot_primary_indicator": honeypot_indicator,
    "deception_rating": deception_rating,
    "recommended_priority_fix": priority_fix
}

with open("/app/threat_assessment.json", 'w') as f:
    json.dump(threat_assessment, f, indent=2)
print("[+] Threat assessment written to /app/threat_assessment.json")
print(json.dumps(threat_assessment, indent=2))


print()
print("=" * 60)
print("DONE - Incident forensics, threat evaluation, and defense complete.")
print("=" * 60)
