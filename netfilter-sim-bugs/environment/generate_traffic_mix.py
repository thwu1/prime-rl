#!/usr/bin/env python3
"""
Generate deterministic DDoS traffic mix for mitigation design challenge.

Produces:
  - /app/traffic_mix.json  (flow metadata without payload data)
  - /app/captures/traffic.pcap  (full packet capture with payloads)

Traffic types:
  - 80 legitimate HTTPS clients (TCP SYN to port 443 from 10.0.0.0/8)
  - 20 legitimate SSH sessions (TCP SYN to port 22 from 172.20.0.0/16)
  - 30 legitimate DNS responses (UDP from known resolvers, src port 53, ~60B payload)
  - 400 SYN flood (TCP SYN to port 80 from 198.18.0.0/15)
  - 200 DNS amplification (UDP from port 53, scattered sources, ~512B payload)
  - 40 port scan (TCP SYN to random high ports from 192.168.100.0/24)
"""

import json
import random
import os

from scapy.all import Ether, IP, TCP, UDP, Raw, wrpcap, conf

conf.verb = 0

DST_IP = "192.0.2.1"


def generate():
    random.seed(42)
    entries = []

    # 80 legitimate HTTPS clients
    for _ in range(80):
        src = "10.{}.{}.{}".format(
            random.randint(0, 255), random.randint(0, 255),
            random.randint(1, 254))
        sport = random.randint(1024, 65535)
        json_pkt = {
            "src_ip": src, "dst_ip": DST_IP,
            "src_port": sport, "dst_port": 443,
            "protocol": "TCP", "tcp_flags": "S"
        }
        scapy_pkt = Ether() / IP(src=src, dst=DST_IP) / TCP(
            sport=sport, dport=443, flags="S")
        entries.append({"json": json_pkt, "scapy": scapy_pkt,
                        "type": "legit_https"})

    # 20 legitimate SSH sessions
    for _ in range(20):
        src = "172.20.{}.{}".format(
            random.randint(0, 255), random.randint(1, 254))
        sport = random.randint(1024, 65535)
        json_pkt = {
            "src_ip": src, "dst_ip": DST_IP,
            "src_port": sport, "dst_port": 22,
            "protocol": "TCP", "tcp_flags": "S"
        }
        scapy_pkt = Ether() / IP(src=src, dst=DST_IP) / TCP(
            sport=sport, dport=22, flags="S")
        entries.append({"json": json_pkt, "scapy": scapy_pkt,
                        "type": "legit_ssh"})

    # 30 legitimate DNS responses from known resolvers (small payloads)
    resolvers = ["8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1"]
    for _ in range(30):
        src = random.choice(resolvers)
        dport = random.randint(1024, 65535)
        json_pkt = {
            "src_ip": src, "dst_ip": DST_IP,
            "src_port": 53, "dst_port": dport,
            "protocol": "UDP"
        }
        scapy_pkt = Ether() / IP(src=src, dst=DST_IP) / UDP(
            sport=53, dport=dport) / Raw(load=b"\x00" * 60)
        entries.append({"json": json_pkt, "scapy": scapy_pkt,
                        "type": "legit_dns"})

    # 400 SYN flood attack
    for _ in range(400):
        src = "198.18.{}.{}".format(
            random.randint(0, 255), random.randint(1, 254))
        sport = random.randint(1024, 65535)
        json_pkt = {
            "src_ip": src, "dst_ip": DST_IP,
            "src_port": sport, "dst_port": 80,
            "protocol": "TCP", "tcp_flags": "S"
        }
        scapy_pkt = Ether() / IP(src=src, dst=DST_IP) / TCP(
            sport=sport, dport=80, flags="S")
        entries.append({"json": json_pkt, "scapy": scapy_pkt,
                        "type": "syn_flood"})

    # 200 DNS amplification attack (scattered sources, large payloads)
    for _ in range(200):
        src = "{}.{}.{}.{}".format(
            random.randint(44, 99), random.randint(0, 255),
            random.randint(0, 255), random.randint(1, 254))
        dport = random.randint(1024, 65535)
        json_pkt = {
            "src_ip": src, "dst_ip": DST_IP,
            "src_port": 53, "dst_port": dport,
            "protocol": "UDP"
        }
        scapy_pkt = Ether() / IP(src=src, dst=DST_IP) / UDP(
            sport=53, dport=dport) / Raw(load=b"\x00" * 512)
        entries.append({"json": json_pkt, "scapy": scapy_pkt,
                        "type": "dns_amp"})

    # 40 port scan
    for _ in range(40):
        src = "192.168.100.{}".format(random.randint(1, 254))
        sport = random.randint(1024, 65535)
        dport = random.randint(8000, 65535)
        json_pkt = {
            "src_ip": src, "dst_ip": DST_IP,
            "src_port": sport, "dst_port": dport,
            "protocol": "TCP", "tcp_flags": "S"
        }
        scapy_pkt = Ether() / IP(src=src, dst=DST_IP) / TCP(
            sport=sport, dport=dport, flags="S")
        entries.append({"json": json_pkt, "scapy": scapy_pkt,
                        "type": "port_scan"})

    # Shuffle deterministically
    random.seed(12345)
    random.shuffle(entries)

    # Write JSON (flow metadata only, no payload data)
    json_data = {
        "conntrack_max": 150,
        "packets": [e["json"] for e in entries]
    }
    os.makedirs("/app", exist_ok=True)
    with open("/app/traffic_mix.json", "w") as f:
        json.dump(json_data, f, indent=1)

    # Write pcap (full packets with payloads)
    os.makedirs("/app/captures", exist_ok=True)
    wrpcap("/app/captures/traffic.pcap", [e["scapy"] for e in entries])

    print("Generated {} packets".format(len(entries)))
    print("  -> /app/traffic_mix.json (flow metadata)")
    print("  -> /app/captures/traffic.pcap (full capture)")
    print("  Legitimate: 130 (80 HTTPS + 20 SSH + 30 DNS)")
    print("  Attack: 640 (400 SYN flood + 200 DNS amp + 40 port scan)")


if __name__ == "__main__":
    generate()
