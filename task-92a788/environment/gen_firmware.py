#!/usr/bin/env python3
"""
Generate firmware artifacts for the dual-firmware cryptographic audit task.

Creates:
  /app/memdump.txt       - U-Boot md.b hex dump of firmware v1
  /app/ciphertext.hex    - Ciphertext encrypted by firmware v1
  /app/firmware_v2.bin   - Raw binary of firmware v2
  /app/ciphertext_v2.hex - Ciphertext encrypted by firmware v2
  /app/context.txt       - Audit context notes
"""
import struct
import zlib
import os
import random
import hashlib

# ============================================================
# AES-128-ECB (pure Python)
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
RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def xtime(a):
    return ((a << 1) ^ 0x1b) & 0xff if a & 0x80 else (a << 1) & 0xff


def aes_encrypt_block(block, key):
    state = list(block)
    ks = list(key)
    for i in range(4, 44):
        t = ks[(i - 1) * 4:(i - 1) * 4 + 4]
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RCON[i // 4 - 1]
        ks.extend([ks[(i - 4) * 4 + j] ^ t[j] for j in range(4)])
    state = [state[i] ^ ks[i] for i in range(16)]
    for r in range(1, 10):
        state = [SBOX[b] for b in state]
        s = list(state)
        s[1], s[5], s[9], s[13] = s[5], s[9], s[13], s[1]
        s[2], s[6], s[10], s[14] = s[10], s[14], s[2], s[6]
        s[3], s[7], s[11], s[15] = s[15], s[3], s[7], s[11]
        state = s
        for c in range(4):
            col = [state[4 * c + j] for j in range(4)]
            t2 = col[0] ^ col[1] ^ col[2] ^ col[3]
            u = col[0]
            col[0] ^= xtime(col[0] ^ col[1]) ^ t2
            col[1] ^= xtime(col[1] ^ col[2]) ^ t2
            col[2] ^= xtime(col[2] ^ col[3]) ^ t2
            col[3] ^= xtime(col[3] ^ u) ^ t2
            for j in range(4):
                state[4 * c + j] = col[j]
        state = [state[i] ^ ks[r * 16 + i] for i in range(16)]
    state = [SBOX[b] for b in state]
    s = list(state)
    s[1], s[5], s[9], s[13] = s[5], s[9], s[13], s[1]
    s[2], s[6], s[10], s[14] = s[10], s[14], s[2], s[6]
    s[3], s[7], s[11], s[15] = s[15], s[3], s[7], s[11]
    state = s
    state = [state[i] ^ ks[160 + i] for i in range(16)]
    return bytes(state)


def rol8(byte, n):
    return ((byte << n) | (byte >> (8 - n))) & 0xFF


def encrypt_48(plaintext, key):
    ct = b""
    for i in range(0, 48, 16):
        ct += aes_encrypt_block(plaintext[i:i + 16], key)
    return ct


# ============================================================
# V1 Parameters (original firmware — XOR obfuscation)
# ============================================================
AES_KEY_V1 = bytes([
    0xDE, 0xAD, 0xC0, 0xDE, 0x13, 0x37, 0xBE, 0xEF,
    0xCA, 0xFE, 0xF0, 0x0D, 0x42, 0x42, 0x42, 0x42
])
XOR_CONST = 0x42
PLAINTEXT_V1 = b"SECURE_TOKEN:9f3a7b2e-c841-4d05-b6e8-71fc52da093"
assert len(PLAINTEXT_V1) == 48

OBF_KEY_V1 = bytes([b ^ XOR_CONST for b in AES_KEY_V1])
KEY_CRC_V1 = zlib.crc32(AES_KEY_V1) & 0xFFFFFFFF

DECOY_A = b"AES-128-ECB-KEY1"
DECOY_B = bytes([
    0xBA, 0xAD, 0xF0, 0x0D, 0xDE, 0xAD, 0xBE, 0xEF,
    0x13, 0x37, 0x13, 0x37, 0xCA, 0xFE, 0xBA, 0xBE
])

DES_IP = bytes([
    58, 50, 42, 34, 26, 18, 10, 2,
    60, 52, 44, 36, 28, 20, 12, 4,
    62, 54, 46, 38, 30, 22, 14, 6,
    64, 56, 48, 40, 32, 24, 16, 8,
    57, 49, 41, 33, 25, 17, 9, 1,
    59, 51, 43, 35, 27, 19, 11, 3,
    61, 53, 45, 37, 29, 21, 13, 5,
    63, 55, 47, 39, 31, 23, 15, 7,
])
DES_FAKE_KEY = bytes([
    0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xF0,
    0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88
])
DES_FAKE_CRC = zlib.crc32(DES_FAKE_KEY) & 0xFFFFFFFF

# ============================================================
# V2 Parameters (updated firmware — split + rotation)
# ============================================================
AES_KEY_V2 = bytes([
    0xA1, 0xB2, 0xC3, 0xD4, 0xE5, 0xF6, 0x07, 0x18,
    0x29, 0x3A, 0x4B, 0x5C, 0x6D, 0x7E, 0x8F, 0x90
])
ROT_AMOUNT = 3
PLAINTEXT_V2 = b"firmware_v2_secret:3c9a7f2b-e184-4d5a-b6e0-7cf21"
assert len(PLAINTEXT_V2) == 48

KEY_HALF_A = AES_KEY_V2[:8]
KEY_HALF_B = AES_KEY_V2[8:]
ROT_HALF_A = bytes([rol8(b, ROT_AMOUNT) for b in KEY_HALF_A])
ROT_HALF_B = bytes([rol8(b, ROT_AMOUNT) for b in KEY_HALF_B])
CRC_HALF_A = zlib.crc32(KEY_HALF_A) & 0xFFFFFFFF
CRC_HALF_B = zlib.crc32(KEY_HALF_B) & 0xFFFFFFFF

# Decoy key half stored near region A (plausible but wrong CRC)
DECOY_HALF = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE, 0xBA, 0xBE])
ROT_DECOY = bytes([rol8(b, ROT_AMOUNT) for b in DECOY_HALF])

