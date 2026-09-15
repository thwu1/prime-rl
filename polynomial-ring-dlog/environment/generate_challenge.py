#!/usr/bin/env python3
"""
Generate the challenge pcap file containing a CryptoExchange key exchange session.
This script runs during Docker build and is deleted afterward.
"""

import hashlib
import os
import struct

from scapy.all import (
    Ether, IP, TCP, UDP, DNS, DNSQR, DNSRR, Raw, wrpcap, conf
)
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

conf.verb = 0


# ── GF(2) polynomial arithmetic ──

def poly_degree(f):
    return -1 if f == 0 else f.bit_length() - 1

def poly_mul(f, g):
    result = 0
    while g:
        if g & 1:
            result ^= f
        f <<= 1
        g >>= 1
    return result

def poly_mod(f, g):
    dg = poly_degree(g)
    while True:
        df = poly_degree(f)
        if df < dg:
            return f
        f ^= g << (df - dg)

def poly_mulmod(f, g, m):
    return poly_mod(poly_mul(f, g), m)

def poly_powmod(base, exp, mod):
    result = 1
    base = poly_mod(base, mod)
    while exp > 0:
        if exp & 1:
            result = poly_mulmod(result, base, mod)
        exp >>= 1
        base = poly_mulmod(base, base, mod)
    return result


# ── Crypto parameters ──

F_MODULUS = 0x15d38708255efb951       # degree-64 reducible polynomial over GF(2)
GENERATOR = 0xbdd640fb06671ad3

# Fixed private keys for deterministic generation
PRIV_A = 0x7a3b1c9d5e4f2a68
PRIV_B = 0x2d8e6f1a4c7b3950

PUB_A = poly_powmod(GENERATOR, PRIV_A, F_MODULUS)
PUB_B = poly_powmod(GENERATOR, PRIV_B, F_MODULUS)

SHARED_A = poly_powmod(PUB_B, PRIV_A, F_MODULUS)
SHARED_B = poly_powmod(PUB_A, PRIV_B, F_MODULUS)
assert SHARED_A == SHARED_B, "Key exchange verification failed"

shared_bytes = SHARED_A.to_bytes((SHARED_A.bit_length() + 7) // 8, 'big')
aes_key = hashlib.sha256(shared_bytes).digest()[:16]

FLAG = b"FLAG{p0lyn0m1al_r1ng_f4ct0r1ng_m33ts_p0hl1g_h3llm4n_CRT_d15cr3te_l0g}"
IV = hashlib.sha256(b"CryptoExchange-Session-IV-v1").digest()[:16]
cipher = AES.new(aes_key, AES.MODE_CBC, iv=IV)
CIPHERTEXT = cipher.encrypt(pad(FLAG, 16))


# ── Protocol messages ──

MAGIC = b'\xCE\xFF'

def make_msg(msg_type, payload):
    return MAGIC + struct.pack('!BH', msg_type, len(payload)) + payload

msg_init    = make_msg(0x01, b'\x01')
msg_params  = make_msg(0x02, F_MODULUS.to_bytes(9, 'big') + GENERATOR.to_bytes(8, 'big'))
msg_pubkey_a = make_msg(0x03, PUB_A.to_bytes(8, 'big'))
msg_pubkey_b = make_msg(0x04, PUB_B.to_bytes(8, 'big'))
msg_cipher  = make_msg(0x05, IV + struct.pack('!I', len(CIPHERTEXT)) + CIPHERTEXT)


# ── Build pcap ──

C_IP, S_IP = "10.13.37.100", "10.13.37.200"
C_PORT, S_PORT = 54321, 31337
C_MAC, S_MAC = "02:00:0a:0d:25:64", "02:00:0a:0d:25:c8"

N_IP  = "10.13.37.101"      # noise client
DNS_IP = "10.13.37.1"       # DNS server
HTTP_IP = "93.184.216.34"   # HTTP server
TLS_IP = "10.13.37.50"      # TLS server

packets = []
t = 1700000000.0

# ─ Noise: DNS query + response ─
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=N_IP, dst=DNS_IP)/UDP(sport=12345, dport=53)/DNS(rd=1, qd=DNSQR(qname="exchange.local"))
p.time = t + 0.10; packets.append(p)
p = Ether(src=S_MAC, dst=C_MAC)/IP(src=DNS_IP, dst=N_IP)/UDP(sport=53, dport=12345)/DNS(qr=1, aa=1, qd=DNSQR(qname="exchange.local"), an=DNSRR(rrname="exchange.local", rdata=S_IP))
p.time = t + 0.15; packets.append(p)

