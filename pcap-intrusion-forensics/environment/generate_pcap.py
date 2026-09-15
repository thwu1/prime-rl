#!/usr/bin/env python3
"""
Generate a forensic PCAP file containing a multi-stage network intrusion.

Stages:
  1. DNS + HTTP: Dropper download with layered encoding (XOR + base64)
  2. C2 beaconing: Custom binary protocol over TCP with encrypted JSON payloads
  3. DNS exfiltration: Base32-encoded data tunneled via subdomain labels
  4. Cleanup: Final C2 handoff

"""

import json
import base64
import struct
import random
from scapy.all import IP, TCP, UDP, DNS, DNSQR, DNSRR, ICMP, Raw, wrpcap, conf

conf.verb = 0
random.seed(0xDEADBEEF)

# ── Network addresses ──
VICTIM_IP = "10.13.37.105"
GW_IP = "10.13.37.1"
STAGING_IP = "185.220.101.34"
C2_IP = "91.234.99.71"

# ── Attack parameters ──
C2_PORT = 8443
XOR_KEY = b"5a7b3e2f"
PAYLOAD_XOR_BYTE = 0x42
BEACON_INTERVAL = 30
AGENT_ID = "agent-7f3a"

# ── C2 protocol message types ──
MSG_BEACON  = 0x0001
MSG_COMMAND = 0x0002
MSG_RESPONSE = 0x0003

BASE_TIME = 1709251200.0  # 2024-03-01 00:00:00 UTC


def xor_single_byte(data, key_byte):
    """XOR every byte of data with a single key byte."""
    return bytes([b ^ key_byte for b in data])


def xor_with_key(data, key):
    """XOR data with a repeating multi-byte key."""
    if isinstance(data, str):
        data = data.encode()
    if isinstance(key, str):
        key = key.encode()
    return bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])


def build_c2_message(msg_type, payload_dict):
    """
    Build a C2 protocol message:
      [2B magic 0xDEAD][2B type BE][2B length BE][encrypted payload]
    """
    payload = json.dumps(payload_dict, separators=(",", ":")).encode()
    encrypted = xor_with_key(payload, XOR_KEY)
    header = b"\xDE\xAD" + struct.pack(">HH", msg_type, len(encrypted))
    return header + encrypted


# ── TCP stream builder ──────────────────────────────────────────────
class TCPStream:
    """Construct a realistic TCP conversation (handshake, data, teardown)."""

    def __init__(self, src_ip, dst_ip, sport, dport):
        self.src_ip, self.dst_ip = src_ip, dst_ip
        self.sport, self.dport = sport, dport
        self.cseq = random.randint(100000, 999999)
        self.sseq = random.randint(100000, 999999)
        self.packets = []
        self.t = 0.0

    def set_time(self, t):
        self.t = t

    def _append(self, pkt):
        self.packets.append((pkt, self.t))

    def handshake(self):
        self._append(IP(src=self.src_ip, dst=self.dst_ip) /
                     TCP(sport=self.sport, dport=self.dport,
                         flags="S", seq=self.cseq))
        self.t += 0.05
        self._append(IP(src=self.dst_ip, dst=self.src_ip) /
                     TCP(sport=self.dport, dport=self.sport,
                         flags="SA", seq=self.sseq, ack=self.cseq + 1))
        self.t += 0.03
        self.cseq += 1
        self.sseq += 1
        self._append(IP(src=self.src_ip, dst=self.dst_ip) /
                     TCP(sport=self.sport, dport=self.dport,
                         flags="A", seq=self.cseq, ack=self.sseq))
        self.t += 0.01

    def client_send(self, data):
        if isinstance(data, str):
            data = data.encode()
        self._append(IP(src=self.src_ip, dst=self.dst_ip) /
                     TCP(sport=self.sport, dport=self.dport,
                         flags="PA", seq=self.cseq, ack=self.sseq) /
                     Raw(load=data))
        self.cseq += len(data)
        self.t += 0.02
        self._append(IP(src=self.dst_ip, dst=self.src_ip) /
                     TCP(sport=self.dport, dport=self.sport,
                         flags="A", seq=self.sseq, ack=self.cseq))
        self.t += 0.01

    def server_send(self, data):
        if isinstance(data, str):
            data = data.encode()
        self._append(IP(src=self.dst_ip, dst=self.src_ip) /
                     TCP(sport=self.dport, dport=self.sport,
                         flags="PA", seq=self.sseq, ack=self.cseq) /
                     Raw(load=data))
        self.sseq += len(data)
        self.t += 0.02
        self._append(IP(src=self.src_ip, dst=self.dst_ip) /
                     TCP(sport=self.sport, dport=self.dport,
                         flags="A", seq=self.cseq, ack=self.sseq))
        self.t += 0.01

    def close(self):
        self._append(IP(src=self.src_ip, dst=self.dst_ip) /
                     TCP(sport=self.sport, dport=self.dport,
                         flags="FA", seq=self.cseq, ack=self.sseq))
        self.cseq += 1
        self.t += 0.03
        self._append(IP(src=self.dst_ip, dst=self.src_ip) /
                     TCP(sport=self.dport, dport=self.sport,
                         flags="FA", seq=self.sseq, ack=self.cseq))
        self.sseq += 1
        self.t += 0.03
        self._append(IP(src=self.src_ip, dst=self.dst_ip) /
                     TCP(sport=self.sport, dport=self.dport,
                         flags="A", seq=self.cseq, ack=self.sseq))
        self.t += 0.01


