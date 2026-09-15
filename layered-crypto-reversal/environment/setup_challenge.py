#!/usr/bin/env python3
"""Generate challenge artifacts for the crypto forensic investigation task.
Runs during Docker build to create /app/ challenge files:
  - key_params.json (RSA public key)
  - session.pcap (network capture with handshake + encrypted data)
"""
import random
import struct
import json
import os

# Deterministic seed for reproducible generation
random.seed(0x464C415245_4F4E_3232)

FLAG = b"TBENCH{xtea_pcbc_raw_rsa3_spec_mismatch}"

# ============================================================
# RSA Key Generation
# ============================================================

SMALL_PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43,
                47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97]


def miller_rabin(n, k=25):
    if n < 2:
        return False
    if n == 2 or n == 3:
        return True
    if n % 2 == 0:
        return False
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2
    for _ in range(k):
        a = random.randrange(2, n - 1)
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def gen_prime(bits):
    while True:
        p = random.getrandbits(bits)
        p |= (1 << (bits - 1)) | 1
        if p % 3 == 1:
            continue
        if any(p % sp == 0 and p != sp for sp in SMALL_PRIMES):
            continue
        if miller_rabin(p):
            return p


def icbrt(n):
    """Integer cube root via Newton's method."""
    if n <= 0:
        return 0
    x = 1 << ((n.bit_length() + 2) // 3)
    while True:
        y = (2 * x + n // (x * x)) // 3
        if y >= x:
            return x
        x = y


# ============================================================
# XTEA (matches crypto_engine.c exactly)
# ============================================================

XTEA_DELTA = 0x9E3779B9
XTEA_ROUNDS = 32
MASK32 = 0xFFFFFFFF


def xtea_encrypt(v0, v1, key):
    s = 0
    for _ in range(XTEA_ROUNDS):
        v0 = (v0 + ((((v1 << 4) ^ (v1 >> 5)) + v1) ^ (s + key[s & 3]))) & MASK32
        s = (s + XTEA_DELTA) & MASK32
        v1 = (v1 + ((((v0 << 4) ^ (v0 >> 5)) + v0) ^ (s + key[(s >> 11) & 3]))) & MASK32
    return v0, v1


def xtea_decrypt(v0, v1, key):
    s = (XTEA_DELTA * XTEA_ROUNDS) & MASK32
    for _ in range(XTEA_ROUNDS):
        v1 = (v1 - ((((v0 << 4) ^ (v0 >> 5)) + v0) ^ (s + key[(s >> 11) & 3]))) & MASK32
        s = (s - XTEA_DELTA) & MASK32
        v0 = (v0 - ((((v1 << 4) ^ (v1 >> 5)) + v1) ^ (s + key[s & 3]))) & MASK32
    return v0, v1


def xor8(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


# ============================================================
# PCAP File Construction
# ============================================================

def ip_checksum(hdr):
    if len(hdr) % 2:
        hdr += b'\x00'
    s = 0
    for i in range(0, len(hdr), 2):
        s += (hdr[i] << 8) + hdr[i + 1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def build_udp_packet(src_mac, dst_mac, src_ip, dst_ip,
                     src_port, dst_port, payload, pkt_id):
    udp_len = 8 + len(payload)
    ip_len = 20 + udp_len

    # UDP header (checksum 0 is valid for IPv4 UDP)
    udp = struct.pack('>HHHH', src_port, dst_port, udp_len, 0)

    # IPv4 header (no options)
    src_b = bytes(int(x) for x in src_ip.split('.'))
    dst_b = bytes(int(x) for x in dst_ip.split('.'))
    ip = struct.pack('>BBHHHBBH', 0x45, 0x00, ip_len, pkt_id,
                     0x4000, 64, 17, 0) + src_b + dst_b
    cksum = ip_checksum(ip)
    ip = ip[:10] + struct.pack('>H', cksum) + ip[12:]

    # Ethernet header
    eth = dst_mac + src_mac + struct.pack('>H', 0x0800)

    return eth + ip + udp + payload


def create_pcap(packets):
    """packets = [(raw_bytes, ts_sec, ts_usec), ...]"""
    hdr = struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
    data = hdr
    for pkt, ts, tus in packets:
        data += struct.pack('<IIII', ts, tus, len(pkt), len(pkt)) + pkt
    return data


# ============================================================
# Generate Challenge
# ============================================================

print("Generating RSA key pair (e=3, 2048-bit modulus)...")
p = gen_prime(1024)
q = gen_prime(1024)
n = p * q
e = 3
print(f"  n = {n.bit_length()}-bit, e = {e}")

# Deterministic XTEA key (16 bytes → 4 uint32 LE)
K = bytes(random.getrandbits(8) for _ in range(16))
key_words = [struct.unpack('<I', K[i*4:(i+1)*4])[0] for i in range(4)]
print(f"  XTEA key: {K.hex()}")

# Deterministic IV (8 bytes)
IV = bytes(random.getrandbits(8) for _ in range(8))
print(f"  IV: {IV.hex()}")

# --- RSA key encapsulation ---
PREFIX = b"PROTO_V2_SESSKEY"
M = PREFIX + K  # 32 bytes total
M_int = int.from_bytes(M, 'big')
C_rsa = pow(M_int, e, n)

# Verify cube root works (M^3 < n since M is 256-bit, n is 2048-bit)
assert M_int ** 3 == C_rsa, "Modular reduction occurred!"
recovered = icbrt(C_rsa)
assert recovered == M_int, "Cube root recovery failed!"
print("  Cube root attack verified OK")

# --- XTEA-PCBC encryption ---
pad_len = 8 - (len(FLAG) % 8)
if pad_len == 0:
    pad_len = 8
padded = FLAG + bytes([pad_len] * pad_len)
print(f"  Plaintext: {len(FLAG)} bytes → padded: {len(padded)} bytes")

ciphertext = b""
feedback = IV
for i in range(0, len(padded), 8):
    block = padded[i:i+8]
    xored = xor8(block, feedback)
    v0, v1 = struct.unpack('<II', xored)
    ev0, ev1 = xtea_encrypt(v0, v1, key_words)
    ct_block = struct.pack('<II', ev0, ev1)
    ciphertext += ct_block
    feedback = xor8(block, ct_block)

# Verify decryption round-trip
dec = b""
fb = IV
for i in range(0, len(ciphertext), 8):
    ct_block = ciphertext[i:i+8]
    v0, v1 = struct.unpack('<II', ct_block)
    dv0, dv1 = xtea_decrypt(v0, v1, key_words)
    decrypted = struct.pack('<II', dv0, dv1)
    pt_block = xor8(decrypted, fb)
    dec += pt_block
    fb = xor8(pt_block, ct_block)
dec = dec[:-dec[-1]]
assert dec == FLAG, f"Round-trip failed: {dec}"
print("  PCBC encryption/decryption verified OK")

# ============================================================
# Build PCAP
# ============================================================

CLIENT_MAC = bytes.fromhex('001122334455')
SERVER_MAC = bytes.fromhex('66778899aabb')
DNS_MAC = bytes.fromhex('aabbccddeeff')

CLIENT_IP = '10.0.1.100'
SERVER_IP = '10.0.1.200'
DNS_IP = '10.0.1.1'


def proto_msg(msg_type, payload):
    return b"PROT" + bytes([0x02, msg_type]) + payload


# Protocol messages
client_random = bytes(random.getrandbits(8) for _ in range(16))
server_random = bytes(random.getrandbits(8) for _ in range(16))

msg1 = proto_msg(0x01, bytes([3, 0x00, 0x01, 0x02]) + client_random)
msg2 = proto_msg(0x02, bytes([0x02]) + IV + server_random)

c_rsa_bytes = C_rsa.to_bytes((C_rsa.bit_length() + 7) // 8, 'big')
msg3 = proto_msg(0x03, struct.pack('>H', len(c_rsa_bytes)) + c_rsa_bytes)
msg4 = proto_msg(0x04, ciphertext)

# Protocol packets (port 9999)
pkt1 = build_udp_packet(CLIENT_MAC, SERVER_MAC, CLIENT_IP, SERVER_IP,
                         31337, 9999, msg1, 1)
pkt2 = build_udp_packet(SERVER_MAC, CLIENT_MAC, SERVER_IP, CLIENT_IP,
                         9999, 31337, msg2, 2)
pkt3 = build_udp_packet(CLIENT_MAC, SERVER_MAC, CLIENT_IP, SERVER_IP,
                         31337, 9999, msg3, 3)
pkt4 = build_udp_packet(SERVER_MAC, CLIENT_MAC, SERVER_IP, CLIENT_IP,
                         9999, 31337, msg4, 4)

# Noise packets (DNS on port 53, failed connection on port 8080)
noise1 = bytes(random.getrandbits(8) for _ in range(32))
noise2 = bytes(random.getrandbits(8) for _ in range(28))
noise3 = b"FAIL" + bytes([0x01, 0xFF]) + bytes(random.getrandbits(8) for _ in range(20))

npkt1 = build_udp_packet(CLIENT_MAC, DNS_MAC, CLIENT_IP, DNS_IP,
                          49152, 53, noise1, 100)
npkt2 = build_udp_packet(DNS_MAC, CLIENT_MAC, DNS_IP, CLIENT_IP,
                          53, 49152, noise2, 101)
npkt3 = build_udp_packet(CLIENT_MAC, SERVER_MAC, CLIENT_IP, SERVER_IP,
                          45000, 8080, noise3, 102)

# Chronological packet order
all_packets = [
    (npkt1, 1717200000, 100000),
    (npkt2, 1717200000, 200000),
    (pkt1,  1717200001, 0),
    (npkt3, 1717200001, 500000),
    (pkt2,  1717200002, 0),
    (pkt3,  1717200003, 0),
    (pkt4,  1717200004, 0),
]

pcap_data = create_pcap(all_packets)
print(f"  PCAP: {len(all_packets)} packets, {len(pcap_data)} bytes total")

# ============================================================
# Write Output Files
# ============================================================

os.makedirs('/app', exist_ok=True)

with open('/app/key_params.json', 'w') as f:
    json.dump({'n': hex(n), 'e': e}, f, indent=2)

with open('/app/session.pcap', 'wb') as f:
    f.write(pcap_data)

print("\nChallenge files written to /app/:")
print(f"  key_params.json  RSA public key (n={n.bit_length()}-bit, e={e})")
print(f"  session.pcap     {len(all_packets)} packets, {len(pcap_data)} bytes")
print(f"  (crypto_engine.so and protocol.py are COPY'd by Dockerfile)")
