#!/usr/bin/env python3
"""
Setup script for APT implant forensics challenge.
Run during Docker build to generate all challenge artifacts.
Deleted from final image via multi-stage build.
"""

import hashlib
import sqlite3
import os
import base64
import json
import struct

# ============================================================
# DETERMINISTIC PARAMETERS (no PRNG)
# ============================================================

MASTER_KEY = bytes.fromhex("428a1f73de55b094c73ea26109f58d4b")
AUTH_TOKEN = bytes.fromhex("78e13c05a962d7f3b4d6e8fa1c3e5a7d")

# Corrupted version stored in DB: bytes at positions 3 and 6 zeroed,
# simulating partial recovery from forensic acquisition of volatile memory
CORRUPTED_AUTH_TOKEN_HEX = "78e13c00a96200f3b4d6e8fa1c3e5a7d"
CORRUPTED_BYTE_POSITIONS = [3, 6]

NODE_ID = "ECHO-7-ALPHA-4921"
ACTIVE_SESSION_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"

COMPLETED_SESSION_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
FAILED_SESSION_ID = "a1b2c3d4-5e6f-7890-abcd-ef1234567890"
COMPLETED_AUTH_TOKEN = "9a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
FAILED_AUTH_TOKEN = "1f2e3d4c5b6a79880f1e2d3c4b5a6978"

DECOY_FRAG_1 = "e7a3b5c9d1f20846"
DECOY_FRAG_3 = "5d8e2f1a4b7c3069"
DECOY_FRAG_5 = "92c4d6e8fa1b3d5e"

