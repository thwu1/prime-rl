#!/usr/bin/env python3
"""
Generate deterministic mixed traffic capture for DDoS analysis task.

Traffic types:
  - Legitimate internal web (TCP SYN from 10.0.0.0/8 to port 80/443)
  - Legitimate external HTTPS (TCP SYN from 203.0.113.0/24 to port 443)
  - SYN flood attack (TCP SYN from 198.18.0.0/15 to port 80)
  - Legitimate DNS queries (UDP from 10.0.0.0/8 to port 53, small payload)
  - Legitimate DNS responses (UDP from known resolvers, src port 53, small payload)
  - DNS amplification attack (UDP from scattered IPs, src port 53, large payload)
"""

import random
import os
from scapy.all import Ether, IP, TCP, UDP, Raw, wrpcap, conf

conf.verb = 0

DST_IP = "192.0.2.1"
ETH_SRC = "00:00:00:00:00:01"
ETH_DST = "00:00:00:00:00:02"


def generate():
    random.seed(42)
    packets = []

    # 1. Legitimate internal web traffic (200 packets)
    for _ in range(200):
        src = "10.{}.{}.{}".format(
            random.randint(0, 255), random.randint(0, 255), random.randint(1, 254))
        sport = random.randint(1024, 65535)
        dport = random.choice([80, 443])
        pkt = (Ether(src=ETH_SRC, dst=ETH_DST) /
               IP(src=src, dst=DST_IP) /
               TCP(sport=sport, dport=dport, flags="S"))
        packets.append(pkt)

    # 2. Legitimate external HTTPS (200 packets)
    for _ in range(200):
        src = "203.0.113.{}".format(random.randint(1, 254))
        sport = random.randint(1024, 65535)
        pkt = (Ether(src=ETH_SRC, dst=ETH_DST) /
               IP(src=src, dst=DST_IP) /
               TCP(sport=sport, dport=443, flags="S"))
        packets.append(pkt)

    # 3. SYN flood attack (5000 packets)
    for _ in range(5000):
        src = "198.18.{}.{}".format(
            random.randint(0, 255), random.randint(1, 254))
        sport = random.randint(1024, 65535)
        pkt = (Ether(src=ETH_SRC, dst=ETH_DST) /
               IP(src=src, dst=DST_IP) /
               TCP(sport=sport, dport=80, flags="S"))
        packets.append(pkt)

    # 4. Legitimate DNS queries (150 packets)
    for _ in range(150):
        src = "10.{}.{}.{}".format(
            random.randint(0, 255), random.randint(0, 255), random.randint(1, 254))
        sport = random.randint(1024, 65535)
        payload_len = random.randint(40, 90)
        pkt = (Ether(src=ETH_SRC, dst=ETH_DST) /
               IP(src=src, dst=DST_IP) /
               UDP(sport=sport, dport=53) /
               Raw(b"\x00" * payload_len))
        packets.append(pkt)

    # 5. Legitimate DNS responses (100 packets)
    resolvers = ["8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1"]
    for _ in range(100):
        src = random.choice(resolvers)
        dport = random.randint(1024, 65535)
        payload_len = random.randint(40, 90)
        pkt = (Ether(src=ETH_SRC, dst=ETH_DST) /
               IP(src=src, dst=DST_IP) /
               UDP(sport=53, dport=dport) /
               Raw(b"\x00" * payload_len))
        packets.append(pkt)

    # 6. DNS amplification attack (2500 packets)
    # Scattered sources across many /8 blocks (not blockable by subnet)
    for _ in range(2500):
        src = "{}.{}.{}.{}".format(
            random.randint(44, 99),
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(1, 254))
        dport = random.randint(1024, 65535)
        payload_len = random.randint(300, 512)
        pkt = (Ether(src=ETH_SRC, dst=ETH_DST) /
               IP(src=src, dst=DST_IP) /
               UDP(sport=53, dport=dport) /
               Raw(b"\x00" * payload_len))
        packets.append(pkt)

    # Shuffle with separate seed for consistent ordering
    random.seed(12345)
    random.shuffle(packets)

    os.makedirs("/app/data", exist_ok=True)
    wrpcap("/app/data/traffic.pcap", packets)
    print("Generated {} packets -> /app/data/traffic.pcap".format(len(packets)))
    print("  Legitimate: 650 (200 web internal + 200 web external + "
          "150 DNS queries + 100 DNS responses)")
    print("  Attack: 7500 (5000 SYN flood + 2500 DNS amplification)")


if __name__ == "__main__":
    generate()