# ─ Noise: HTTP session (TCP port 80) ─
hs_c, hs_s = 5000, 50000
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=N_IP, dst=HTTP_IP)/TCP(sport=48080, dport=80, flags='S', seq=hs_c)
p.time = t + 0.20; packets.append(p)
p = Ether(src=S_MAC, dst=C_MAC)/IP(src=HTTP_IP, dst=N_IP)/TCP(sport=80, dport=48080, flags='SA', seq=hs_s, ack=hs_c+1)
p.time = t + 0.25; packets.append(p)
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=N_IP, dst=HTTP_IP)/TCP(sport=48080, dport=80, flags='A', seq=hs_c+1, ack=hs_s+1)
p.time = t + 0.30; packets.append(p)

http_req = b"GET /api/v1/status HTTP/1.1\r\nHost: exchange.local\r\nAccept: application/json\r\n\r\n"
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=N_IP, dst=HTTP_IP)/TCP(sport=48080, dport=80, flags='PA', seq=hs_c+1, ack=hs_s+1)/Raw(load=http_req)
p.time = t + 0.35; packets.append(p)

http_resp = b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{"status":"running","protocol":"CryptoExchange","version":"1.0","uptime":86400}'
p = Ether(src=S_MAC, dst=C_MAC)/IP(src=HTTP_IP, dst=N_IP)/TCP(sport=80, dport=48080, flags='PA', seq=hs_s+1, ack=hs_c+1+len(http_req))/Raw(load=http_resp)
p.time = t + 0.50; packets.append(p)

# ─ Key exchange: TCP handshake (port 31337) ─
sc, ss = 100000, 200000
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=C_IP, dst=S_IP)/TCP(sport=C_PORT, dport=S_PORT, flags='S', seq=sc)
p.time = t + 1.00; packets.append(p); sc += 1
p = Ether(src=S_MAC, dst=C_MAC)/IP(src=S_IP, dst=C_IP)/TCP(sport=S_PORT, dport=C_PORT, flags='SA', seq=ss, ack=sc)
p.time = t + 1.05; packets.append(p); ss += 1
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=C_IP, dst=S_IP)/TCP(sport=C_PORT, dport=S_PORT, flags='A', seq=sc, ack=ss)
p.time = t + 1.10; packets.append(p)

# Client -> Server: INIT
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=C_IP, dst=S_IP)/TCP(sport=C_PORT, dport=S_PORT, flags='PA', seq=sc, ack=ss)/Raw(load=msg_init)
p.time = t + 1.50; packets.append(p); sc += len(msg_init)
p = Ether(src=S_MAC, dst=C_MAC)/IP(src=S_IP, dst=C_IP)/TCP(sport=S_PORT, dport=C_PORT, flags='A', seq=ss, ack=sc)
p.time = t + 1.55; packets.append(p)

# ─ Interleaved noise: TLS handshake (port 8443) ─
ts_c, ts_s = 300000, 400000
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=N_IP, dst=TLS_IP)/TCP(sport=55555, dport=8443, flags='S', seq=ts_c)
p.time = t + 1.60; packets.append(p); ts_c += 1
p = Ether(src=S_MAC, dst=C_MAC)/IP(src=TLS_IP, dst=N_IP)/TCP(sport=8443, dport=55555, flags='SA', seq=ts_s, ack=ts_c)
p.time = t + 1.65; packets.append(p); ts_s += 1
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=N_IP, dst=TLS_IP)/TCP(sport=55555, dport=8443, flags='A', seq=ts_c, ack=ts_s)
p.time = t + 1.70; packets.append(p)

