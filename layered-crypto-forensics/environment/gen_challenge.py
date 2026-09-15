#!/usr/bin/env python3
"""Generate challenge artifacts during Docker build.
Produces: PCAP with two covert DNS channels, process memory dump, incident notes,
and verification hash. Runs in builder stage then is discarded."""

import struct
import hashlib
import os
import random

# ===== Exfiltrated data (the target for recovery) =====
EXFIL_DATA = '{"host":"prod-db-01","user":"svc_backup","token":"a9f3e2c1b8d7046f5e3a1c9b8d7f6e5a4c3b2d1e0f9a8b7c6d5e4f3a2b1c0d9e","exfil_ts":1709251200}'

# ===== Heartbeat status (decoy channel data) =====
HEARTBEAT_DATA = "UP:monitor.internal.net:8443:30:7"

# ===== Key derivation (matches C binary's init_session) =====
def derive_key(seed):
    key = [0, 0, 0, 0]
    h = 0x811c9dc5
    for i, b in enumerate(seed):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
        key[i % 4] ^= h
    return key

SEED = b"agent-session-2024-rev3"
XTEA_KEY = derive_key(SEED)
XTEA_ROUNDS = 32

# Config key used in the binary (ckey in main)
CONFIG_KEY = [0xA1B2C3D4, 0xE5F60718, 0x293A4B5C, 0x6D7E8F90]

# ===== Modified XTEA (matches C binary's transform_block) =====
def xtea_encrypt_block(v0, v1, key, rounds=32):
    delta = (key[0] ^ key[2]) | 0x80000001
    delta &= 0xFFFFFFFF
    s = 0
    m = 0xFFFFFFFF
    for _ in range(rounds):
        v0 = (v0 + ((((v1 << 4) ^ (v1 >> 5)) + v1) ^ (s + key[s & 3]))) & m
        s = (s + delta) & m
        v1 = (v1 + ((((v0 << 4) ^ (v0 >> 5)) + v0) ^ (s + key[(s >> 11) & 3]))) & m
    return v0, v1

def xtea_encrypt(data, key, rounds=32):
    padded = data + b'\x00' * ((8 - len(data) % 8) % 8)
    result = bytearray()
    for i in range(0, len(padded), 8):
        v0, v1 = struct.unpack('<II', padded[i:i+8])
        e0, e1 = xtea_encrypt_block(v0, v1, key, rounds)
        result.extend(struct.pack('<II', e0, e1))
    return bytes(result)

# ===== Feistel cipher (matches C binary's feistel_enc) =====
def feistel_f(x, subkey):
    x = (x ^ subkey) & 0xFFFFFFFF
    x = ((x << 7) | (x >> 25)) & 0xFFFFFFFF
    x = (x * 0x01000193) & 0xFFFFFFFF
    return x

def feistel_enc_block(l, r, key):
    for i in range(16):
        t = r
        r = (l ^ feistel_f(r, key[i & 3])) & 0xFFFFFFFF
        l = t
    return r, l  # swapped per the C code

def feistel_encrypt(data, key):
    padded = data + b'\x00' * ((8 - len(data) % 8) % 8)
    result = bytearray()
    for i in range(0, len(padded), 8):
        l, r = struct.unpack('<II', padded[i:i+8])
        el, er = feistel_enc_block(l, r, key)
        result.extend(struct.pack('<II', el, er))
    return bytes(result)

# ===== Base32 encoding (matches C binary's b32enc) =====
B32 = "abcdefghijklmnopqrstuvwxyz234567"

def base32_encode(data):
    out = []
    bits = 0
    acc = 0
    for b in data:
        acc = (acc << 8) | b
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(B32[(acc >> bits) & 0x1F])
        acc &= (1 << bits) - 1
    if bits > 0:
        out.append(B32[(acc << (5 - bits)) & 0x1F])
    return ''.join(out)

# ===== PCAP generation =====
def pcap_global_header():
    return struct.pack('<IHHiIII', 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)