# ── DNS helpers ─────────────────────────────────────────────────────
def dns_query(src, dst, domain, qtype="A", t=0):
    pkt = (IP(src=src, dst=dst) /
           UDP(sport=random.randint(49152, 65535), dport=53) /
           DNS(id=random.randint(1, 65535), rd=1,
               qd=DNSQR(qname=domain, qtype=qtype)))
    return (pkt, t)


def dns_a_response(qpkt, rdata, t=0):
    ip = qpkt[IP]
    udp = qpkt[UDP]
    d = qpkt[DNS]
    resp = (IP(src=ip.dst, dst=ip.src) /
            UDP(sport=53, dport=udp.sport) /
            DNS(id=d.id, qr=1, rd=1, ra=1, qd=d.qd,
                an=DNSRR(rrname=d.qd.qname, type="A",
                         rdata=rdata, ttl=300)))
    return (resp, t)


def dns_txt_response(qpkt, txt, t=0):
    ip = qpkt[IP]
    udp = qpkt[UDP]
    d = qpkt[DNS]
    resp = (IP(src=ip.dst, dst=ip.src) /
            UDP(sport=53, dport=udp.sport) /
            DNS(id=d.id, qr=1, rd=1, ra=1, qd=d.qd,
                an=DNSRR(rrname=d.qd.qname, type="TXT",
                         rdata=txt, ttl=60)))
    return (resp, t)


