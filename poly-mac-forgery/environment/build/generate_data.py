#!/usr/bin/env python3
"""
Build-time data generator. Creates PCAP, SQLite DB, and target info.
This script is deleted from the Docker image after execution.
"""

import struct
import os
import sqlite3
import random

random.seed(42)

# ========== Crypto primitives ==========

def tea_encrypt(v_bytes, key_bytes):
    v0, v1 = struct.unpack('>II', v_bytes)
    k = struct.unpack('>IIII', key_bytes)
    delta = 0x9E3779B9
    s = 0
    for _ in range(32):
        s = (s + delta) & 0xFFFFFFFF
        v0 = (v0 + (((v1 << 4) + k[0]) ^ (v1 + s) ^ ((v1 >> 5) + k[1]))) & 0xFFFFFFFF
        v1 = (v1 + (((v0 << 4) + k[2]) ^ (v0 + s) ^ ((v0 >> 5) + k[3]))) & 0xFFFFFFFF
    return struct.pack('>II', v0, v1)

REDUCTION = 0x1B

def gf64_mul(a, b):
    result = 0
    mask = (1 << 64) - 1
    for _ in range(64):
        if b & 1:
            result ^= a
        b >>= 1
        carry = a >> 63
        a = (a << 1) & mask
        if carry:
            a ^= REDUCTION
    return result

def compute_mac(ct_bytes, h, s):
    blocks = []
    for i in range(0, len(ct_bytes), 8):
        blocks.append(int.from_bytes(ct_bytes[i:i + 8], 'big'))
    acc = 0
    for block in blocks:
        acc = gf64_mul(acc ^ block, h)
    return acc ^ s

def derive_keys(nonce_bytes, key_bytes):
    h_bytes = tea_encrypt(nonce_bytes, key_bytes)
    s_nonce = bytes([b ^ 0xFF for b in nonce_bytes])
    s_bytes = tea_encrypt(s_nonce, key_bytes)
    return int.from_bytes(h_bytes, 'big'), int.from_bytes(s_bytes, 'big')

# ========== Parameters ==========

KEY = bytes.fromhex("a3b1c2d4e5f60718293a4b5c6d7e8f90")
NONCES = {
    'alpha': bytes.fromhex("0011223344556677"),
    'beta':  bytes.fromhex("aabbccddeeff0011"),
    'gamma': bytes.fromhex("1122334455667788"),
}

TARGET_CT = bytes.fromhex(
    "70f4e974aeb9176ace932eb7c91cc9c5"
    "315bb8a0672b63affe59fb8948f07fdb"
    "a96b19d6a818842b"
)

# ========== Generate messages ==========

messages = []

# Alpha session: 3 messages with REUSED nonce
for i in range(3):
    ct = bytes([random.randint(0, 255) for _ in range(40)])
    nonce = NONCES['alpha']
    h, s = derive_keys(nonce, KEY)
    tag = compute_mac(ct, h, s)
    messages.append({
        'session': 'alpha', 'msg_id': i,
        'nonce': nonce, 'ciphertext': ct, 'tag': tag,
    })

# Beta session: 2 messages
for i in range(2):
    ct = bytes([random.randint(0, 255) for _ in range(40)])
    nonce = NONCES['beta']
    h, s = derive_keys(nonce, KEY)
    tag = compute_mac(ct, h, s)
    messages.append({
        'session': 'beta', 'msg_id': 3 + i,
        'nonce': nonce, 'ciphertext': ct, 'tag': tag,
    })

# Gamma session: 2 messages
for i in range(2):
    ct = bytes([random.randint(0, 255) for _ in range(40)])
    nonce = NONCES['gamma']
    h, s = derive_keys(nonce, KEY)
    tag = compute_mac(ct, h, s)
    messages.append({
        'session': 'gamma', 'msg_id': 5 + i,
        'nonce': nonce, 'ciphertext': ct, 'tag': tag,
    })

# ========== PCAP generation ==========

def ip_checksum(hdr):
    if len(hdr) % 2:
        hdr += b'\x00'
    total = 0
    for i in range(0, len(hdr), 2):
        total += (hdr[i] << 8) + hdr[i + 1]
    while total >> 16:
        total = (total >> 16) + (total & 0xFFFF)
    return (~total) & 0xFFFF

def make_udp_packet(src_port, dst_port, payload, src_ip, dst_ip, pkt_id=0):
    udp_len = 8 + len(payload)
    udp_hdr = struct.pack('>HHHH', src_port, dst_port, udp_len, 0)
    ip_total = 20 + udp_len
    ip_hdr = struct.pack('>BBHHHBBH4s4s',
                         0x45, 0, ip_total,
                         pkt_id, 0x4000,
                         64, 17, 0,
                         src_ip, dst_ip)
    chk = ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('>H', chk) + ip_hdr[12:]
    eth_hdr = (b'\x00\x50\x56\xc0\x00\x01'
               b'\x00\x50\x56\xc0\x00\x02'
               b'\x08\x00')
    return eth_hdr + ip_hdr + udp_hdr + payload

