#!/usr/bin/env python3
"""
Forensic analysis of a multi-stage intrusion PCAP, plus detection rule
generation.

Extracts: HTTP dropper payload -> C2 config -> decrypts C2 traffic ->
          reconstructs DNS exfiltration -> writes Suricata detection rules.

"""

import json
import struct
import base64
import re
from scapy.all import rdpcap, TCP, UDP, DNS, DNSQR, Raw, IP, conf

conf.verb = 0


def xor_single_byte(data, key_byte):
    return bytes([b ^ key_byte for b in data])


def xor_with_key(data, key):
    if isinstance(key, str):
        key = key.encode()
    return bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])


def extract_tcp_streams(packets):
    """Group packets into TCP streams keyed by (src, dst, sport, dport)."""
    streams = {}
    for pkt in packets:
        if pkt.haslayer(TCP) and pkt.haslayer(Raw):
            ip = pkt[IP]
            tcp = pkt[TCP]
            fwd = (ip.src, ip.dst, tcp.sport, tcp.dport)
            rev = (ip.dst, ip.src, tcp.dport, tcp.sport)
            key = tuple(sorted([fwd, rev]))
            if key not in streams:
                streams[key] = []
            streams[key].append({
                "src": ip.src,
                "dst": ip.dst,
                "sport": tcp.sport,
                "dport": tcp.dport,
                "data": bytes(pkt[Raw].load),
                "time": float(pkt.time),
            })
    return streams


def find_http_response_body(streams):
    """Find the HTTP response from the staging server and extract the body."""
    for key, pkts in streams.items():
        for pkt in pkts:
            if pkt["dport"] == 80 or pkt["sport"] == 80:
                data = pkt["data"]
                if data.startswith(b"HTTP/1.1 200"):
                    sep = data.find(b"\r\n\r\n")
                    if sep > 0:
                        return data[sep + 4:]
    return None


def decode_dropper_payload(js_body):
    """Extract the base64 string from fake JS, brute-force XOR key, return config."""
    text = js_body.decode("utf-8", errors="replace")

    match = re.search(r'var\s+_0x[0-9a-f]+\s*=\s*"([A-Za-z0-9+/=]+)"', text)
    if not match:
        raise ValueError("Could not find encoded payload in JavaScript")

    b64_str = match.group(1)
    raw = base64.b64decode(b64_str)

    for key_byte in range(256):
        candidate = xor_single_byte(raw, key_byte)
        if candidate[0:1] == b"{":
            try:
                config = json.loads(candidate)
                if "c2" in config and "key" in config:
                    return config
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

    raise ValueError("Could not decode dropper payload")


def parse_c2_messages(streams, c2_ip, c2_port, xor_key):
    """Parse all C2 protocol messages from TCP streams to the C2 server."""
    messages = []

    for key, pkts in streams.items():
        involves_c2 = False
        for pkt in pkts:
            if ((pkt["dst"] == c2_ip and pkt["dport"] == c2_port) or
                    (pkt["src"] == c2_ip and pkt["sport"] == c2_port)):
                involves_c2 = True
                break

        if not involves_c2:
            continue

        for pkt in pkts:
            data = pkt["data"]
            offset = 0
            while offset + 6 <= len(data):
                if data[offset:offset + 2] != b"\xDE\xAD":
                    offset += 1
                    continue

                msg_type = struct.unpack(">H", data[offset + 2:offset + 4])[0]
                payload_len = struct.unpack(">H", data[offset + 4:offset + 6])[0]

                if offset + 6 + payload_len > len(data):
                    break

                encrypted = data[offset + 6:offset + 6 + payload_len]
                decrypted = xor_with_key(encrypted, xor_key)

                try:
                    payload = json.loads(decrypted)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    offset += 1
                    continue

                direction = "client" if pkt["dst"] == c2_ip else "server"
                messages.append({
                    "type": msg_type,
                    "direction": direction,
                    "payload": payload,
                    "time": pkt["time"],
                })
                offset += 6 + payload_len

    messages.sort(key=lambda m: m["time"])
    return messages


def reconstruct_dns_exfil(packets):
    """Find DNS exfiltration queries and reconstruct the tunneled data."""
    txt_queries = []
    for pkt in packets:
        if pkt.haslayer(DNS) and pkt.haslayer(DNSQR):
            dns = pkt[DNS]
            if dns.qr == 0:
                qr = dns.qd
                if qr and qr.qtype == 16:
                    qname = qr.qname.decode() if isinstance(qr.qname, bytes) else qr.qname
                    qname = qname.rstrip(".")
                    txt_queries.append(qname)

    domain_chunks = {}
    for qname in txt_queries:
        parts = qname.split(".")
        if len(parts) >= 4:
            chunk = parts[0]
            try:
                seq = int(parts[1])
            except ValueError:
                continue
            base_domain = ".".join(parts[2:])
            if base_domain not in domain_chunks:
                domain_chunks[base_domain] = {}
            domain_chunks[base_domain][seq] = chunk

    exfil_domain = max(domain_chunks, key=lambda d: len(domain_chunks[d]))
    chunks = domain_chunks[exfil_domain]

    ordered = [chunks[i] for i in sorted(chunks.keys())]
    encoded = "".join(ordered)

    padding = (8 - len(encoded) % 8) % 8
    encoded_padded = encoded.upper() + "=" * padding
    plaintext = base64.b32decode(encoded_padded).decode()

    return plaintext, exfil_domain