ENTROPY_POOL_DECOY = base64.b64encode(
    bytes.fromhex("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
).decode()

CHUNK_SIZES = [347, 283, 361, 299, 317, 313]
CHUNK_FILENAMES = [
    "3a7f2c9e1b4d.enc", "8e5d1a3f7c2b.enc", "4b9e6d2a1f3c.enc",
    "c7a3e5f1d8b2.enc", "6f2d8b4e9a1c.enc", "1d5e3a7b9c4f.enc",
    "9b2f7d4e6a8c.enc", "d3c1a9e7f5b2.enc",
]

# Order in which exfil packets appear in the pcap (scrambled)
PCAP_EXFIL_ORDER = [4, 1, 6, 0, 5, 3, 2]

# ============================================================
# PLAINTEXT DOCUMENT
# ============================================================

PLAINTEXT = b"""CLASSIFICATION: TOP SECRET//SI//NOFORN
DOCUMENT-ID: TS-MERIDIAN-2024-7X4921-DELTA
DATE: 15 September 2024
ORIGINATOR: COL Sarah Mitchell, SITE ECHO-7 FACILITY LEAD

========================================
PROJECT MERIDIAN - QUARTERLY STATUS REPORT
REPORTING PERIOD: Q3 FY2024
========================================

1. EXECUTIVE SUMMARY

Phase III deployment of MERIDIAN collection infrastructure achieved full
operational capability on 15 AUG 2024. All primary objectives for the
quarter have been met. Integration with UPSTREAM SIGINT feeds proceeds
ahead of schedule. Two critical zero-day vulnerabilities in the target
network VPN concentrator were identified; exploitation tooling for
CVE-2024-31337 is under active development by the Tools Division.

2. COLLECTION METRICS (CURRENT QUARTER)

Total intercepts processed ........... 847,293
Actionable products generated ........ 1,247
New selector nominations approved .... 342
Automated triage accuracy ............ 97.7%
Average processing latency ........... 3.2 sec
Encrypted traffic decrypted .......... 12.4%
Storage utilization .................. 73.1%

3. TECHNICAL OPERATIONS

3.1 Relay Network Infrastructure

The MERIDIAN relay mesh now operates 12 active nodes across 4 geographic
regions (EUCOM, PACOM, CENTCOM, AFRICOM). Performance metrics:

  Average tunnel latency ....... 47 ms  (req: <100 ms)
  Maximum observed latency ..... 189 ms
  Packet loss rate ............. 0.003%
  Network uptime ............... 99.97%

Node ECHO-7-ALPHA-4921 serves as primary aggregation point for PACOM
region collection. Bandwidth allocation increased 40% this quarter to
accommodate expanded tasking requirements.

3.2 Adversary Analysis

Primary target GRANITE BEAR continues operating from previously
identified infrastructure. New C2 domains confirmed via passive DNS:

  - api-telemetry-cdn[.]example[.]net
  - resource-optimize[.]example[.]cloud
  - static-delivery-hub[.]example[.]org

Secondary target COBALT SPHINX migrated to Tor-based C2 architecture
on approximately 22 JUL 2024. Deployment of ONION HARVEST collection
capabilities authorized under FISA Order 2024-1193.

3.3 Vulnerability Research

CVE-2024-31337 (RESERVED): Heap buffer overflow in target custom VPN
daemon 'vpn_concentrator' version 2.4.1-rc3. Attack requires valid
session token but achieves arbitrary code execution in kernel context.
CVSS 3.1 base score: 8.1. Proof-of-concept complete. Operational
weaponization estimated Q4 FY2024.

4. COUNTERINTELLIGENCE ASSESSMENT

Operational security posture: GREEN (no change from prior quarter)

- No indicators of adversary awareness of MERIDIAN operations
- All covert communication channels tested and verified
- Personnel security reviews completed for all cleared staff
- Physical security sweep of SITE ECHO-7: negative findings
- TSCM sweep conducted 03 SEP 2024: no anomalies detected

5. RESOURCE REQUIREMENTS

- Additional GPU cluster allocation for ML-based traffic analysis
- Two (2) senior reverse engineers (GG-14/15) for VPN exploit dev
- 50TB additional storage for long-term SIGINT retention
- TEMPEST-certified replacement hardware for aging Terminal Room B

6. NEXT QUARTER OBJECTIVES

  [ ] Complete Phase IV geographic expansion (2 new CONUS nodes)
  [ ] Full integration with SIGINT National Tasking System (SNTS)
  [ ] Deploy v3.0 encrypted traffic analysis pipeline
  [ ] Operationalize CVE-2024-31337 exploit chain
  [ ] Initiate COBALT SPHINX enhanced collection (Project DEEP REEF)

7. AUTHENTICATION

Prepared by: COL Sarah Mitchell, USAF
Verified by: CAPT James Rodriguez, USN
Authentication code: SIGMA-7-ECHO-TANGO-4921-FOXTROT

========================================
END OF REPORT
DISTRIBUTION: MERIDIAN INDOC ONLY
CLASSIFICATION: TOP SECRET//SI//NOFORN
========================================
"""

# ============================================================
# CIPHER IMPLEMENTATION (must match crypto_engine.c exactly)
# ============================================================

PHI = 0x9E3779B9
BLK_SIZE = 256
FB_SIZE = 16


def ksa(key):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    return S


def encrypt(plaintext, key, tweak):
    S = ksa(key)
    ct = bytearray()
    for i, b in enumerate(plaintext):
        sb = S[b]
        tb = tweak[i % len(tweak)]
        pb = ((i + 1) * PHI) & 0xFF
        ct.append(sb ^ tb ^ pb)
        if (i + 1) % BLK_SIZE == 0:
            fb = bytes(ct[max(0, len(ct) - FB_SIZE):])
            j = 0
            for k in range(256):
                j = (j + S[k] + fb[k % len(fb)]) % 256
                S[k], S[j] = S[j], S[k]
    return bytes(ct)


# ============================================================
# KEY DERIVATION
# ============================================================

node_id_md5 = hashlib.md5(NODE_ID.encode("utf-8")).digest()

raw_fragment_2 = bytes(
    a ^ b for a, b in zip(MASTER_KEY[:8], AUTH_TOKEN[:8])
)
raw_fragment_4 = bytes(
    a ^ b for a, b in zip(MASTER_KEY[8:], node_id_md5[:8])
)

TWEAK = hashlib.sha256(ACTIVE_SESSION_ID.encode("utf-8")).digest()[:8]

# ============================================================
# PCAP HELPERS
# ============================================================


def ip_checksum(header_bytes):
    """Compute IP header checksum (one's complement sum)."""
    if len(header_bytes) % 2 == 1:
        header_bytes = header_bytes + b'\x00'
    total = 0
    for i in range(0, len(header_bytes), 2):
        total += (header_bytes[i] << 8) + header_bytes[i + 1]
    while total > 0xFFFF:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def make_udp_packet(src_ip, dst_ip, src_port, dst_port, payload, ip_id=0):
    """Create an Ethernet/IP/UDP packet."""
    src_b = bytes(int(x) for x in src_ip.split('.'))
    dst_b = bytes(int(x) for x in dst_ip.split('.'))

    # Ethernet (14 bytes)
    eth = (b'\x00\x50\x56\xc0\x00\x08'
           + b'\x00\x0c\x29\x4e\x7d\x2a'
           + struct.pack('>H', 0x0800))

    # IP header with checksum=0 first
    ip_len = 20 + 8 + len(payload)
    ip_hdr = struct.pack('>BBHHHBBH4s4s',
                         0x45, 0x00, ip_len,
                         ip_id & 0xFFFF, 0x4000,
                         64, 17, 0x0000,
                         src_b, dst_b)
    cksum = ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('>H', cksum) + ip_hdr[12:]

    # UDP (8 bytes)
    udp_len = 8 + len(payload)
    udp = struct.pack('>HHHH', src_port, dst_port, udp_len, 0x0000)

    return eth + ip_hdr + udp + payload


def write_pcap(filepath, packets):
    """Write a pcap file. packets = [(timestamp_sec, packet_bytes), ...]."""
    with open(filepath, 'wb') as f:
        # Global header
        f.write(struct.pack('<IHHiIII',
                            0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts, pkt_data in packets:
            f.write(struct.pack('<IIII', ts, 0, len(pkt_data), len(pkt_data)))
            f.write(pkt_data)


# ============================================================
# GENERATE ARTIFACTS
# ============================================================

os.makedirs("/app/exfil", exist_ok=True)

# --- Encrypt the document ---
ciphertext = encrypt(PLAINTEXT, MASTER_KEY, TWEAK)

# --- Split into chunks ---
chunks = []
pos = 0
for sz in CHUNK_SIZES:
    if pos >= len(ciphertext):
        break
    end = min(pos + sz, len(ciphertext))
    chunks.append(ciphertext[pos:end])
    pos = end
if pos < len(ciphertext):
    chunks.append(ciphertext[pos:])

num_chunks = len(chunks)

# --- Write encrypted chunk files ---
for i in range(num_chunks):
    filepath = f"/app/exfil/{CHUNK_FILENAMES[i]}"
    with open(filepath, "wb") as f:
        f.write(chunks[i])

# --- Generate pcap with exfil traffic and noise ---
pcap_packets = []
base_ts = 1726358400
ts = base_ts
ip_id_counter = 1000

IMPLANT_IP = "10.0.0.45"
C2_IP = "203.0.113.42"
DNS_IP = "8.8.8.8"

# Heartbeat payload (port 443)
heartbeat_payload = struct.pack('>I', 0xBEEF0001) + b'\x00' * 12

# DNS query payload (port 53)
dns_payload = (b'\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00'
               b'\x03api\x09telemetry\x03cdn\x07example\x03net\x00'
               b'\x00\x01\x00\x01')

# Keepalive probe payload for exfil port (different magic from exfil protocol)
keepalive_exfil_payload = struct.pack('>I', 0xBEEF0002) + b'\x00' * 8

# Initial noise packets before exfiltration
for n in range(3):
    pkt = make_udp_packet(IMPLANT_IP, C2_IP, 49152 + n, 443,
                          heartbeat_payload, ip_id_counter)
    pcap_packets.append((ts, pkt))
    ip_id_counter += 1
    ts += 2

# Interleave exfil and noise packets
for pcap_idx, chunk_idx in enumerate(PCAP_EXFIL_ORDER):
    if chunk_idx >= num_chunks:
        continue

    # Noise: heartbeat before each exfil
    hb_pkt = make_udp_packet(IMPLANT_IP, C2_IP, 49200 + pcap_idx, 443,
                             heartbeat_payload, ip_id_counter)
    pcap_packets.append((ts, hb_pkt))
    ip_id_counter += 1
    ts += 1

    # Noise: DNS query every other packet
    if pcap_idx % 2 == 0:
        dns_pkt = make_udp_packet(IMPLANT_IP, DNS_IP,
                                  49300 + pcap_idx, 53,
                                  dns_payload, ip_id_counter)
        pcap_packets.append((ts, dns_pkt))
        ip_id_counter += 1
        ts += 1

    # Noise: keepalive probe on exfil port (same dst port, different magic)
    if pcap_idx % 2 == 1:
        ka_pkt = make_udp_packet(IMPLANT_IP, C2_IP,
                                  49450 + pcap_idx, 8443,
                                  keepalive_exfil_payload, ip_id_counter)
        pcap_packets.append((ts, ka_pkt))
        ip_id_counter += 1
        ts += 1

    # Exfil packet: magic(4) + seq(4) + chunk_data
    exfil_payload = struct.pack('>II', 0xC0DE0001, chunk_idx) + chunks[chunk_idx]
    exfil_pkt = make_udp_packet(IMPLANT_IP, C2_IP,
                                49400 + pcap_idx, 8443,
                                exfil_payload, ip_id_counter)
    pcap_packets.append((ts, exfil_pkt))
    ip_id_counter += 1
    ts += 3

# Trailing noise
for n in range(2):
    pkt = make_udp_packet(IMPLANT_IP, C2_IP, 49500 + n, 443,
                          heartbeat_payload, ip_id_counter)
    pcap_packets.append((ts, pkt))
    ip_id_counter += 1
    ts += 2

write_pcap("/app/exfil_traffic.pcap", pcap_packets)

# --- Create SQLite database ---
db = sqlite3.connect("/app/implant.db")
cur = db.cursor()

# Config table
cur.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
config_entries = [
    ("node_id", NODE_ID),
    ("version", "3.2.1"),
    ("beacon_interval", "300"),
    ("max_retries", "5"),
    ("proxy_chain", "socks5://10.0.0.1:1080"),
    ("fallback_dns", "8.8.8.8"),
    ("install_date", "2024-06-12T03:45:00Z"),
    ("entropy_pool", ENTROPY_POOL_DECOY),
    ("debug_level", "0"),
    ("c2_primary", "https://api-telemetry-cdn.example.net/v2/collect"),
    ("c2_fallback", "https://static-delivery-hub.example.org/api/health"),
    ("heartbeat_jitter", "15"),
    ("exfil_max_chunk", "512"),
    ("exfil_port", "8443"),
]
cur.executemany("INSERT INTO config VALUES (?, ?)", config_entries)

# Key fragments table (includes decoys)
cur.execute("""CREATE TABLE key_fragments (
    fragment_id INTEGER PRIMARY KEY,
    fragment_type TEXT NOT NULL,
    fragment_data TEXT NOT NULL,
    created_at TEXT,
    checksum TEXT
)""")

fragments_data = [
    (1, "init_vector", DECOY_FRAG_1,
     "2024-06-12T03:45:01Z",
     hashlib.sha256(bytes.fromhex(DECOY_FRAG_1)).hexdigest()[:16]),
    (2, "primary", raw_fragment_2.hex(),
     "2024-06-12T03:45:02Z",
     hashlib.sha256(raw_fragment_2).hexdigest()[:16]),
    (3, "session_salt", DECOY_FRAG_3,
     "2024-06-12T03:45:03Z",
     hashlib.sha256(bytes.fromhex(DECOY_FRAG_3)).hexdigest()[:16]),
    (4, "secondary", base64.b64encode(raw_fragment_4).decode(),
     "2024-06-12T03:45:04Z",
     hashlib.sha256(raw_fragment_4).hexdigest()[:16]),
    (5, "recovery_shard", DECOY_FRAG_5,
     "2024-06-12T03:45:05Z",
     hashlib.sha256(bytes.fromhex(DECOY_FRAG_5)).hexdigest()[:16]),
]
cur.executemany(
    "INSERT INTO key_fragments VALUES (?, ?, ?, ?, ?)", fragments_data
)

# Sessions table
cur.execute("""CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    auth_token TEXT NOT NULL,
    enc_mode TEXT,
    data_integrity TEXT DEFAULT 'full',
    start_time INTEGER,
    end_time INTEGER,
    src_addr TEXT,
    heartbeat_count INTEGER
)""")
sessions_data = [
    (COMPLETED_SESSION_ID, "completed", COMPLETED_AUTH_TOKEN,
     "stream", "full",
     1718000000, 1718003600, "10.0.0.45", 12),
    (ACTIVE_SESSION_ID, "active", CORRUPTED_AUTH_TOKEN_HEX,
     "recovery", "partial_recovery",
     1718100000, None, "10.0.0.45", 847),
    (FAILED_SESSION_ID, "failed", FAILED_AUTH_TOKEN,
     "stream", "full",
     1717900000, 1717900060, "10.0.0.45", 0),
]
cur.executemany(
    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", sessions_data
)

# Message log table
cur.execute("""CREATE TABLE message_log (
    msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    chunk_file TEXT,
    chunk_size INTEGER,
    msg_type TEXT,
    timestamp INTEGER,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
)""")
db_insert_order = [3, 0, 5, 1, 6, 4, 2]
for idx in db_insert_order:
    if idx >= num_chunks:
        continue
    cur.execute(
        "INSERT INTO message_log "
        "(session_id, chunk_file, chunk_size, msg_type, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (ACTIVE_SESSION_ID, CHUNK_FILENAMES[idx], len(chunks[idx]),
         "exfil", base_ts),
    )

db.commit()
db.close()

# --- Write agent_loader.py (partially recovered module) ---
loader_content = """\
'''
agent_loader.py - Reconstructed from process memory dump
Build: 3.2.1-release | Recovery: partial (heap pages 0x7f4a2c..0x7f4a30 missing)

Symbol cross-ref (libcrypto.so):
  se_init / se_transform  -- stream cipher engine (ctx size ~288 bytes)
  re_init / re_transform  -- recovery/fallback engine (ctx size ~36 bytes)

Runtime notes:
  - Engine selection observed via session enc_mode field
  - enc_mode populated during transport negotiation (_Transport.negotiate)
  - WARNING: enc_mode may reflect operator-configured override, not the
    actual negotiated mode; _Transport.negotiate body not recovered
'''
import ctypes as _c
import hashlib as _h
import base64 as _b

# Two distinct call paths traced in execution logs:
#   Path A (stream): se_init(ctx, key, klen, tweak, tlen) -> se_transform(...)
#   Path B (recovery): re_init(ctx, entropy, elen, iv, ilen) -> re_transform(...)

def _xb(a, b):
    return bytes(x ^ y for x, y in zip(a, b))

def _dk(cfg, kf, ss):
    '''Key material derivation for stream engine path.'''
    _n = cfg['node_id'].encode('utf-8')
    _d = _h.md5(_n).digest()
    _p = bytes.fromhex(kf['primary'])
    _t = bytes.fromhex(ss['auth_token'])
    _s = _b.b64decode(kf['secondary'])
    return _xb(_p, _t[:8]) + _xb(_s, _d[:8])

def _tw(sid):
    '''Operational tweak from session binding.'''
    return _h.sha256(sid.encode('utf-8')).digest()[:8]

# --- Engine dispatch (from branch trace reconstruction) ---
# if ss.get('enc_mode') == 'recovery':
#     _ent = _b.b64decode(cfg.get('entropy_pool', ''))
#     ctx = _c_re_init(lib_handle, _ent, b'\\x00' * 16)
# else:
#     _k = _dk(cfg, kf, ss)
#     _twk = _tw(ss['session_id'])
#     ctx = _c_se_init(lib_handle, _k, _twk)
#
# --- Memory dump truncated at 0x7f4a2c001a40 ---
# --- Remaining heap pages (0x7f4a30+) not recoverable ---
"""

with open("/app/agent_loader.py", "w") as f:
    f.write(loader_content)

# No verification data is stored in the image.
# Tests verify by computational re-derivation.

print(f"[+] Challenge setup complete")
print(f"[+] Plaintext: {len(PLAINTEXT)} bytes")
print(f"[+] Ciphertext: {len(ciphertext)} bytes, {num_chunks} chunks")
print(f"[+] PCAP: {len(pcap_packets)} packets written")
