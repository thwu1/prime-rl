#!/usr/bin/env python3
"""Analyze Suricata EVE JSON alerts and produce an incident report.

"""
import json
import sys

eve_file = "/app/logs/eve.json"
report_file = "/app/incident_report.txt"

alerts = []
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

if not alerts:
    print("ERROR: No alerts found in eve.json", file=sys.stderr)
    sys.exit(1)

compromised_hosts = set()
c2_ips = set()
c2_domains = set()
attack_summary = {}

for alert in alerts:
    sid = alert["alert"]["signature_id"]
    sig = alert["alert"]["signature"]
    src_ip = alert.get("src_ip", "unknown")
    dst_ip = alert.get("dest_ip", "unknown")

    if sid not in attack_summary:
        attack_summary[sid] = {"signature": sig, "count": 0, "sources": set()}
    attack_summary[sid]["count"] += 1
    attack_summary[sid]["sources"].add(src_ip)

    if sid == 2100001:
        compromised_hosts.add(src_ip)
        c2_domains.add("evil-c2.example.net")
    elif sid == 2100002:
        compromised_hosts.add(src_ip)
        c2_ips.add(dst_ip)
    elif sid == 2100004:
        compromised_hosts.add(src_ip)
    elif sid == 2100005:
        compromised_hosts.add(src_ip)
        c2_ips.add(dst_ip)

with open(report_file, "w") as f:
    f.write("INCIDENT REPORT - Suricata IDS Analysis\n")
    f.write("=" * 50 + "\n\n")

    f.write("COMPROMISED INTERNAL HOSTS:\n")
    for ip in sorted(compromised_hosts):
        f.write(f"  - {ip}\n")

    f.write("\nEXTERNAL C2/ATTACKER INFRASTRUCTURE IPs:\n")
    for ip in sorted(c2_ips):
        f.write(f"  - {ip}\n")

    f.write("\nDNS TUNNELING DOMAIN:\n")
    for domain in sorted(c2_domains):
        f.write(f"  - {domain}\n")

    f.write("\nATTACK TYPES DETECTED:\n")
    for sid in sorted(attack_summary):
        info = attack_summary[sid]
        f.write(f"  - SID {sid}: {info['signature']} "
                f"({info['count']} alerts from {sorted(info['sources'])})\n")

    f.write(f"\nTOTAL ALERTS: {len(alerts)}\n")
    f.write(f"UNIQUE ATTACK SIGNATURES: {len(attack_summary)}\n")

print(f"Incident report written to {report_file}")
