#!/usr/bin/env python3
"""
Solve the dual-firmware cryptographic audit challenge.

"""
import struct
import zlib
import json
import sys

# ============================================================
# AES-128-ECB decryption (pure Python)
# ============================================================
SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
]
INV_SBOX = [
    0x52,0x09,0x6a,0xd5,0x30,0x36,0xa5,0x38,0xbf,0x40,0xa3,0x9e,0x81,0xf3,0xd7,0xfb,
    0x7c,0xe3,0x39,0x82,0x9b,0x2f,0xff,0x87,0x34,0x8e,0x43,0x44,0xc4,0xde,0xe9,0xcb,
    0x54,0x7b,0x94,0x32,0xa6,0xc2,0x23,0x3d,0xee,0x4c,0x95,0x0b,0x42,0xfa,0xc3,0x4e,
    0x08,0x2e,0xa1,0x66,0x28,0xd9,0x24,0xb2,0x76,0x5b,0xa2,0x49,0x6d,0x8b,0xd1,0x25,
    0x72,0xf8,0xf6,0x64,0x86,0x68,0x98,0x16,0xd4,0xa4,0x5c,0xcc,0x5d,0x65,0xb6,0x92,
    0x6c,0x70,0x48,0x50,0xfd,0xed,0xb9,0xda,0x5e,0x15,0x46,0x57,0xa7,0x8d,0x9d,0x84,
    0x90,0xd8,0xab,0x00,0x8c,0xbc,0xd3,0x0a,0xf7,0xe4,0x58,0x05,0xb8,0xb3,0x45,0x06,
    0xd0,0x2c,0x1e,0x8f,0xca,0x3f,0x0f,0x02,0xc1,0xaf,0xbd,0x03,0x01,0x13,0x8a,0x6b,
    0x3a,0x91,0x11,0x41,0x4f,0x67,0xdc,0xea,0x97,0xf2,0xcf,0xce,0xf0,0xb4,0xe6,0x73,
    0x96,0xac,0x74,0x22,0xe7,0xad,0x35,0x85,0xe2,0xf9,0x37,0xe8,0x1c,0x75,0xdf,0x6e,
    0x47,0xf1,0x1a,0x71,0x1d,0x29,0xc5,0x89,0x6f,0xb7,0x62,0x0e,0xaa,0x18,0xbe,0x1b,
    0xfc,0x56,0x3e,0x4b,0xc6,0xd2,0x79,0x20,0x9a,0xdb,0xc0,0xfe,0x78,0xcd,0x5a,0xf4,
    0x1f,0xdd,0xa8,0x33,0x88,0x07,0xc7,0x31,0xb1,0x12,0x10,0x59,0x27,0x80,0xec,0x5f,
    0x60,0x51,0x7f,0xa9,0x19,0xb5,0x4a,0x0d,0x2d,0xe5,0x7a,0x9f,0x93,0xc9,0x9c,0xef,
    0xa0,0xe0,0x3b,0x4d,0xae,0x2a,0xf5,0xb0,0xc8,0xeb,0xbb,0x3c,0x83,0x53,0x99,0x61,
    0x17,0x2b,0x04,0x7e,0xba,0x77,0xd6,0x26,0xe1,0x69,0x14,0x63,0x55,0x21,0x0c,0x7d,
]
RCON_VALS = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def gmul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xff
        if hi:
            a ^= 0x1b
        b >>= 1
    return p