# ============================================================
# Compute ciphertexts
# ============================================================
ciphertext_v1 = encrypt_48(PLAINTEXT_V1, AES_KEY_V1)
ciphertext_v2 = encrypt_48(PLAINTEXT_V2, AES_KEY_V2)

# ============================================================
# Build V1 firmware (same layout as original task)
# ============================================================
CODE_SIZE = 0x0A00
EOR_OFFSET = 0x00B0
STRINGS_OFFSET = 0x0A00
KEY_REGION_OFFSET = 0x0A60
SBOX_OFFSET = 0x0AA0
DES_TABLE_OFFSET = 0x0BA0
DES_KEY_OFFSET = 0x0BE0
DES_CRC_OFFSET = 0x0BF0
DES_MARKER_OFFSET = 0x0BF4
V1_TOTAL_SIZE = 0x0C00

rng = random.Random(0xDEAD)
code = bytearray(CODE_SIZE)
for i in range(0, CODE_SIZE, 4):
    while True:
        word = bytes([rng.randint(0, 255) for _ in range(4)])
        if word[1] == 0x30 and word[2] == 0x23 and word[3] == 0xE2:
            continue
        break
    code[i:i + 4] = word

code[EOR_OFFSET] = XOR_CONST
code[EOR_OFFSET + 1] = 0x30
code[EOR_OFFSET + 2] = 0x23
code[EOR_OFFSET + 3] = 0xE2

code[0x00:0x04] = bytes([0xF0, 0x40, 0x2D, 0xE9])
code[0x04:0x08] = bytes([0x00, 0x00, 0xA0, 0xE1])
code[0x08:0x0C] = bytes([0x00, 0x00, 0xA0, 0xE3])
code[0x80:0x84] = bytes([0x00, 0x10, 0x90, 0xE5])
code[0xA0:0xA4] = bytes([0x04, 0x00, 0x00, 0xEB])
code[0xB4:0xB8] = bytes([0x00, 0x30, 0x82, 0xE5])

strings = bytearray(96)
msg1 = b"crypto subsys: init complete\x00"
strings[:len(msg1)] = msg1
msg2 = b"DES cipher: disabled\x00"
strings[0x28:0x28 + len(msg2)] = msg2
msg3 = b"SecureCore v3.1.7-arm32le\x00"
strings[0x40:0x40 + len(msg3)] = msg3