src_ip = bytes([10, 0, 1, 100])
dst_ip = bytes([10, 0, 1, 200])
pcap_packets = []
base_ts = 1700000000

# Protocol messages (port 4443, version 0x02)
for msg in messages:
    tag_bytes = msg['tag'].to_bytes(8, 'big')
    payload = (bytes([0x02])
               + struct.pack('>H', msg['msg_id'])
               + msg['nonce']
               + msg['ciphertext']
               + tag_bytes)
    src_port = 10000 + random.randint(0, 50000)
    pkt = make_udp_packet(src_port, 4443, payload, src_ip, dst_ip, msg['msg_id'])
    pcap_packets.append((base_ts + msg['msg_id'] * 5, pkt))

# Decoy: DNS (port 53)
for i in range(8):
    dns_payload = bytes([random.randint(0, 255) for _ in range(random.randint(20, 60))])
    pkt = make_udp_packet(random.randint(10000, 60000), 53, dns_payload, src_ip, dst_ip, 100 + i)
    pcap_packets.append((base_ts + 2 + i * 3, pkt))

# Decoy: SNMP (port 161)
for i in range(4):
    snmp_payload = bytes([random.randint(0, 255) for _ in range(random.randint(30, 90))])
    pkt = make_udp_packet(random.randint(10000, 60000), 161, snmp_payload, src_ip, dst_ip, 200 + i)
    pcap_packets.append((base_ts + 1 + i * 8, pkt))

# Decoy: old protocol v1 on port 4443
for i in range(3):
    old_payload = bytes([0x01]) + bytes([random.randint(0, 255) for _ in range(random.randint(15, 30))])
    pkt = make_udp_packet(random.randint(10000, 60000), 4443, old_payload, src_ip, dst_ip, 300 + i)
    pcap_packets.append((base_ts + 4 + i * 12, pkt))

pcap_packets.sort(key=lambda x: x[0])

os.makedirs('/app/capture', exist_ok=True)
with open('/app/capture/traffic.pcap', 'wb') as f:
    f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
    for ts, pkt_data in pcap_packets:
        f.write(struct.pack('<IIII', ts, 0, len(pkt_data), len(pkt_data)))
        f.write(pkt_data)

# ========== SQLite database ==========

os.makedirs('/app/db', exist_ok=True)
conn = sqlite3.connect('/app/db/sessions.db')
cur = conn.cursor()

cur.execute('''CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    nonce_hex TEXT NOT NULL,
    created_at TEXT NOT NULL,
    description TEXT
)''')

cur.execute('''CREATE TABLE messages (
    msg_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    ciphertext_len INTEGER NOT NULL,
    status TEXT DEFAULT 'verified',
    captured_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
)''')

cur.execute('''CREATE TABLE targets (
    target_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    ciphertext_hex TEXT NOT NULL,
    status TEXT DEFAULT 'pending_auth',
    notes TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
)''')

sessions_data = [
    ('alpha-3', NONCES['alpha'].hex(), '2024-11-14 08:00:00', 'Sensor array alpha, channel 3'),
    ('beta-1',  NONCES['beta'].hex(),  '2024-11-14 08:15:00', 'Sensor array beta, channel 1'),
    ('gamma-7', NONCES['gamma'].hex(), '2024-11-14 08:30:00', 'Sensor array gamma, channel 7'),
]
cur.executemany('INSERT INTO sessions VALUES (?,?,?,?)', sessions_data)

session_map = {'alpha': 'alpha-3', 'beta': 'beta-1', 'gamma': 'gamma-7'}
for msg in messages:
    cur.execute('INSERT INTO messages VALUES (?,?,?,?,?)',
                (msg['msg_id'], session_map[msg['session']],
                 len(msg['ciphertext']), 'verified',
                 '2024-11-14 08:{:02d}:00'.format(msg['msg_id'] * 10)))

cur.execute('INSERT INTO targets VALUES (?,?,?,?,?)',
            (99, 'alpha-3', TARGET_CT.hex(), 'pending_auth',
             'Intercepted ciphertext requiring MAC tag forgery'))

conn.commit()
conn.close()

# ========== Target info file ==========

os.makedirs('/app/data', exist_ok=True)
with open('/app/data/target_info.txt', 'w') as f:
    f.write("Target: Forge a valid authentication tag for target_id=99\n")
    f.write("Session and ciphertext details are in /app/db/sessions.db\n")
    f.write("Write the 16-char lowercase hex tag to /app/output/forged_tag.txt\n")

# ========== Verify ==========

h, s = derive_keys(NONCES['alpha'], KEY)
expected_tag = compute_mac(TARGET_CT, h, s)
print("Data generation complete.")
print("  PCAP: /app/capture/traffic.pcap ({} packets)".format(len(pcap_packets)))
print("  SQLite: /app/db/sessions.db")
print("  Expected tag: {:016x}".format(expected_tag))