def generate_detection_rules(c2_ip, c2_port, exfil_domain):
    """Design Suricata IDS rules targeting each attack stage."""
    rules = []

    # Rule 1: C2 protocol beacon detection via magic byte header
    rules.append(
        f'alert tcp $HOME_NET any -> {c2_ip} {c2_port} '
        f'(msg:"Custom C2 Protocol - DEAD Magic Header Beacon"; '
        f'content:"|DE AD|"; offset:0; depth:2; '
        f'sid:1000001; rev:1;)'
    )

    # Rule 2: DNS-based data exfiltration to attacker domain
    rules.append(
        f'alert dns $HOME_NET any -> any any '
        f'(msg:"DNS Data Exfiltration via {exfil_domain}"; '
        f'dns.query; content:"{exfil_domain}"; nocase; '
        f'sid:1000002; rev:1;)'
    )

    # Rule 3: Obfuscated JavaScript dropper delivery
    rules.append(
        f'alert http $HOME_NET any -> $EXTERNAL_NET any '
        f'(msg:"Obfuscated JavaScript Dropper Delivery"; '
        f'content:"_0x"; content:"atob"; '
        f'sid:1000003; rev:1;)'
    )

    return rules


def main():
    print("Reading PCAP...")
    packets = rdpcap("/app/capture.pcap")
    print(f"Loaded {len(packets)} packets")

    # ── Identify victim IP (most active internal IP) ──
    ip_counts = {}
    for pkt in packets:
        if pkt.haslayer(IP):
            src = pkt[IP].src
            if src.startswith("10."):
                ip_counts[src] = ip_counts.get(src, 0) + 1
    victim_ip = max(ip_counts, key=ip_counts.get)
    print(f"Victim IP: {victim_ip}")

    # ── Extract TCP streams ──
    streams = extract_tcp_streams(packets)
    print(f"Found {len(streams)} TCP streams")

    # ── Stage 1: Decode HTTP dropper ──
    print("\n=== Stage 1: HTTP Dropper ===")
    http_body = find_http_response_body(streams)
    if http_body is None:
        raise RuntimeError("Could not find HTTP response")

    config = decode_dropper_payload(http_body)
    print(f"Decoded config: {json.dumps(config, indent=2)}")

    c2_ip = config["c2"]
    c2_port = config["port"]
    xor_key = config["key"]

    # ── Stage 2: Decrypt C2 messages ──
    print("\n=== Stage 2: C2 Communications ===")
    messages = parse_c2_messages(streams, c2_ip, c2_port, xor_key)
    print(f"Decoded {len(messages)} C2 messages")

    hostname = None
    username = None
    commands = []
    credentials = {}

    for msg in messages:
        payload = msg["payload"]

        if msg["type"] == 0x0001:  # beacon
            if "hostname" in payload:
                hostname = payload["hostname"]
            if "user" in payload:
                username = payload["user"]

        elif msg["type"] == 0x0002:  # command from server
            if "cmd" in payload:
                commands.append(payload["cmd"])

        elif msg["type"] == 0x0003:  # response
            result = payload.get("result")
            if isinstance(result, dict) and all(
                isinstance(v, str) for v in result.values()
            ):
                credentials.update(result)

    print(f"Hostname: {hostname}")
    print(f"Username: {username}")
    print(f"Commands: {commands}")
    print(f"Credentials: {credentials}")

    # ── Stage 3: DNS exfiltration ──
    print("\n=== Stage 3: DNS Exfiltration ===")
    exfil_plaintext, exfil_domain = reconstruct_dns_exfil(packets)
    print(f"Exfil domain: {exfil_domain}")
    print(f"Exfiltrated data: {exfil_plaintext}")

    # ── Write forensic findings ──
    findings = {
        "victim_ip": victim_ip,
        "c2_server_ip": c2_ip,
        "c2_port": c2_port,
        "encryption_key": xor_key,
        "victim_hostname": hostname,
        "victim_username": username,
        "c2_commands": commands,
        "compromised_credentials": credentials,
        "exfiltrated_data": exfil_plaintext,
        "exfil_domain": exfil_domain,
    }

    with open("/app/findings.json", "w") as f:
        json.dump(findings, f, indent=2)
    print("\nFindings written to /app/findings.json")

    # ── Generate detection rules ──
    print("\n=== Detection Engineering ===")
    rules = generate_detection_rules(c2_ip, c2_port, exfil_domain)
    with open("/app/detection.rules", "w") as f:
        f.write("\n".join(rules) + "\n")
    print(f"Wrote {len(rules)} Suricata rules to /app/detection.rules")


if __name__ == "__main__":
    main()