def ip_checksum(hdr):
    if len(hdr) % 2:
        hdr += b'\x00'
    s = 0
    for i in range(0, len(hdr), 2):
        s += (hdr[i] << 8) + hdr[i+1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF

def dns_name_encode(domain):
    r = bytearray()
    for label in domain.split('.'):
        r.append(len(label))
        r.extend(label.encode('ascii'))
    r.append(0)
    return bytes(r)

def make_dns_query(domain, txn_id):
    msg = struct.pack('>HHHHHH', txn_id, 0x0100, 1, 0, 0, 0)
    msg += dns_name_encode(domain)
    msg += struct.pack('>HH', 1, 1)
    return msg

def make_packet(domain, ts_sec, ts_usec, src_port, rng):
    txn_id = rng.randint(1, 65535)
    dns = make_dns_query(domain, txn_id)
    udp_len = 8 + len(dns)
    udp = struct.pack('>HHH', src_port, 53, udp_len) + b'\x00\x00' + dns
    ip_total = 20 + len(udp)
    ip_hdr = struct.pack('>BBHHHBBH4s4s',
        0x45, 0x00, ip_total,
        rng.randint(1, 65535), 0x4000,
        64, 17, 0,
        bytes([10, 0, 1, 47]),
        bytes([10, 0, 1, 2]))
    chk = ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('>H', chk) + ip_hdr[12:]
    eth = b'\x00\x11\x22\x33\x44\x55\xaa\xbb\xcc\xdd\xee\xff\x08\x00'
    frame = eth + ip_hdr + udp
    return struct.pack('<IIII', ts_sec, ts_usec, len(frame), len(frame)) + frame

# ===== Memory dump generation =====
def make_memory_dump(key, seed):
    rng = random.Random(0xDEAD)
    dump = bytearray(65536)
    for i in range(len(dump)):
        dump[i] = rng.randint(0, 255)

    # ELF header fragment at 0x0800
    dump[0x0800:0x0804] = b'\x7fELF'

    # Fake/decoy key at 0x1400 (looks like it could be an encryption key)
    dump[0x1400:0x1410] = struct.pack('<IIII',
        0xDEADBEEF, 0xCAFEBABE, 0x12345678, 0x9ABCDEF0)

    # Config key bytes at 0x2000 (Feistel/heartbeat key, used for decoy channel)
    dump[0x2000:0x2010] = struct.pack('<IIII',
        CONFIG_KEY[0], CONFIG_KEY[1], CONFIG_KEY[2], CONFIG_KEY[3])

    # Agent config at 0x2800
    cfg = b'ACFG' + b'\x02\x00\x00\x00'
    cfg += b'monitor.internal.net\x00' + b'\x00' * 43
    cfg += struct.pack('<IIB', 8443, 30, 0x07)
    dump[0x2800:0x2800+len(cfg)] = cfg

    # Seed string at 0x3A00 (visible in binary too)
    dump[0x3A00:0x3A00+len(seed)+1] = seed + b'\x00'

    # Session struct with actual key at 0x3A20
    sess = struct.pack('<4sII', b'SESS', 1, 0x20240315)  # magic, ver, ts
    key_bytes = struct.pack('<IIII', key[0], key[1], key[2], key[3])
    dump[0x3A20:0x3A20+len(sess)] = sess
    dump[0x3A2C:0x3A2C+len(key_bytes)] = key_bytes

    # FNV hash state after key derivation at 0x3A3C
    h = 0x811c9dc5
    for i, b in enumerate(seed):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    dump[0x3A3C:0x3A40] = struct.pack('<I', h)

    # DNS cache at 0x5000
    domains = [b'monitor.internal.net\x00', b'cdn-telemetry.example.com\x00',
               b'api-metrics.example.com\x00',
               b'dns.google\x00', b'ntp.ubuntu.com\x00']
    off = 0x5000
    for d in domains:
        dump[off:off+len(d)] = d
        off += len(d) + 16  # gap between entries

    # Second decoy key region at 0x7800
    dump[0x7800:0x7810] = struct.pack('<IIII',
        0x41414141, 0x42424242, 0x43434343, 0x44444444)

    # Transmission buffer with partial base32 at 0x9000
    partial = b'cdn-telemetry.example.com\x00'
    dump[0x9000:0x9000+len(partial)] = partial

    # api-metrics reference at 0x9100
    partial2 = b'api-metrics.example.com\x00'
    dump[0x9100:0x9100+len(partial2)] = partial2

    return bytes(dump)

# ===== Main =====
def main():
    os.makedirs('/app', exist_ok=True)

    flag_bytes = EXFIL_DATA.encode('utf-8')
    hb_bytes = HEARTBEAT_DATA.encode('utf-8')
    print(f"[+] Exfil data: {len(flag_bytes)} bytes")
    print(f"[+] Heartbeat data: {len(hb_bytes)} bytes")

    # Encrypt exfil data with XTEA
    ciphertext = xtea_encrypt(flag_bytes, XTEA_KEY, XTEA_ROUNDS)
    print(f"[+] XTEA Ciphertext: {len(ciphertext)} bytes")
    print(f"[+] XTEA Key: {[hex(k) for k in XTEA_KEY]}")
    delta = (XTEA_KEY[0] ^ XTEA_KEY[2]) | 0x80000001
    print(f"[+] XTEA Delta: {hex(delta & 0xFFFFFFFF)}")

    # Encrypt heartbeat with Feistel
    hb_ciphertext = feistel_encrypt(hb_bytes, CONFIG_KEY)
    print(f"[+] Feistel Ciphertext: {len(hb_ciphertext)} bytes")
    print(f"[+] Config Key: {[hex(k) for k in CONFIG_KEY]}")

    # Base32 encode both
    exfil_encoded = base32_encode(ciphertext)
    hb_encoded = base32_encode(hb_ciphertext)
    print(f"[+] Exfil Base32: {len(exfil_encoded)} chars")
    print(f"[+] Heartbeat Base32: {len(hb_encoded)} chars")

    # Split into DNS chunks
    chunk_size = 50

    exfil_chunks = []
    for i in range(0, len(exfil_encoded), chunk_size):
        exfil_chunks.append((i // chunk_size, exfil_encoded[i:i+chunk_size]))

    hb_chunks = []
    for i in range(0, len(hb_encoded), chunk_size):
        hb_chunks.append((i // chunk_size, hb_encoded[i:i+chunk_size]))

    print(f"[+] Exfil DNS chunks: {len(exfil_chunks)}")
    print(f"[+] Heartbeat DNS chunks: {len(hb_chunks)}")

    # Generate PCAP
    rng = random.Random(42)
    base_ts = 1710504000  # 2024-03-15 12:00:00 UTC

    legit_domains = [
        'www.google.com', 'api.github.com', 'cdn.cloudflare.com',
        'registry.npmjs.org', 'pypi.org', 'packages.ubuntu.com',
        'ntp.ubuntu.com', 'security.ubuntu.com', 'archive.ubuntu.com',
        'dns.google', 'connectivity-check.ubuntu.com',
        'motd.ubuntu.com', 'updates.jenkins.io', 'repo.maven.apache.org',
        'download.docker.com', 'production.cloudflare.docker.com',
        'auth.docker.io', 'registry-1.docker.io', 'gcr.io',
        'storage.googleapis.com', 'metadata.google.internal',
        'monitoring.internal.net', 'ldap.internal.net', 'nfs.internal.net',
        'time.google.com',
    ]

    all_queries = []

    # Legitimate DNS queries (background noise)
    ts = base_ts
    for domain in legit_domains:
        ts += rng.randint(1, 15)
        all_queries.append((ts, rng.randint(0, 999999), domain))

    # Heartbeat channel queries (Feistel-encrypted, api-metrics domain)
    # These come FIRST — heartbeat before exfil, as in the binary
    ts = base_ts + 18
    for seq, data in hb_chunks:
        ts += rng.randint(2, 7)
        domain = f"{seq}-{data}.api-metrics.example.com"
        all_queries.append((ts, rng.randint(0, 999999), domain))

    # Exfil channel queries (XTEA-encrypted, cdn-telemetry domain)
    ts = base_ts + 45
    for seq, data in exfil_chunks:
        ts += rng.randint(3, 10)
        domain = f"{seq}-{data}.cdn-telemetry.example.com"
        all_queries.append((ts, rng.randint(0, 999999), domain))

    # Add retry/duplicate for exfil seq 1 and seq 3
    if len(exfil_chunks) > 3:
        retry_ts = base_ts + 140
        _, data1 = exfil_chunks[1]
        all_queries.append((retry_ts, rng.randint(0, 999999),
                            f"1-{data1}.cdn-telemetry.example.com"))
        retry_ts += rng.randint(5, 12)
        _, data3 = exfil_chunks[3]
        all_queries.append((retry_ts, rng.randint(0, 999999),
                            f"3-{data3}.cdn-telemetry.example.com"))

    # Add retry for heartbeat seq 0
    if len(hb_chunks) > 0:
        retry_ts = base_ts + 95
        _, hbd0 = hb_chunks[0]
        all_queries.append((retry_ts, rng.randint(0, 999999),
                            f"0-{hbd0}.api-metrics.example.com"))

    all_queries.sort(key=lambda x: (x[0], x[1]))

    pcap = pcap_global_header()
    for ts, usec, domain in all_queries:
        pcap += make_packet(domain, ts, usec, rng.randint(49152, 65535), rng)

    with open('/app/traffic_capture.pcap', 'wb') as f:
        f.write(pcap)
    print(f"[+] PCAP: {len(all_queries)} packets")

    # Generate memory dump
    mem = make_memory_dump(XTEA_KEY, SEED)
    with open('/app/process_memory.bin', 'wb') as f:
        f.write(mem)
    print(f"[+] Memory dump: {len(mem)} bytes")

    # Incident notes — mention BOTH suspicious domains
    with open('/app/incident_notes.txt', 'w') as f:
        f.write("""INCIDENT REPORT - CASE IR-2024-0847
Date: 2024-03-15
Analyst: J. Chen

Host: prod-web-03.dmz.internal (10.0.1.47)
Finding: Unknown stripped binary running as daemon process PID 4827
Service account: netmond
Binary path on host: /opt/netmond/agent (copied to /app/sample_alpha)

Observed external DNS communication to unfamiliar domains.
Traffic capture and process memory snapshot obtained before
the process was killed.

A second compromised host (staging-app-01, 10.0.2.91) was found
running a structurally similar binary (copied to /app/sample_beta).
The second binary communicates with different external domains.
No traffic or memory captures are available from the second host.

Preliminary notes:
- Both binaries appear to contain multiple cryptographic routines
- DNS traffic from the first host includes queries to TWO domains
  not in our allow-list:
    * cdn-telemetry.example.com (base32-encoded subdomains)
    * api-metrics.example.com (base32-encoded subdomains)
- Both channels carry encrypted data; unclear which (if either)
  is the primary exfiltration vector vs. operational signaling
- Process memory snapshot is 64KB from the heap region around
  the binary's session state structures
- Multiple key-like byte sequences found in memory at different
  offsets — relationship to the crypto routines is unknown
- The second binary's DNS traffic was not captured but strings
  output shows it connects to different domains

Action required: Determine which channel was used for data
exfiltration from the first host, recover the stolen data,
evaluate which binary features are reliable family indicators,
and produce a detection signature for the implant family.
""")

    # Verification hash (plaintext never stored in final image)
    with open('/app/.verification', 'w') as f:
        f.write(hashlib.sha256(flag_bytes).hexdigest())

    print(f"[+] Verification hash: {hashlib.sha256(flag_bytes).hexdigest()}")
    print("[+] Artifact generation complete")

if __name__ == '__main__':
    main()