fw1 = bytearray(V1_TOTAL_SIZE)
fw1[0:CODE_SIZE] = code
fw1[STRINGS_OFFSET:STRINGS_OFFSET + 96] = strings
fw1[KEY_REGION_OFFSET:KEY_REGION_OFFSET + 16] = DECOY_A
fw1[KEY_REGION_OFFSET + 16:KEY_REGION_OFFSET + 32] = OBF_KEY_V1
fw1[KEY_REGION_OFFSET + 32:KEY_REGION_OFFSET + 48] = DECOY_B
fw1[0x0A90:0x0A94] = struct.pack('<I', KEY_CRC_V1)
fw1[0x0A94:0x0A98] = bytes([0x55, 0xAA, 0x55, 0xAA])
fw1[SBOX_OFFSET:SBOX_OFFSET + 256] = bytes(SBOX)
fw1[DES_TABLE_OFFSET:DES_TABLE_OFFSET + 64] = DES_IP
fw1[DES_KEY_OFFSET:DES_KEY_OFFSET + 16] = DES_FAKE_KEY
fw1[DES_CRC_OFFSET:DES_CRC_OFFSET + 4] = struct.pack('<I', DES_FAKE_CRC)
fw1[DES_MARKER_OFFSET:DES_MARKER_OFFSET + 4] = bytes([0xAA, 0x55, 0xAA, 0x55])

# ============================================================
# Build V2 firmware binary (1024 bytes)
# ============================================================
V2_SIZE = 1024
fw2 = bytearray(V2_SIZE)

# Header (16 bytes)
fw2[0x00:0x04] = b"FWv2"
fw2[0x04:0x08] = struct.pack('<I', 0x00030107)  # version 3.1.7
fw2[0x08:0x0C] = struct.pack('<I', 0x03)  # flags: split(1) | rotate(2)
fw2[0x0C:0x10] = struct.pack('<I', ROT_AMOUNT)

# Code section (0x10 - 0xFF): random ARM-like
rng2 = random.Random(0xBEEF)
for i in range(0x10, 0x100):
    fw2[i] = rng2.randint(0, 255)
# ARM patterns for realism
fw2[0x10:0x14] = bytes([0xF0, 0x40, 0x2D, 0xE9])  # PUSH {R4-R7, LR}
fw2[0x14:0x18] = bytes([0x00, 0x00, 0xA0, 0xE1])  # NOP
fw2[0x18:0x1C] = bytes([0x03, 0x00, 0xA0, 0xE3])  # MOV R0, #3

# String section (0x100 - 0x13F)
str_area = bytearray(64)
s1 = b"aes_engine: active\x00"
str_area[:len(s1)] = s1
s2 = b"keystore: split-rotate\x00"
str_area[0x20:0x20 + len(s2)] = s2
fw2[0x100:0x140] = str_area

# Crypto region A (0x140 - 0x15F)
fw2[0x140:0x144] = bytes([0xFE, 0xED, 0xFA, 0xCE])  # FEEDFACE marker
fw2[0x144:0x14C] = ROT_HALF_A  # rotated key half A (8 bytes)
fw2[0x14C:0x150] = struct.pack('<I', CRC_HALF_A)
# Decoy: another 8-byte block with same FEEDFACE marker but wrong CRC
fw2[0x150:0x154] = bytes([0xFE, 0xED, 0xFA, 0xCE])  # same marker
fw2[0x154:0x15C] = ROT_DECOY  # rotated decoy half
fw2[0x15C:0x160] = struct.pack('<I', 0xDEADBEEF)  # bogus CRC

# AES S-box (0x160 - 0x25F, 256 bytes)
fw2[0x160:0x260] = bytes(SBOX)

# Crypto region B (0x260 - 0x27F)
fw2[0x260:0x264] = bytes([0xCA, 0xFE, 0xD0, 0x0D])  # CAFED00D marker
fw2[0x264:0x26C] = ROT_HALF_B  # rotated key half B (8 bytes)
fw2[0x26C:0x270] = struct.pack('<I', CRC_HALF_B)

# ============================================================
# Format V1 as U-Boot md.b hex dump
# ============================================================
BASE_ADDR = 0x40200000


def format_memdump(data, base_addr):
    lines = []
    lines.append("=> md.b 0x%08x 0x%04x" % (base_addr, len(data)))
    for offset in range(0, len(data), 16):
        chunk = data[offset:offset + 16]
        addr = base_addr + offset
        hex_part = ' '.join('%02x' % b for b in chunk)
        if len(chunk) < 16:
            hex_part += '   ' * (16 - len(chunk))
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append("%08x: %-47s  %s" % (addr, hex_part, ascii_part))
    lines.append("=> ")
    return '\n'.join(lines) + '\n'


