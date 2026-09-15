#!/usr/bin/env python3
"""Analyze the deployed Suricata rules and PCAP, diagnose detection failures,
and write corrected rules and threshold configuration.

"""
import re
import shutil
import subprocess

# ============================================================
# Step 1: Analyze the PCAP to catalog attack vectors
# ============================================================
print("=== Analyzing incident PCAP ===")

# DNS traffic — look for tunneling indicators
result = subprocess.run(
    ["tcpdump", "-r", "/app/incident.pcap", "-nn", "udp port 53"],
    capture_output=True, text=True
)
print("DNS traffic found:")
for line in result.stdout.strip().split("\n"):
    print(f"  {line}")

# TCP connections on suspicious ports
for port in [4444, 8888, 9999]:
    result = subprocess.run(
        ["tcpdump", "-r", "/app/incident.pcap", "-nn", f"tcp dst port {port}"],
        capture_output=True, text=True
    )
    count = len([l for l in result.stdout.strip().split("\n") if l.strip()])
    print(f"TCP dst port {port}: {count} packets")

# ICMP traffic analysis
result = subprocess.run(
    ["tcpdump", "-r", "/app/incident.pcap", "-nn", "icmp"],
    capture_output=True, text=True
)
icmp_lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
print(f"ICMP packets: {len(icmp_lines)}")

# HTTP traffic with User-Agent inspection
result = subprocess.run(
    ["tcpdump", "-r", "/app/incident.pcap", "-nn", "-A", "tcp dst port 80"],
    capture_output=True, text=True
)
if "Trojan" in result.stdout:
    print("Found HTTP traffic with 'Trojan' in payload (User-Agent)")

# ============================================================
# Step 2: Read deployed rules and diagnose bugs
# ============================================================
print("\n=== Diagnosing deployed rules ===")
with open("/app/rules/deployed.rules") as f:
    deployed = f.read()

print("Deployed rules:")
print(deployed)

# Diagnosis:
# SID 2100001: content:"evil-c2.example.net" without dns.query sticky buffer.
#   DNS wire format uses length-prefixed labels (\x07evil-c2\x07example\x03net),
#   not dot-separated strings. Raw content match will never find the dot-separated
#   domain name in the actual packet payload. Fix: add dns.query; before content.
print("SID 2100001: MISSING dns.query sticky buffer — raw content can't match "
      "DNS wire-format length-prefixed labels")

# SID 2100002: flow:established,from_server — wrong direction. The reverse shell
#   payload (/bin/sh) is sent FROM the victim (TCP client/SYN initiator) TO the
#   attacker (server), which is to_server direction. Fix: change to to_server.
print("SID 2100002: WRONG flow direction — from_server checks attacker→victim, "
      "but payload goes victim→attacker (to_server)")

# SID 2100003: itype:0 is Echo Reply, but scanning sends Echo Request (itype:8).
#   Fix: change itype:0 to itype:8.
print("SID 2100003: WRONG ICMP type — itype:0 is Echo Reply, scanners send "
      "Echo Request (itype:8)")

# SID 2100004: http.host matches Host header, but "Trojan" is in User-Agent.
#   Fix: change http.host to http.user_agent.
print("SID 2100004: WRONG sticky buffer — http.host inspects Host header, "
      "need http.user_agent for User-Agent matching")

# SID 2100005: Port 8888 but exfiltration traffic uses port 9999.
#   Fix: change 8888 to 9999.
print("SID 2100005: WRONG port — rule targets 8888 but traffic uses 9999")

# Threshold.config: track by_dst suppresses when 10.0.0.1 is destination,
#   but trusted host generates traffic as source. Fix: change to by_src.
print("threshold.config: WRONG track direction — by_dst but host is source")

# ============================================================
# Step 3: Write corrected rules
# ============================================================
print("\n=== Writing corrected rules ===")
corrected_rules = """\
# SID 2100001: DNS C2 Tunneling - queries to evil-c2.example.net subdomains
# FIX: Added dns.query sticky buffer for normalized domain matching
alert dns any any -> any any (msg:"DNS C2 Tunneling to evil-c2.example.net"; dns.query; content:"evil-c2.example.net"; nocase; sid:2100001; rev:2;)

# SID 2100002: Reverse Shell - outbound TCP to port 4444 with shell invocation
# FIX: Changed flow direction from from_server to to_server
alert tcp any any -> any 4444 (msg:"Reverse Shell Connection Detected"; flow:established,to_server; content:"/bin/"; nocase; sid:2100002; rev:2;)

# SID 2100003: ICMP Scanning - echo requests, one alert per source per 60s
# FIX: Changed itype from 0 (echo reply) to 8 (echo request)
alert icmp any any -> any any (msg:"ICMP Scan Detected"; itype:8; threshold: type limit, track by_src, count 1, seconds 60; sid:2100003; rev:2;)

# SID 2100004: Malicious HTTP User-Agent containing "Trojan"
# FIX: Changed sticky buffer from http.host to http.user_agent
alert http any any -> any any (msg:"Suspicious HTTP User-Agent - Trojan"; http.user_agent; content:"Trojan"; nocase; sid:2100004; rev:2;)

# SID 2100005: Binary Exfiltration Protocol - magic bytes DEADBEEF
# FIX: Changed destination port from 8888 to 9999
alert tcp any any -> any 9999 (msg:"Binary Exfiltration Protocol Detected"; flow:established,to_server; content:"|DE AD BE EF|"; offset:0; depth:4; sid:2100005; rev:2;)
"""

with open("/app/rules/local.rules", "w") as f:
    f.write(corrected_rules)
print("Corrected rules written to /app/rules/local.rules")

# ============================================================
# Step 4: Fix threshold configuration
# ============================================================
print("\n=== Fixing threshold configuration ===")
corrected_threshold = (
    "# Suppress all alerts from trusted monitoring host (source)\n"
    "suppress gen_id 1, sig_id 0, track by_src, ip 10.0.0.1\n"
)
with open("/app/threshold.config", "w") as f:
    f.write(corrected_threshold)
print("Corrected threshold.config written")

# ============================================================
# Step 5: Prepare Suricata configuration with threshold file
# ============================================================
print("\n=== Preparing Suricata configuration ===")
shutil.copy("/etc/suricata/suricata.yaml", "/app/suricata.yaml")

with open("/app/suricata.yaml") as f:
    config = f.read()

config = re.sub(
    r"#?\s*threshold-file:.*",
    "threshold-file: /app/threshold.config",
    config,
)
if "threshold-file" not in config:
    config += "\nthreshold-file: /app/threshold.config\n"

with open("/app/suricata.yaml", "w") as f:
    f.write(config)
print("Suricata config updated with threshold-file path")
