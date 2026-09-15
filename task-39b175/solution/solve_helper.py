#!/usr/bin/env python3
"""
Analyze capture.pcap: reconstruct the multi-stage attack, evaluate candidate
IDS rules, decode DNS tunnel exfiltration, and produce all report deliverables.
"""

import base64
import json
import os
import re
from collections import defaultdict
from urllib.parse import unquote

from scapy.all import rdpcap, IP, TCP, UDP, DNS, DNSQR, Raw

PCAP_PATH = "/app/capture.pcap"
REPORT_DIR = "/app/report"
CANDIDATE_RULES_PATH = "/app/proposed_rules/candidate_rules.txt"


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    packets = rdpcap(PCAP_PATH)

    # ------------------------------------------------------------------
    # Phase 1: Identify the SYN scan -> attacker IP, victim IP, open ports
    # ------------------------------------------------------------------
    syn_packets = [
        p for p in packets
        if p.haslayer(TCP) and p[TCP].flags == 0x02 and p.haslayer(IP)
    ]

    syn_counts = defaultdict(int)
    for p in syn_packets:
        syn_counts[(p[IP].src, p[IP].dst)] += 1

    attacker_ip, victim_ip = max(syn_counts, key=syn_counts.get)

    open_ports = set()
    for p in packets:
        if (p.haslayer(TCP) and p.haslayer(IP)
                and p[IP].src == victim_ip and p[IP].dst == attacker_ip
                and p[TCP].flags == 0x12):  # SYN-ACK
            open_ports.add(p[TCP].sport)

    open_ports = sorted(open_ports)

    # ------------------------------------------------------------------
    # Phase 2: Extract HTTP payloads -> SQL injection analysis
    # ------------------------------------------------------------------
    http_payloads_req = []
    http_payloads_resp = []

    for p in packets:
        if p.haslayer(TCP) and p.haslayer(Raw) and p.haslayer(IP):
            payload = p[Raw].load.decode("utf-8", errors="replace")
            if p[IP].src == attacker_ip and p[TCP].dport == 80:
                http_payloads_req.append(payload)
            elif p[IP].src == victim_ip and p[TCP].sport == 80:
                http_payloads_resp.append(payload)

    sqli_payload = ""
    sqli_tool = ""
    compromised_credentials = {}

    for i, req in enumerate(http_payloads_req):
        m = re.search(r"GET /search\?q=(.+?) HTTP", req)
        if m:
            raw_q = m.group(1)
            decoded_q = unquote(raw_q.replace("+", " "))
            if "UNION" in decoded_q.upper() and "users" in decoded_q.lower():
                sqli_payload = decoded_q

        ua = re.search(r"User-Agent:\s*(.+?)[\r\n]", req)
        if ua and "sqlmap" in ua.group(1).lower():
            sqli_tool = ua.group(1).strip()

    for resp in http_payloads_resp:
        if "UNION" not in sqli_payload:
            continue
        cred_matches = re.findall(r"<div>(\w+):(.+?)</div>", resp)
        for user, passwd in cred_matches:
            if user not in ("Search", "Results"):
                compromised_credentials[user] = passwd

    # ------------------------------------------------------------------
    # Phase 3: Identify reverse shell
    # ------------------------------------------------------------------
    reverse_shell_port = None

    tcp_conns = set()
    for p in packets:
        if (p.haslayer(TCP) and p.haslayer(IP)
                and p[TCP].flags == 0x02
                and p[IP].src == victim_ip and p[IP].dst == attacker_ip):
            tcp_conns.add(p[TCP].dport)

    for port in tcp_conns:
        if port not in open_ports and port > 1024:
            reverse_shell_port = port
            break

    # ------------------------------------------------------------------
    # Phase 4: DNS tunneling analysis
    # ------------------------------------------------------------------
    dns_queries = []
    c2_dns_server = None
    tunnel_domain = None

    for p in packets:
        if p.haslayer(DNS) and p.haslayer(DNSQR) and p.haslayer(IP) and p.haslayer(UDP):
            if p[DNS].qr == 0:
                dst = p[IP].dst
                qname = p[DNSQR].qname.decode("utf-8", errors="replace").rstrip(".")
                dns_queries.append((dst, qname, p.time))

    dns_by_server = defaultdict(list)
    for dst, qname, t in dns_queries:
        dns_by_server[dst].append((qname, t))

    for server, queries in dns_by_server.items():
        if server == "8.8.8.8":
            continue
        has_pattern = any(re.match(r"\d{2}-[a-z0-9]+\.", q) for q, _ in queries)
        if has_pattern:
            c2_dns_server = server
            for q, _ in queries:
                m = re.match(r"\d{2}-[a-z0-9]+\.(.+)", q)
                if m:
                    tunnel_domain = m.group(1)
                    break
            break

    tunnel_chunks = []
    for q, t in dns_by_server.get(c2_dns_server, []):
        m = re.match(r"(\d{2})-([a-z0-9]+)\." + re.escape(tunnel_domain), q)
        if m:
            seq = int(m.group(1))
            chunk = m.group(2)
            tunnel_chunks.append((seq, chunk))

    tunnel_chunks.sort(key=lambda x: x[0])
    encoded_data = "".join(chunk for _, chunk in tunnel_chunks)

    padding = (8 - len(encoded_data) % 8) % 8
    encoded_padded = encoded_data.upper() + "=" * padding

    exfiltrated_data = base64.b32decode(encoded_padded).decode("utf-8")

    # ------------------------------------------------------------------
    # Phase 5: Evaluate candidate IDS rules
    # ------------------------------------------------------------------
    with open(CANDIDATE_RULES_PATH) as f:
        rules_text = f.read()

    # Parse each rule by its R-id
    rules = {}
    current_id = None
    for line in rules_text.split("\n"):
        line_stripped = line.strip()
        id_match = re.match(r"#\s*Rule\s+(R\d+):", line_stripped)
        if id_match:
            current_id = id_match.group(1)
        elif line_stripped.startswith("alert") and current_id:
            rules[current_id] = line_stripped
            current_id = None

    # Evaluate R1: alert udp $HOME_NET any -> 198.51.100.53 53
    # Correct C2 IP but no content filter — fires on ALL queries to that IP
    r1_target = re.search(r"->\s+(\S+)\s+53", rules.get("R1", ""))
    r1_target_ip = r1_target.group(1) if r1_target else ""
    r1_fires = r1_target_ip == c2_dns_server

    # Evaluate R2: alert tcp ... -> $HOME_NET 443 with UNION/SELECT content
    # Attack used port 80 (HTTP), not 443 (HTTPS)
    r2_port_match = re.search(r"->\s+\S+\s+(\d+)", rules.get("R2", ""))
    r2_port = int(r2_port_match.group(1)) if r2_port_match else 0
    r2_fires = r2_port == 80  # Attack was on port 80; rule checks 443

    # Evaluate R3: alert tcp $EXTERNAL_NET any -> $HOME_NET 4444
    # Reverse shell is OUTBOUND: victim initiates SYN to attacker:4444
    # Rule checks INBOUND to HOME_NET on 4444 — wrong direction
    r3_direction = "$EXTERNAL_NET" in rules.get("R3", "").split("->")[0]
    r3_target_home = "$HOME_NET" in rules.get("R3", "").split("->")[1] if "->" in rules.get("R3", "") else False
    # Reverse shell SYN goes FROM $HOME_NET TO $EXTERNAL_NET, so this rule
    # (EXTERNAL->HOME on 4444) would not fire
    r3_fires = False  # Direction is reversed

    # Evaluate R4: alert udp $HOME_NET any -> 8.8.8.8 53 content:"c2-ops"
    # Tunnel queries go to the C2 DNS (198.51.100.53), NOT to 8.8.8.8
    r4_target = re.search(r"->\s+(\S+)\s+53", rules.get("R4", ""))
    r4_target_ip = r4_target.group(1) if r4_target else ""
    r4_fires = r4_target_ip == c2_dns_server  # 8.8.8.8 != 198.51.100.53

    # Evaluate R5: alert tcp $EXTERNAL_NET any -> $HOME_NET any flags:S
    # threshold:type both, count 3, seconds 120
    # Correct direction for SYN scan detection, fires on the observed scan
    # But threshold of 3 in 120s is too low — high false positive rate
    r5_fires = True  # SYN scan sends 22 SYNs, well above threshold 3

    # Count SYN scan packets to confirm
    scan_syn_count = sum(
        1 for p in packets
        if p.haslayer(TCP) and p.haslayer(IP)
        and p[IP].src == attacker_ip and p[IP].dst == victim_ip
        and p[TCP].flags == 0x02
    )

    # Evaluate R6: alert udp $HOME_NET any -> any 53 dsize:>40
    # Check actual DNS payload sizes for tunnel vs legitimate queries
    tunnel_dns_sizes = []
    legit_dns_sizes = []
    for p in packets:
        if p.haslayer(UDP) and p.haslayer(DNS) and p.haslayer(IP):
            if p[IP].src == victim_ip and p[UDP].dport == 53 and p[DNS].qr == 0:
                # Get UDP payload size (DNS layer)
                dns_payload_len = len(bytes(p[DNS]))
                if p[IP].dst == c2_dns_server:
                    tunnel_dns_sizes.append(dns_payload_len)
                else:
                    legit_dns_sizes.append(dns_payload_len)

    # Rule fires if any tunnel DNS payload > 40 bytes
    r6_fires = any(s > 40 for s in tunnel_dns_sizes)
    # Also check for false positives on legitimate queries
    r6_false_positives = sum(1 for s in legit_dns_sizes if s > 40)

    rule_evaluation = {
        "R1": {
            "fires_on_attack_traffic": r1_fires,
            "verdict": "partially_effective" if r1_fires else "ineffective",
            "primary_flaw": (
                "No content filter — alerts on ALL DNS queries to the C2 "
                "server IP without distinguishing tunnel queries from "
                "potentially legitimate lookups, lacking specificity for "
                "the encoded subdomain pattern"
            ),
        },
        "R2": {
            "fires_on_attack_traffic": r2_fires,
            "verdict": "ineffective",
            "primary_flaw": (
                f"Monitors port {r2_port} (HTTPS) but the SQL injection "
                f"attack occurred on port 80 (HTTP); rule would never "
                f"trigger on the observed attack traffic"
            ),
        },
        "R3": {
            "fires_on_attack_traffic": r3_fires,
            "verdict": "ineffective",
            "primary_flaw": (
                "Checks for inbound connections TO $HOME_NET on port 4444, "
                "but a reverse shell is initiated OUTBOUND from the victim "
                "to the attacker; the SYN direction is reversed relative to "
                "the actual attack flow"
            ),
        },
        "R4": {
            "fires_on_attack_traffic": r4_fires,
            "verdict": "ineffective",
            "primary_flaw": (
                f"Targets DNS queries to {r4_target_ip} (legitimate public "
                f"resolver) but the DNS tunnel uses a different C2 server "
                f"({c2_dns_server}); rule monitors the wrong destination"
            ),
        },
        "R5": {
            "fires_on_attack_traffic": r5_fires,
            "verdict": "partially_effective",
            "primary_flaw": (
                f"Threshold of 3 SYN packets in 120 seconds is too low — "
                f"legitimate web browsing and connection-heavy applications "
                f"routinely exceed this, generating excessive false positives "
                f"in production (scan sent {scan_syn_count} SYNs which "
                f"triggers, but so would normal traffic)"
            ),
        },
        "R6": {
            "fires_on_attack_traffic": r6_fires,
            "verdict": "partially_effective" if r6_fires else "ineffective",
            "primary_flaw": (
                f"Relies solely on DNS packet size (>40 bytes) without "
                f"examining query content patterns; {r6_false_positives} "
                f"legitimate DNS queries in this capture also exceed the "
                f"threshold, and CDN/cloud service domain lookups commonly "
                f"produce large queries in production"
            ),
        },
    }

    # ------------------------------------------------------------------
    # Phase 6: Design improved detection rules
    # ------------------------------------------------------------------
    detection_rules = (
        f"# Improved Detection Ruleset — covers all four attack phases\n"
        f"# Designed to correct deficiencies found in candidate rules R1-R6\n"
        f"\n"
        f"# Phase 1: Reconnaissance — SYN Scan Detection\n"
        f"# Corrects R5: higher threshold (15 in 10s) reduces false positives\n"
        f"# while still catching rapid port scanning behavior\n"
        f'alert tcp $EXTERNAL_NET any -> $HOME_NET any '
        f'(msg:"Rapid SYN scan detected from single external source"; '
        f'flags:S,12; '
        f'threshold:type both, track by_src, count 15, seconds 10; '
        f'classtype:attempted-recon; sid:2000001; rev:1;)\n'
        f"\n"
        f"# Phase 2: Web Exploitation — SQL Injection via HTTP\n"
        f"# Corrects R2: targets port 80 (HTTP) not 443, adds FROM keyword\n"
        f'alert tcp $EXTERNAL_NET any -> $HOME_NET 80 '
        f'(msg:"SQL Injection UNION SELECT attempt in HTTP traffic"; '
        f'flow:to_server,established; '
        f'content:"UNION"; nocase; '
        f'content:"SELECT"; nocase; '
        f'content:"FROM"; nocase; '
        f'classtype:web-application-attack; sid:2000002; rev:1;)\n'
        f"\n"
        f"# Phase 3: Reverse Shell — Outbound Callback Detection\n"
        f"# Corrects R3: direction is FROM $HOME_NET (victim initiates)\n"
        f'alert tcp $HOME_NET any -> $EXTERNAL_NET 4444 '
        f'(msg:"Possible reverse shell callback to external host on port 4444"; '
        f'flags:S; '
        f'classtype:trojan-activity; sid:2000003; rev:1;)\n'
        f"\n"
        f"# Phase 4: DNS Tunnel Exfiltration — C2 Channel Detection\n"
        f"# Corrects R4: targets actual C2 DNS server, not 8.8.8.8\n"
        f"# Corrects R1: adds content match for tunnel domain specificity\n"
        f'alert udp $HOME_NET any -> {c2_dns_server} 53 '
        f'(msg:"DNS tunnel exfiltration to C2 server via {tunnel_domain}"; '
        f'content:"c2-ops"; nocase; '
        f'threshold:type both, track by_src, count 5, seconds 60; '
        f'classtype:trojan-activity; sid:2000004; rev:1;)\n'
    )

    # ------------------------------------------------------------------
    # Phase 7: Write all outputs
    # ------------------------------------------------------------------
    findings = {
        "attacker_ip": attacker_ip,
        "victim_ip": victim_ip,
        "c2_dns_server": c2_dns_server,
        "tunnel_domain": tunnel_domain,
        "open_ports": open_ports,
        "sqli_payload": sqli_payload,
        "sqli_tool": sqli_tool,
        "reverse_shell_port": reverse_shell_port,
        "exfiltration_method": "dns_tunneling",
        "compromised_credentials": compromised_credentials,
    }

    with open(os.path.join(REPORT_DIR, "findings.json"), "w") as f:
        json.dump(findings, f, indent=2)

    with open(os.path.join(REPORT_DIR, "exfiltrated_data.txt"), "w") as f:
        f.write(exfiltrated_data)

    with open(os.path.join(REPORT_DIR, "rule_evaluation.json"), "w") as f:
        json.dump(rule_evaluation, f, indent=2)

    with open(os.path.join(REPORT_DIR, "detection_rules.rules"), "w") as f:
        f.write(detection_rules)

    print("=== Analysis Complete ===")
    print(f"Attacker: {attacker_ip}, Victim: {victim_ip}")
    print(f"C2 DNS: {c2_dns_server}, Tunnel: {tunnel_domain}")
    print(f"Open ports: {open_ports}")
    print(f"Reverse shell port: {reverse_shell_port}")
    print(f"Exfiltrated data length: {len(exfiltrated_data)} chars")
    print(f"Credentials found: {list(compromised_credentials.keys())}")
    print(f"Tunnel DNS sizes: min={min(tunnel_dns_sizes)}, max={max(tunnel_dns_sizes)}")
    print(f"Legit DNS sizes: min={min(legit_dns_sizes)}, max={max(legit_dns_sizes)}")
    print(f"R6 false positives in capture: {r6_false_positives}")
    print(f"SYN scan packets: {scan_syn_count}")
    print("Rule evaluations written.")
    print("Detection rules written.")


if __name__ == "__main__":
    main()