memdump = format_memdump(fw1, BASE_ADDR)

# ============================================================
# Write output files
# ============================================================
os.makedirs("/app", exist_ok=True)

with open("/app/memdump.txt", "w") as f:
    f.write(memdump)

with open("/app/ciphertext.hex", "w") as f:
    f.write(ciphertext_v1.hex() + "\n")

with open("/app/firmware_v2.bin", "wb") as f:
    f.write(bytes(fw2))

with open("/app/ciphertext_v2.hex", "w") as f:
    f.write(ciphertext_v2.hex() + "\n")

with open("/app/context.txt", "w") as f:
    f.write(
        "Firmware Security Audit - Comparative Analysis\n"
        "===============================================\n"
        "\n"
        "Two firmware revisions were recovered from an ARM embedded device\n"
        "during a security engagement.\n"
        "\n"
        "FIRMWARE V1 (Legacy):\n"
        "  Source: Memory dump captured via bootloader debug console (md.b)\n"
        "  File: memdump.txt\n"
        "  Architecture: ARMv7 32-bit little-endian\n"
        "  Load address: 0x40200000\n"
        "  Notes: This revision was deployed in production for 18 months.\n"
        "  The manufacturer claims key material is 'obfuscated' but did\n"
        "  not provide documentation on the protection scheme.\n"
        "\n"
        "FIRMWARE V2 (Updated):\n"
        "  Source: Extracted from firmware update package\n"
        "  File: firmware_v2.bin (raw binary)\n"
        "  Architecture: ARMv7 32-bit little-endian\n"
        "  Notes: This revision was developed as a 'security hardened'\n"
        "  replacement. The manufacturer claims improved key storage\n"
        "  with split key architecture and stronger obfuscation.\n"
        "\n"
        "Both firmware versions encrypt payloads using symmetric ciphers.\n"
        "Encrypted payloads from each version are provided in the\n"
        "corresponding ciphertext files.\n"
        "\n"
        "OBJECTIVES:\n"
        "  - Determine the cipher and key protection scheme for each version\n"
        "  - Recover keys and decrypt both payloads\n"
        "  - Assess whether V2 actually improves upon V1's security\n"
    )

# ============================================================
# Print hashes for test construction
# ============================================================
import sys

print("=== VERIFICATION HASHES ===", file=sys.stderr)
print(f"V1_PLAINTEXT_SHA256 = \"{hashlib.sha256(PLAINTEXT_V1).hexdigest()}\"", file=sys.stderr)
print(f"V2_PLAINTEXT_SHA256 = \"{hashlib.sha256(PLAINTEXT_V2).hexdigest()}\"", file=sys.stderr)
print(f"V1_KEY_HEX = \"{AES_KEY_V1.hex()}\"", file=sys.stderr)
print(f"V1_KEY_SHA256 = \"{hashlib.sha256(AES_KEY_V1.hex().encode()).hexdigest()}\"", file=sys.stderr)
print(f"V2_KEY_HEX = \"{AES_KEY_V2.hex()}\"", file=sys.stderr)
print(f"V2_KEY_SHA256 = \"{hashlib.sha256(AES_KEY_V2.hex().encode()).hexdigest()}\"", file=sys.stderr)

# Normalized algorithm hash: "aes128ecb"
import re
algo = "AES-128-ECB"
algo_norm = re.sub(r'[^a-z0-9]', '', algo.lower())
print(f"ALGO_NORMALIZED = \"{algo_norm}\"", file=sys.stderr)
print(f"ALGO_SHA256 = \"{hashlib.sha256(algo_norm.encode()).hexdigest()}\"", file=sys.stderr)

print(f"\nV1 ciphertext: {ciphertext_v1.hex()}", file=sys.stderr)
print(f"V2 ciphertext: {ciphertext_v2.hex()}", file=sys.stderr)
print(f"V1 firmware: {len(fw1)} bytes", file=sys.stderr)
print(f"V2 firmware: {len(fw2)} bytes", file=sys.stderr)
print(f"Files written to /app/", file=sys.stderr)