# ════════════════════════════════════════════════════════════════════
def generate():
    pkts = []
    t = BASE_TIME

    # ── Stage 0: legitimate-looking noise ───────────────────────────
    noise = [
        ("www.google.com", "142.250.80.4"),
        ("fonts.googleapis.com", "142.250.80.10"),
        ("cdn.jsdelivr.net", "104.16.85.20"),
        ("api.github.com", "140.82.121.6"),
        ("update.microsoft.com", "13.107.4.52"),
    ]
    for dom, ip in noise:
        q = dns_query(VICTIM_IP, GW_IP, dom, t=t)
        pkts.append(q)
        t += 0.05
        pkts.append(dns_a_response(q[0], ip, t=t))
        t += random.uniform(0.5, 2.0)

    # ICMP noise
    for _ in range(3):
        pkts.append((IP(src=VICTIM_IP, dst="8.8.8.8") /
                      ICMP(type=8) / Raw(load=b"\x00" * 32), t))
        t += 0.1
        pkts.append((IP(src="8.8.8.8", dst=VICTIM_IP) /
                      ICMP(type=0) / Raw(load=b"\x00" * 32), t))
        t += random.uniform(1.0, 3.0)

    # Noise HTTPS handshake (partial TLS)
    noise_tls = TCPStream(VICTIM_IP, "142.250.80.4", 49722, 443)
    noise_tls.set_time(t)
    noise_tls.handshake()
    fake_hello = (b"\x16\x03\x01\x00\xf1\x01\x00\x00\xed\x03\x03" +
                  bytes([random.randint(0, 255) for _ in range(80)]))
    noise_tls.client_send(fake_hello)
    noise_tls.close()
    pkts.extend(noise_tls.packets)
    t = noise_tls.t + 2.0

    # ── Stage 1: DNS + HTTP dropper ─────────────────────────────────
    staging_domain = "dl-update.microsoftservice.center"
    q = dns_query(VICTIM_IP, GW_IP, staging_domain, t=t)
    pkts.append(q)
    t += 0.05
    pkts.append(dns_a_response(q[0], STAGING_IP, t=t))
    t += 0.2

    # Build encoded payload
    config = {
        "c2": C2_IP,
        "port": C2_PORT,
        "key": XOR_KEY.decode(),
        "interval": BEACON_INTERVAL,
        "id": AGENT_ID,
    }
    config_json = json.dumps(config, separators=(",", ":"))
    xored_config = xor_single_byte(config_json.encode(), PAYLOAD_XOR_BYTE)
    b64_payload = base64.b64encode(xored_config).decode()

    # Wrap in fake JavaScript
    js_body = (
        '/*! jQuery v3.6.0 | (c) OpenJS Foundation | jquery.org/license */\n'
        '!function(e,t){"use strict";'
        'var _0x4f8a="' + b64_payload + '";'
        'var _0x2c1d=function(e){return window.atob(e)};'
        'var _0x7e3b=function(s,k){for(var r="",i=0;i<s.length;i++)'
        '{r+=String.fromCharCode(s.charCodeAt(i)^k)}return r};'
        'if(typeof module==="object"&&typeof module.exports==="object")'
        '{module.exports=e.document?t(e,!0):function(e){return t(e)}}'
        'else{t(e)}}(typeof window!=="undefined"?window:this,'
        'function(e,t){var n=[];var r=Object.getPrototypeOf;'
        'var i=n.slice;var o=n.flat?function(e){return n.flat.call(e)}'
        ':function(e){return n.concat.apply([],e)};return jQuery});'
    )

    http_req = (
        "GET /assets/jquery.min.js HTTP/1.1\r\n"
        "Host: " + staging_domain + "\r\n"
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0\r\n"
        "Accept: */*\r\n"
        "Accept-Encoding: identity\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    http_resp = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/javascript; charset=utf-8\r\n"
        "Content-Length: " + str(len(js_body)) + "\r\n"
        "Server: nginx/1.24.0\r\n"
        "X-Request-ID: a3f8c291-7e4b-4d12-b5a6-9c8d7e6f5a4b\r\n"
        "Cache-Control: public, max-age=31536000\r\n"
        "\r\n" + js_body
    )

    http = TCPStream(VICTIM_IP, STAGING_IP, 49721, 80)
    http.set_time(t)
    http.handshake()
    http.client_send(http_req)
    http.server_send(http_resp)
    http.close()
    pkts.extend(http.packets)
    t = http.t + 3.0

    # More noise DNS between stages
    extra_noise = [
        ("analytics.google.com", "142.250.80.46"),
        ("stats.wp.com", "192.0.78.13"),
    ]
    for dom, ip in extra_noise:
        q = dns_query(VICTIM_IP, GW_IP, dom, t=t)
        pkts.append(q)
        t += 0.05
        pkts.append(dns_a_response(q[0], ip, t=t))
        t += random.uniform(0.5, 1.5)

    # ── Stage 2: C2 beaconing ───────────────────────────────────────
    c2_domain = "cdn-static.analyticscloud.io"
    q = dns_query(VICTIM_IP, GW_IP, c2_domain, t=t)
    pkts.append(q)
    t += 0.05
    pkts.append(dns_a_response(q[0], C2_IP, t=t))
    t += 0.5

    c2 = TCPStream(VICTIM_IP, C2_IP, 49830, C2_PORT)
    c2.set_time(t)
    c2.handshake()

    # Beacon 1
    c2.client_send(build_c2_message(MSG_BEACON, {
        "hostname": "WS-PC0117",
        "user": "j.morrison",
        "os": "Windows 10 Pro 22H2",
        "pid": 4832,
    }))
    c2.t += BEACON_INTERVAL

    # Command 1: enum_shares
    c2.server_send(build_c2_message(MSG_COMMAND, {
        "cmd": "enum_shares", "id": 1,
    }))
    c2.t += 2.0

    # Response 1
    c2.client_send(build_c2_message(MSG_RESPONSE, {
        "id": 1,
        "result": [
            "\\\\filesvr\\finance$",
            "\\\\filesvr\\hr$",
            "\\\\filesvr\\engineering",
        ],
    }))
    c2.t += BEACON_INTERVAL

    # Beacon 2
    c2.client_send(build_c2_message(MSG_BEACON, {
        "hostname": "WS-PC0117",
        "user": "j.morrison",
        "os": "Windows 10 Pro 22H2",
        "pid": 4832,
    }))
    c2.t += 3.0

    # Command 2: dump_creds
    c2.server_send(build_c2_message(MSG_COMMAND, {
        "cmd": "dump_creds", "id": 2,
    }))
    c2.t += 5.0

    # Response 2
    c2.client_send(build_c2_message(MSG_RESPONSE, {
        "id": 2,
        "result": {
            "admin": "P@ssw0rd!2024",
            "svc_backup": "Backup#Str0ng",
        },
    }))
    c2.t += BEACON_INTERVAL

    # Beacon 3
    c2.client_send(build_c2_message(MSG_BEACON, {
        "hostname": "WS-PC0117",
        "user": "j.morrison",
        "os": "Windows 10 Pro 22H2",
        "pid": 4832,
    }))
    c2.t += 3.0

    # Command 3: exfil
    c2.server_send(build_c2_message(MSG_COMMAND, {
        "cmd": "exfil",
        "target": "/data/quarterly-report.xlsx",
        "id": 3,
    }))
    c2.t += 1.0

    # Response 3
    c2.client_send(build_c2_message(MSG_RESPONSE, {
        "id": 3, "status": "exfil_started",
    }))

    c2.close()
    pkts.extend(c2.packets)
    t = c2.t + 2.0

    # ── Stage 3: DNS exfiltration ───────────────────────────────────
    exfil_data = (
        "CONFIDENTIAL: Q3 Revenue Projection - $4.7M shortfall. "
        "Board meeting moved to Dec 15. "
        "Contact: CFO j.morrison@corp.local"
    )
    encoded_exfil = base64.b32encode(exfil_data.encode()).decode()
    encoded_exfil = encoded_exfil.rstrip("=").lower()

    chunk_size = 50
    chunks = [encoded_exfil[i:i + chunk_size]
              for i in range(0, len(encoded_exfil), chunk_size)]

    exfil_domain = "telemetry-cdn.net"
    intersperse_domains = [
        "analytics.google.com", "stats.wp.com",
        "pixel.facebook.net", "cdn.segment.io",
    ]

    for seq, chunk in enumerate(chunks):
        subdomain = "{}.{}.{}".format(chunk, seq, exfil_domain)
        q = dns_query(VICTIM_IP, GW_IP, subdomain, qtype="TXT", t=t)
        pkts.append(q)
        t += 0.05
        pkts.append(dns_txt_response(q[0], "v=1", t=t))
        t += random.uniform(0.3, 0.8)

        # Intersperse noise
        if seq % 2 == 0:
            nd = random.choice(intersperse_domains)
            nq = dns_query(VICTIM_IP, GW_IP, nd, t=t)
            pkts.append(nq)
            t += 0.05
            pkts.append(dns_a_response(
                nq[0],
                "10.{}.{}.{}".format(
                    random.randint(0, 255),
                    random.randint(0, 255),
                    random.randint(0, 255)),
                t=t))
            t += random.uniform(0.2, 0.5)

    # ── Stage 4: Cleanup ────────────────────────────────────────────
    t += 5.0
    c2b = TCPStream(VICTIM_IP, C2_IP, 49831, C2_PORT)
    c2b.set_time(t)
    c2b.handshake()

    c2b.client_send(build_c2_message(MSG_BEACON, {
        "hostname": "WS-PC0117",
        "user": "j.morrison",
        "os": "Windows 10 Pro 22H2",
        "pid": 4832,
        "status": "exfil_complete",
    }))
    c2b.t += 1.0

    c2b.server_send(build_c2_message(MSG_COMMAND, {
        "cmd": "cleanup", "id": 4,
    }))
    c2b.t += 2.0

    c2b.client_send(build_c2_message(MSG_RESPONSE, {
        "id": 4, "status": "cleaned",
    }))
    c2b.close()
    pkts.extend(c2b.packets)

    # ── Write PCAP ──────────────────────────────────────────────────
    pkts.sort(key=lambda x: x[1])
    final = []
    for pkt, ts in pkts:
        pkt.time = ts
        final.append(pkt)

    wrpcap("/build/capture.pcap", final)
    print("Generated PCAP: {} packets".format(len(final)))


if __name__ == "__main__":
    generate()