# Server -> Client: PARAMS
p = Ether(src=S_MAC, dst=C_MAC)/IP(src=S_IP, dst=C_IP)/TCP(sport=S_PORT, dport=C_PORT, flags='PA', seq=ss, ack=sc)/Raw(load=msg_params)
p.time = t + 2.00; packets.append(p); ss += len(msg_params)
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=C_IP, dst=S_IP)/TCP(sport=C_PORT, dport=S_PORT, flags='A', seq=sc, ack=ss)
p.time = t + 2.05; packets.append(p)

# More noise: TLS ClientHello
tls_hello = b'\x16\x03\x01\x00\xf1\x01\x00\x00\xed\x03\x03' + os.urandom(32) + b'\x20' + os.urandom(32) + b'\x00\x02\x13\x01\x01\x00'
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=N_IP, dst=TLS_IP)/TCP(sport=55555, dport=8443, flags='PA', seq=ts_c, ack=ts_s)/Raw(load=tls_hello)
p.time = t + 2.10; packets.append(p); ts_c += len(tls_hello)

# Client -> Server: PUBKEY_A
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=C_IP, dst=S_IP)/TCP(sport=C_PORT, dport=S_PORT, flags='PA', seq=sc, ack=ss)/Raw(load=msg_pubkey_a)
p.time = t + 2.50; packets.append(p); sc += len(msg_pubkey_a)
p = Ether(src=S_MAC, dst=C_MAC)/IP(src=S_IP, dst=C_IP)/TCP(sport=S_PORT, dport=C_PORT, flags='A', seq=ss, ack=sc)
p.time = t + 2.55; packets.append(p)

# Server -> Client: PUBKEY_B
p = Ether(src=S_MAC, dst=C_MAC)/IP(src=S_IP, dst=C_IP)/TCP(sport=S_PORT, dport=C_PORT, flags='PA', seq=ss, ack=sc)/Raw(load=msg_pubkey_b)
p.time = t + 3.00; packets.append(p); ss += len(msg_pubkey_b)
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=C_IP, dst=S_IP)/TCP(sport=C_PORT, dport=S_PORT, flags='A', seq=sc, ack=ss)
p.time = t + 3.05; packets.append(p)

# TLS noise response
tls_resp = b'\x16\x03\x03\x00\x31\x02\x00\x00\x2d\x03\x03' + os.urandom(32) + b'\x00\x13\x01\x00'
p = Ether(src=S_MAC, dst=C_MAC)/IP(src=TLS_IP, dst=N_IP)/TCP(sport=8443, dport=55555, flags='PA', seq=ts_s, ack=ts_c)/Raw(load=tls_resp)
p.time = t + 3.20; packets.append(p); ts_s += len(tls_resp)

# Server -> Client: ENCRYPTED
p = Ether(src=S_MAC, dst=C_MAC)/IP(src=S_IP, dst=C_IP)/TCP(sport=S_PORT, dport=C_PORT, flags='PA', seq=ss, ack=sc)/Raw(load=msg_cipher)
p.time = t + 3.50; packets.append(p); ss += len(msg_cipher)
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=C_IP, dst=S_IP)/TCP(sport=C_PORT, dport=S_PORT, flags='A', seq=sc, ack=ss)
p.time = t + 3.55; packets.append(p)

# Final noise: another DNS query
p = Ether(src=C_MAC, dst=S_MAC)/IP(src=N_IP, dst=DNS_IP)/UDP(sport=12346, dport=53)/DNS(rd=1, qd=DNSQR(qname="metrics.exchange.local"))
p.time = t + 4.00; packets.append(p)

# ─ Write pcap ─
os.makedirs('/app', exist_ok=True)
wrpcap('/app/capture.pcap', packets)

print(f"Generated capture.pcap with {len(packets)} packets")
print(f"  Modulus:  {hex(F_MODULUS)}")
print(f"  Public A: {hex(PUB_A)}")
print(f"  Public B: {hex(PUB_B)}")
print(f"  Shared:   {hex(SHARED_A)}")
print(f"  AES key:  {aes_key.hex()}")
print(f"  IV:       {IV.hex()}")
print(f"  CT len:   {len(CIPHERTEXT)}")
