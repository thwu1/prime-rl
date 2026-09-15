#!/usr/bin/env python3
"""Analyze /app/incident.pcap to perform full forensic investigation of a
multi-stage intrusion with multi-channel exfiltration and anti-forensics decoy.

Uses scapy for reliable PCAP parsing. Identifies SYN scan, command injection
exploit, DNS tunneling (real + decoy), and HTTP covert exfiltration. Produces
forensic report, decoded exfiltrated data, channel assessment, and IDS rules.
"""

import base64
import hashlib
import json
import sys
from collections import defaultdict
from urllib.parse import unquote_plus

from scapy.all import IP, TCP, UDP, DNS, DNSQR, Raw, rdpcap


def main():
    print("Loading PCAP...")
    packets = rdpcap("/app/incident.pcap")
    print(f"Loaded {len(packets)} packets")

    # ==================================================================
    # 1. SYN scan identification
    # ==================================================================
    pair_ports = defaultdict(set)
    for pkt in packets:
        if IP not in pkt or TCP not in pkt:
            continue
        tcp_flags = pkt[TCP].flags
        # SYN set, ACK not set
        if (int(tcp_flags) & 0x12) == 0x02:
            src = pkt[IP].src
            dst = pkt[IP].dst
            pair_ports[(src, dst)].add(pkt[TCP].dport)

    if not pair_ports:
        print("ERROR: No SYN-only packets found in PCAP", file=sys.stderr)
        sys.exit(1)

    scanner_pair = max(pair_ports.keys(), key=lambda k: len(pair_ports[k]))
    attacker_ip = scanner_pair[0]
    target_ip = scanner_pair[1]
    scanned_ports = sorted(pair_ports[scanner_pair])

    print(f"Attacker IP: {attacker_ip}")
    print(f"Target IP:   {target_ip}")
    print(f"Ports scanned: {len(scanned_ports)}")

    # ==================================================================
    # 2. Open ports (SYN-ACK from target back to attacker)
    # ==================================================================
    open_ports = set()
    for pkt in packets:
        if IP not in pkt or TCP not in pkt:
            continue
        tcp_flags = pkt[TCP].flags
        # SYN+ACK set
        if (int(tcp_flags) & 0x12) == 0x12:
            if pkt[IP].src == target_ip and pkt[IP].dst == attacker_ip:
                open_ports.add(pkt[TCP].sport)
    open_ports = sorted(open_ports)
    print(f"Open ports: {open_ports}")

    # ==================================================================
    # 3. HTTP exploit (POST to port 8080)
    # ==================================================================
    exploit_method = ""
    exploit_port = 0
    exploit_uri = ""

    for pkt in packets:
        if IP not in pkt or TCP not in pkt or Raw not in pkt:
            continue
        if pkt[IP].src != attacker_ip or pkt[TCP].dport != 8080:
            continue
        try:
            payload = pkt[Raw].load.decode("utf-8", errors="ignore")
            if "POST" not in payload or "/api/" not in payload:
                continue
            first_line = payload.split("\r\n")[0]
            parts = first_line.split(" ")
            if len(parts) >= 2:
                exploit_uri = parts[1]
            exploit_port = 8080
            if "\r\n\r\n" in payload:
                body = payload.split("\r\n\r\n", 1)[1]
                decoded_body = unquote_plus(body)
                if ";" in decoded_body or "|" in decoded_body:
                    exploit_method = "command_injection"
        except Exception:
            continue

    print(f"Exploit: {exploit_method} on port {exploit_port} at {exploit_uri}")

    # ==================================================================
    # 4. DNS tunneling channel discovery
    # ==================================================================
    base32_chars = set("abcdefghijklmnopqrstuvwxyz234567")
    dns_channels = defaultdict(list)

    for pkt in packets:
        if IP not in pkt or UDP not in pkt or DNS not in pkt:
            continue
        dns_layer = pkt[DNS]
        if dns_layer.qr != 0:
            continue
        if DNSQR not in pkt:
            continue
        qname_raw = pkt[DNSQR].qname
        if isinstance(qname_raw, bytes):
            qname = qname_raw.decode("utf-8", errors="ignore")
        else:
            qname = str(qname_raw)
        qname = qname.rstrip(".")
        parts = qname.split(".")
        if len(parts) < 3:
            continue

        subdomain = parts[0].lower()
        parent = ".".join(parts[1:]).lower()

        if len(subdomain) >= 20 and all(c in base32_chars for c in subdomain):
            dns_channels[parent].append(subdomain)

    print(f"DNS tunneling channels: {list(dns_channels.keys())}")
    for dom, subs in dns_channels.items():
        print(f"  {dom}: {len(subs)} queries")

    # ==================================================================
    # 5. Evaluate each DNS channel — real exfiltration vs decoy
    # ==================================================================
    channel_results = []
    primary_decoded = ""
    primary_domain = ""
    decoy_domain = ""

    for domain, subdomains in dns_channels.items():
        encoded_str = "".join(subdomains)
        pad = (8 - len(encoded_str) % 8) % 8
        padded = encoded_str.upper() + "=" * pad
        try:
            decoded_bytes = base64.b32decode(padded)
            text = decoded_bytes.decode("utf-8")  # strict: raises on invalid
            if any(kw in text for kw in ["DB_", "API_", "PASS", "KEY", "HOST"]):
                channel_results.append({
                    "id": "dns_primary",
                    "type": "dns_tunneling",
                    "domain_or_dest": domain,
                    "encoding": "base32",
                    "classification": "active_exfiltration",
                    "data_valid": True,
                })
                primary_decoded = text
                primary_domain = domain
            else:
                channel_results.append({
                    "id": "dns_decoy",
                    "type": "dns_tunneling",
                    "domain_or_dest": domain,
                    "encoding": "base32",
                    "classification": "decoy",
                    "data_valid": False,
                })
                decoy_domain = domain
        except Exception:
            channel_results.append({
                "id": "dns_decoy",
                "type": "dns_tunneling",
                "domain_or_dest": domain,
                "encoding": "base32",
                "classification": "decoy",
                "data_valid": False,
            })
            decoy_domain = domain

    # ==================================================================
    # 6. HTTP POST exfiltration (covert channel)
    # ==================================================================
    http_exfil_chunks = []
    http_exfil_dest = ""

    for pkt in packets:
        if IP not in pkt or TCP not in pkt or Raw not in pkt:
            continue
        if pkt[IP].src != target_ip:
            continue
        if pkt[IP].dst == attacker_ip:
            continue
        # Skip DNS server
        if pkt[IP].dst == "10.1.1.1":
            continue
        try:
            payload = pkt[Raw].load.decode("utf-8", errors="ignore")
            if "POST" not in payload or "payload" not in payload:
                continue
            if "\r\n\r\n" not in payload:
                continue
            body_str = payload.split("\r\n\r\n", 1)[1]
            body = json.loads(body_str)
            if "payload" in body and "part" in body:
                http_exfil_chunks.append(body)
                http_exfil_dest = pkt[IP].dst
        except Exception:
            continue

    print(f"HTTP exfil chunks: {len(http_exfil_chunks)}")
    print(f"HTTP exfil dest:   {http_exfil_dest}")

    # Sort by part number and decode
    secondary_decoded = ""
    if http_exfil_chunks:
        http_exfil_chunks.sort(key=lambda c: c["part"])
        hex_concat = "".join(c["payload"] for c in http_exfil_chunks)
        try:
            secondary_decoded = bytes.fromhex(hex_concat).decode("utf-8")
        except Exception as e:
            print(f"HTTP exfil decode error: {e}")

        channel_results.append({
            "id": "http_covert",
            "type": "http_post",
            "domain_or_dest": http_exfil_dest,
            "encoding": "hex",
            "classification": "active_exfiltration",
            "data_valid": True,
        })

    # ==================================================================
    # 7. Cross-validate the two real channels
    # ==================================================================
    data_hash = hashlib.sha256(primary_decoded.encode()).hexdigest()
    cross_match = (primary_decoded == secondary_decoded) and len(primary_decoded) > 0

    print(f"Primary decoded:   {repr(primary_decoded[:80])}...")
    if secondary_decoded:
        print(f"Secondary decoded: {repr(secondary_decoded[:80])}...")
    print(f"Cross-validation:  match={cross_match}")
    print(f"Data SHA-256:      {data_hash}")

    # ==================================================================
    # 8. Write forensic_report.json
    # ==================================================================
    report = {
        "attacker_ip": attacker_ip,
        "compromised_host": target_ip,
        "scan_type": "syn_scan",
        "ports_scanned": len(scanned_ports),
        "open_ports": open_ports,
        "exploit_method": exploit_method,
        "exploit_target_port": exploit_port,
        "exploit_uri": exploit_uri,
        "primary_c2_domain": primary_domain,
        "primary_exfil_encoding": "base32",
        "secondary_exfil_dest": http_exfil_dest,
        "secondary_exfil_encoding": "hex",
        "decoy_domain": decoy_domain,
        "decoy_reason": (
            "DNS queries to this domain contain base32-encoded subdomains "
            "that decode to random binary garbage, not valid UTF-8 text or "
            "recognizable credentials. The decoded data is nonsensical noise "
            "with no meaningful structure. This channel is an anti-forensics "
            "decoy designed to misdirect analysis and waste analyst time."
        ),
    }
    with open("/app/forensic_report.json", "w") as f:
        json.dump(report, f, indent=2)

    # ==================================================================
    # 9. Write decoded files
    # ==================================================================
    with open("/app/decoded_primary.txt", "w") as f:
        f.write(primary_decoded)
    with open("/app/decoded_secondary.txt", "w") as f:
        f.write(secondary_decoded)

    # ==================================================================
    # 10. Write channel_assessment.json
    # ==================================================================
    assessment = {
        "channels": channel_results,
        "cross_validation": {
            "primary_secondary_match": cross_match,
            "data_sha256": data_hash,
        },
    }
    with open("/app/channel_assessment.json", "w") as f:
        json.dump(assessment, f, indent=2)

    # ==================================================================
    # 11. Write detection.rules (Suricata/Snort format)
    # ==================================================================
    rules = []

    # Rule 1: DNS tunneling to the real C2 domain
    if primary_domain:
        rules.append(
            f'alert udp $HOME_NET any -> any 53 '
            f'(msg:"DNS Tunneling exfiltration to c2server.xyz"; '
            f'content:"c2server"; nocase; '
            f'content:"xyz"; nocase; distance:0; '
            f'threshold:type both, track by_src, count 3, seconds 60; '
            f'classtype:trojan-activity; '
            f'sid:1000001; rev:1;)'
        )

    # Rule 2: HTTP covert exfiltration via events endpoint
    if http_exfil_dest:
        rules.append(
            f'alert tcp $HOME_NET any -> {http_exfil_dest} any '
            f'(msg:"HTTP Covert Data Exfiltration via events endpoint"; '
            f'flow:to_server,established; '
            f'content:"POST"; depth:4; '
            f'content:"/api/v1/events"; '
            f'content:"payload"; '
            f'classtype:trojan-activity; '
            f'sid:1000002; rev:1;)'
        )
    else:
        rules.append(
            'alert tcp $HOME_NET any -> $EXTERNAL_NET any '
            '(msg:"HTTP Covert Data Exfiltration via events endpoint"; '
            'flow:to_server,established; '
            'content:"POST"; depth:4; '
            'content:"/api/v1/events"; '
            'content:"payload"; '
            'classtype:trojan-activity; '
            'sid:1000002; rev:1;)'
        )

    # Rule 3: Command injection via diagnostic endpoint
    rules.append(
        f'alert tcp $EXTERNAL_NET any -> $HOME_NET {exploit_port} '
        f'(msg:"Command Injection via {exploit_uri} endpoint"; '
        f'flow:to_server,established; '
        f'content:"POST"; depth:4; '
        f'content:"{exploit_uri}"; '
        f'content:"%3B"; '
        f'classtype:web-application-attack; '
        f'sid:1000003; rev:1;)'
    )

    with open("/app/detection.rules", "w") as f:
        for rule in rules:
            f.write(rule + "\n")

    print(f"Channels found: {len(channel_results)}")
    print("All outputs written successfully.")


if __name__ == "__main__":
    main()