def key_expansion(key):
    ks = list(key)
    for i in range(4, 44):
        t = ks[(i - 1) * 4:(i - 1) * 4 + 4]
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RCON_VALS[i // 4 - 1]
        ks.extend([ks[(i - 4) * 4 + j] ^ t[j] for j in range(4)])
    return ks


def aes_decrypt_block(ct, key):
    ks = key_expansion(list(key))
    state = list(ct)
    state = [state[i] ^ ks[160 + i] for i in range(16)]
    s = list(state)
    s[1], s[5], s[9], s[13] = s[13], s[1], s[5], s[9]
    s[2], s[6], s[10], s[14] = s[10], s[14], s[2], s[6]
    s[3], s[7], s[11], s[15] = s[7], s[11], s[15], s[3]
    state = s
    state = [INV_SBOX[b] for b in state]
    for r in range(9, 0, -1):
        state = [state[i] ^ ks[r * 16 + i] for i in range(16)]
        for c in range(4):
            s0, s1, s2, s3 = state[4*c], state[4*c+1], state[4*c+2], state[4*c+3]
            state[4*c]   = gmul(s0, 14) ^ gmul(s1, 11) ^ gmul(s2, 13) ^ gmul(s3, 9)
            state[4*c+1] = gmul(s0, 9) ^ gmul(s1, 14) ^ gmul(s2, 11) ^ gmul(s3, 13)
            state[4*c+2] = gmul(s0, 13) ^ gmul(s1, 9) ^ gmul(s2, 14) ^ gmul(s3, 11)
            state[4*c+3] = gmul(s0, 11) ^ gmul(s1, 13) ^ gmul(s2, 9) ^ gmul(s3, 14)
        s = list(state)
        s[1], s[5], s[9], s[13] = s[13], s[1], s[5], s[9]
        s[2], s[6], s[10], s[14] = s[10], s[14], s[2], s[6]
        s[3], s[7], s[11], s[15] = s[7], s[11], s[15], s[3]
        state = s
        state = [INV_SBOX[b] for b in state]
    state = [state[i] ^ ks[i] for i in range(16)]
    return bytes(state)


def decrypt_ecb(ciphertext, key):
    plaintext = b""
    for i in range(0, len(ciphertext), 16):
        plaintext += aes_decrypt_block(ciphertext[i:i + 16], key)
    return plaintext


def ror8(byte, n):
    return ((byte >> n) | (byte << (8 - n))) & 0xFF


# ============================================================
# Part 1: Solve V1 firmware (hex dump + XOR obfuscation)
# ============================================================
print("=" * 60)
print("PHASE 1: Firmware V1 Analysis")
print("=" * 60)


def parse_memdump(path):
    data = bytearray()
    base_addr = None
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('=>'):
                continue
            if ':' not in line:
                continue
            parts = line.split(':')
            if len(parts) < 2:
                continue
            try:
                addr = int(parts[0].strip(), 16)
            except ValueError:
                continue
            if base_addr is None:
                base_addr = addr
            rest = ':'.join(parts[1:])
            dsp = rest.find('  ')
            if dsp > 0:
                hex_str = rest[:dsp].strip()
            else:
                hex_str = rest.strip()
            for hb in hex_str.split():
                try:
                    data.append(int(hb, 16))
                except ValueError:
                    pass
    return bytes(data), base_addr


firmware_v1, base = parse_memdump("/app/memdump.txt")
print(f"[*] V1 firmware: {len(firmware_v1)} bytes at 0x{base:08x}")

# Scan for AES S-box
AES_SBOX_START = bytes([0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5])
DES_IP_START = bytes([58, 50, 42, 34, 26, 18, 10, 2])

sbox_offset = firmware_v1.find(AES_SBOX_START)
des_offset = firmware_v1.find(DES_IP_START)
print(f"[*] AES S-box at offset 0x{sbox_offset:04x}")
print(f"[*] DES IP table at offset 0x{des_offset:04x}")

# Extract strings
v1_strings = []
for i in range(len(firmware_v1) - 4):
    s = ""
    j = i
    while j < len(firmware_v1) and 0x20 <= firmware_v1[j] < 0x7f:
        s += chr(firmware_v1[j])
        j += 1
    if len(s) >= 8 and j < len(firmware_v1) and firmware_v1[j] == 0:
        v1_strings.append((i, s))

print(f"[*] Strings found:")
for off, s in v1_strings:
    print(f"    0x{off:04x}: \"{s}\"")

# Find XOR constant from EOR instruction
xor_const = None
for i in range(0, min(len(firmware_v1), sbox_offset), 4):
    if (i + 3 < len(firmware_v1) and
            firmware_v1[i + 1] == 0x30 and
            firmware_v1[i + 2] == 0x23 and
            firmware_v1[i + 3] == 0xe2):
        xor_const = firmware_v1[i]
        print(f"[+] EOR R3, R3, #0x{xor_const:02x} at offset 0x{i:04x}")
        break

# Find key candidates via end marker
key_region_start = sbox_offset - 64
key_region_end = sbox_offset
candidates_v1 = []
stored_crc_v1 = None

for i in range(key_region_start, key_region_end - 3):
    if firmware_v1[i:i + 4] == bytes([0x55, 0xAA, 0x55, 0xAA]):
        crc_offset = i - 4
        stored_crc_v1 = struct.unpack('<I', firmware_v1[crc_offset:crc_offset + 4])[0]
        print(f"[+] End marker at 0x{i:04x}, CRC32: 0x{stored_crc_v1:08x}")
        for j in range(3):
            offset = crc_offset - (3 - j) * 16
            candidate = firmware_v1[offset:offset + 16]
            candidates_v1.append((offset, candidate))
        break

# Evaluate V1 candidates
real_key_v1 = None
v1_rejected = []

for idx, (offset, candidate) in enumerate(candidates_v1):
    crc_raw = zlib.crc32(candidate) & 0xFFFFFFFF
    deobf = bytes([b ^ xor_const for b in candidate])
    crc_deobf = zlib.crc32(deobf) & 0xFFFFFFFF

    if crc_raw == stored_crc_v1:
        real_key_v1 = candidate
        print(f"[+] V1 key (direct): {candidate.hex()}")
    elif crc_deobf == stored_crc_v1:
        real_key_v1 = deobf
        print(f"[+] V1 key (XOR-deobfuscated): {deobf.hex()}")
    else:
        v1_rejected.append({
            "hex": candidate.hex(),
            "reason": f"CRC32 mismatch: raw=0x{crc_raw:08x}, deobf=0x{crc_deobf:08x}, expected=0x{stored_crc_v1:08x}",
            "firmware_version": "v1"
        })

# Reject DES fake key
if des_offset >= 0:
    fake_key_offset = des_offset + 64
    if fake_key_offset + 16 <= len(firmware_v1):
        fake_key = firmware_v1[fake_key_offset:fake_key_offset + 16]
        if any(b != 0 for b in fake_key):
            v1_rejected.append({
                "hex": fake_key.hex(),
                "reason": "Adjacent to DES IP table; DES is disabled per firmware strings — belongs to inactive cipher module",
                "firmware_version": "v1"
            })

# Decrypt V1
with open("/app/ciphertext.hex", "r") as f:
    ct_v1 = bytes.fromhex(f.read().strip())

plaintext_v1 = decrypt_ecb(ct_v1, real_key_v1)
print(f"[+] V1 decrypted: {plaintext_v1}")

with open("/app/answer.txt", "wb") as f:
    f.write(plaintext_v1)
print("[+] V1 answer written to /app/answer.txt")


# ============================================================
# Part 2: Solve V2 firmware (raw binary + split/rotation)
# ============================================================
print()
print("=" * 60)
print("PHASE 2: Firmware V2 Analysis")
print("=" * 60)

with open("/app/firmware_v2.bin", "rb") as f:
    firmware_v2 = f.read()

print(f"[*] V2 firmware: {len(firmware_v2)} bytes")

# Parse header
magic = firmware_v2[0:4]
version = struct.unpack('<I', firmware_v2[4:8])[0]
flags = struct.unpack('<I', firmware_v2[8:12])[0]
rot_amount = struct.unpack('<I', firmware_v2[12:16])[0]
print(f"[*] Magic: {magic}")
print(f"[*] Version: 0x{version:08x}")
print(f"[*] Flags: 0x{flags:08x} (split={flags & 1}, rotate={(flags >> 1) & 1})")
print(f"[*] Rotation amount: {rot_amount}")

# Find AES S-box in V2
sbox_v2 = firmware_v2.find(AES_SBOX_START)
print(f"[*] AES S-box at offset 0x{sbox_v2:04x}")

# Extract V2 strings
for i in range(len(firmware_v2) - 4):
    s = ""
    j = i
    while j < len(firmware_v2) and 0x20 <= firmware_v2[j] < 0x7f:
        s += chr(firmware_v2[j])
        j += 1
    if len(s) >= 8 and j < len(firmware_v2) and firmware_v2[j] == 0:
        print(f"[*] V2 string at 0x{i:04x}: \"{s}\"")

# Find key markers
MARKER_A = bytes([0xFE, 0xED, 0xFA, 0xCE])
MARKER_B = bytes([0xCA, 0xFE, 0xD0, 0x0D])

v2_rejected = []
key_half_a = None
key_half_b = None

# Search for all FEEDFACE-like markers
marker_a_positions = []
pos = 0
while True:
    idx = firmware_v2.find(MARKER_A, pos)
    if idx < 0:
        break
    marker_a_positions.append(idx)
    pos = idx + 1

print(f"[*] Found {len(marker_a_positions)} FEEDFACE markers")

for ma_pos in marker_a_positions:
    rot_data = firmware_v2[ma_pos + 4:ma_pos + 12]  # 8 bytes after marker
    stored_crc = struct.unpack('<I', firmware_v2[ma_pos + 12:ma_pos + 16])[0]

    # Reverse rotation
    candidate = bytes([ror8(b, rot_amount) for b in rot_data])
    computed_crc = zlib.crc32(candidate) & 0xFFFFFFFF

    if computed_crc == stored_crc:
        key_half_a = candidate
        print(f"[+] Key half A at 0x{ma_pos:04x}: {candidate.hex()} (CRC OK)")
    else:
        v2_rejected.append({
            "hex": candidate.hex(),
            "reason": f"CRC32 mismatch after rotation reversal: computed=0x{computed_crc:08x}, stored=0x{stored_crc:08x}. Decoy key half near marker at 0x{ma_pos:04x}",
            "firmware_version": "v2"
        })
        print(f"[-] Decoy at 0x{ma_pos:04x}: {candidate.hex()} (CRC mismatch)")

# Find CAFED00D marker
mb_pos = firmware_v2.find(MARKER_B)
if mb_pos >= 0:
    rot_data = firmware_v2[mb_pos + 4:mb_pos + 12]
    stored_crc = struct.unpack('<I', firmware_v2[mb_pos + 12:mb_pos + 16])[0]
    candidate = bytes([ror8(b, rot_amount) for b in rot_data])
    computed_crc = zlib.crc32(candidate) & 0xFFFFFFFF

    if computed_crc == stored_crc:
        key_half_b = candidate
        print(f"[+] Key half B at 0x{mb_pos:04x}: {candidate.hex()} (CRC OK)")
    else:
        v2_rejected.append({
            "hex": candidate.hex(),
            "reason": f"CRC32 mismatch: computed=0x{computed_crc:08x}, stored=0x{stored_crc:08x}",
            "firmware_version": "v2"
        })

real_key_v2 = key_half_a + key_half_b
print(f"[+] V2 full key: {real_key_v2.hex()}")

# Decrypt V2
with open("/app/ciphertext_v2.hex", "r") as f:
    ct_v2 = bytes.fromhex(f.read().strip())

plaintext_v2 = decrypt_ecb(ct_v2, real_key_v2)
print(f"[+] V2 decrypted: {plaintext_v2}")

with open("/app/answer_v2.txt", "wb") as f:
    f.write(plaintext_v2)
print("[+] V2 answer written to /app/answer_v2.txt")


# ============================================================
# Part 3: Comparative Security Assessment
# ============================================================
print()
print("=" * 60)
print("PHASE 3: Comparative Security Assessment")
print("=" * 60)

all_rejected = v1_rejected + v2_rejected

assessment = {
    "v1_algorithm": "AES-128-ECB",
    "v1_key_hex": real_key_v1.hex(),
    "v1_key_protection": (
        f"Single-byte XOR obfuscation with constant 0x{xor_const:02x}. "
        f"All key candidates stored contiguously in a 48-byte region before "
        f"the AES S-box, with a CRC32 checksum and 0x55AA55AA end marker. "
        f"The XOR constant is directly visible as an ARM EOR instruction in "
        f"the code section. Only 256 possible XOR values to brute-force."
    ),
    "v1_attack_complexity": "low",
    "v2_algorithm": "AES-128-ECB",
    "v2_key_hex": real_key_v2.hex(),
    "v2_key_protection": (
        f"Key split into two 8-byte halves stored in non-adjacent regions "
        f"separated by the 256-byte AES S-box. Each half is individually "
        f"obfuscated via {rot_amount}-bit left rotation per byte and "
        f"integrity-checked with a separate CRC32. Halves are marked with "
        f"distinct signatures (FEEDFACE / CAFED00D). A decoy half with an "
        f"intentionally wrong CRC is placed near the first real half. "
        f"The rotation amount is stored in the firmware header config block."
    ),
    "v2_attack_complexity": "medium",
    "more_secure_version": "v2",
    "justification": (
        "V2 provides materially stronger key protection than V1 through three "
        "improvements: (1) Key splitting across non-adjacent memory regions "
        "forces an attacker to locate and correctly correlate both halves, "
        "whereas V1 stores the entire key contiguously. (2) The decoy key half "
        "with a plausible-looking marker adds confusion that does not exist in "
        "V1's scheme. (3) While both use reversible obfuscation (XOR vs bit "
        "rotation), V1's XOR constant is trivially extracted from a single ARM "
        "EOR instruction, whereas V2's rotation parameter requires understanding "
        "the firmware header format. However, V2 still falls short of proper "
        "key management: the rotation amount is stored in plaintext in the "
        "header, the scheme is still symmetric obfuscation rather than "
        "cryptographic key wrapping, and the 8 possible rotation values "
        "(0-7 bits) are brute-forceable. Both versions use AES-ECB mode, which "
        "leaks block-level patterns regardless of key protection strength."
    ),
    "rejected_candidates": all_rejected
}

with open("/app/assessment.json", "w") as f:
    json.dump(assessment, f, indent=2)

print("[+] Assessment written to /app/assessment.json")
print(f"    V1: {assessment['v1_algorithm']}, complexity={assessment['v1_attack_complexity']}")
print(f"    V2: {assessment['v2_algorithm']}, complexity={assessment['v2_attack_complexity']}")
print(f"    More secure: {assessment['more_secure_version']}")
print(f"    Rejected candidates: {len(all_rejected)}")
print("[+] Done.")
