#!/usr/bin/env python3
"""Generate artifact.bin — a custom linearized binary archive with randomized secrets."""
import struct
import zlib
import os
import secrets
import random
import json


def encode_compact_int(value):
    """Variable-length integer encoding (high bits indicate byte count)."""
    if value < 0x80:
        return bytes([value])
    elif value < 0x4000:
        return bytes([0x80 | (value >> 8), value & 0xFF])
    elif value < 0x200000:
        return bytes([0xC0 | (value >> 16), (value >> 8) & 0xFF, value & 0xFF])
    else:
        return bytes([0xE0 | (value >> 24), (value >> 16) & 0xFF,
                      (value >> 8) & 0xFF, value & 0xFF])


def xor_encrypt(data, file_index, key_material):
    result = bytearray(len(data))
    km_len = len(key_material)
    for i in range(len(data)):
        result[i] = data[i] ^ key_material[(file_index * 7 + i) % km_len]
    return bytes(result)


def make_nested_container(entries):
    """Build a nested container (magic 0x4E43, entry count, name/data pairs)."""
    buf = bytearray()
    buf.extend(b'\x4E\x43')
    buf.append(len(entries))
    for name, content in entries:
        nb = name.encode('utf-8')
        buf.append(len(nb))
        buf.extend(nb)
        cb = content.encode('utf-8') if isinstance(content, str) else content
        buf.extend(struct.pack('<H', len(cb)))
        buf.extend(cb)
    return bytes(buf)


# ---- Generate randomized secrets ----
rand_token = "NIGHTFALL{%s_%s_%s}" % (
    secrets.token_hex(4), secrets.token_hex(4), secrets.token_hex(4)
)
rand_master_key = secrets.token_hex(16)
rand_serial = "NF7-%s-RESTRICTED" % secrets.token_hex(4).upper()

rand_salt1 = secrets.token_hex(4)
rand_salt2 = secrets.token_hex(4)
rand_salt3 = secrets.token_hex(4)
rand_hash1 = secrets.token_hex(6)
rand_hash2 = secrets.token_hex(6)
rand_hash3 = secrets.token_hex(6)

cred_line1 = "operator-alpha:$6$rounds=5000$%s$%s" % (rand_salt1, rand_hash1)
cred_line2 = "operator-bravo:$6$rounds=5000$%s$%s" % (rand_salt2, rand_hash2)
cred_line3 = "service-account:$6$rounds=5000$%s$%s" % (rand_salt3, rand_hash3)
creds_content = "%s\n%s\n%s\n" % (cred_line1, cred_line2, cred_line3)

# 150-byte randomized key schedule
key_seed = secrets.randbelow(2**32)
rng = random.Random(key_seed)
KEY_MATERIAL = bytes([rng.randint(0, 255) for _ in range(150)])

files = [
    ("manifest.txt",
     b"Project: NIGHTFALL-7\nVersion: 3.2.1\nBuild: 20240315-rc4\n"
     b"Files: 8\nClassification: RESTRICTED\n",
     False),

    ("config.ini",
     b"[network]\nendpoint=10.0.42.17:8443\nprotocol=tls1.3\n"
     b"retry_interval=30\nmax_connections=256\n\n"
     b"[storage]\nbackend=rocksdb\npath=/var/lib/nightfall/db\n"
     b"cache_mb=512\n\n"
     b"[auth]\nmethod=certificate\nca_path=/etc/nightfall/ca.pem\n"
     b"verify_peer=true\n",
     False),

    ("debug.log",
     b"[2024-03-15 08:12:01] INFO  Starting NIGHTFALL-7 service v3.2.1\n"
     b"[2024-03-15 08:12:01] INFO  Loading configuration from /etc/nightfall/config.ini\n"
     b"[2024-03-15 08:12:02] WARN  Certificate expires in 30 days\n"
     b"[2024-03-15 08:12:02] INFO  Database initialized: 1,247 records loaded\n"
     b"[2024-03-15 08:12:03] INFO  Listening on 10.0.42.17:8443\n"
     b"[2024-03-15 08:12:15] INFO  Connection from 10.0.42.100:49221\n"
     b"[2024-03-15 08:12:15] DEBUG Auth challenge sent, awaiting response\n"
     b"[2024-03-15 08:12:16] INFO  Client authenticated: operator-alpha\n"
     b"[2024-03-15 08:12:16] INFO  Session established: sid=a3f7c901\n",
     False),

    ("keystore.nc",
     make_nested_container([
         ("master_key", rand_master_key),
         ("serial", rand_serial),
         ("token", rand_token),
     ]),
     True),

    ("firmware.bin",
     bytes(range(256)) * 4,
     False),

    ("credentials.enc",
     creds_content.encode('utf-8'),
     True),

    ("README.md",
     b"# NIGHTFALL-7 Deployment Guide\n\n"
     b"Internal documentation for NIGHTFALL-7 field deployment.\n\n"
     b"## Quick Start\n"
     b"1. Load firmware onto target device\n"
     b"2. Configure network parameters via config.ini\n"
     b"3. Initialize keystore with master credentials\n"
     b"4. Verify connectivity through diagnostic endpoint\n\n"
     b"## Security Notes\n"
     b"- All credentials are stored in encrypted keystore\n"
     b"- Master key required for keystore access\n"
     b"- Rotate credentials every 90 days\n",
     False),

    ("telemetry.dat",
     b"TELEMETRY_V2\n"
     b"timestamp=1710489600\n"
     b"uptime_hours=2847\n"
     b"packets_sent=1893742\n"
     b"packets_recv=1893501\n"
     b"errors=241\n"
     b"last_checkin=1710489590\n"
     b"status=OPERATIONAL\n",
     True),
]

# ---- Build the decompressed byte stream ----
stream = bytearray()

# Header
stream.extend(b'\xC0\xDE\xBA\x5E')          # magic
stream.extend(struct.pack('<H', 0x0201))     # version 2.1
stream.extend(struct.pack('<H', 0x0001))     # flags

# Counts
stream.extend(encode_compact_int(len(files)))          # num_entries  (8)
stream.extend(encode_compact_int(len(KEY_MATERIAL)))   # key_sched_len (150 -> 2 bytes)

# Key material
stream.extend(KEY_MATERIAL)

# File table
virtual_offset = 0x00040000   # red-herring base address
for i, (name, content, encrypted) in enumerate(files):
    name_bytes = name.encode('utf-8') + b'\x00'
    stream.extend(encode_compact_int(len(name_bytes)))
    stream.extend(name_bytes)
    stream.extend(struct.pack('<I', virtual_offset))             # virtual offset (useless)
    stream.extend(struct.pack('<I', len(content)))               # data size
    stream.extend(struct.pack('<I', zlib.crc32(content) & 0xFFFFFFFF))  # CRC32
    stream.append(1 if encrypted else 0)                         # encryption flag
    virtual_offset += len(content)
    virtual_offset = (virtual_offset + 0xF) & ~0xF              # align to 16

# File data — written sequentially in file-table order
for i, (name, content, encrypted) in enumerate(files):
    if encrypted:
        stream.extend(xor_encrypt(content, i, KEY_MATERIAL))
    else:
        stream.extend(content)

decompressed = bytes(stream)

# ---- Compress into size-prefixed zlib blocks ----
BLOCK_SIZE = 0x4000   # 16 KiB
output = bytearray()
pos = 0
while pos < len(decompressed):
    chunk = decompressed[pos:pos + BLOCK_SIZE]
    compressed = zlib.compress(chunk, 6)
    output.extend(struct.pack('<I', len(chunk)))        # decompressed size
    output.extend(struct.pack('<I', len(compressed)))   # compressed size
    output.extend(compressed)
    pos += BLOCK_SIZE

os.makedirs('/app', exist_ok=True)
with open('/app/artifact.bin', 'wb') as f:
    f.write(bytes(output))

# ---- Save verification data for test harness ----
verification = {
    "token": rand_token,
    "num_files": len(files),
    "file_names": sorted(name for name, _, _ in files),
    "encrypted_count": sum(1 for _, _, enc in files if enc),
    "credential_lines": [cred_line1, cred_line2, cred_line3],
}
os.makedirs('/var/lib/task', exist_ok=True)
with open('/var/lib/task/.verification.json', 'w') as f:
    json.dump(verification, f)

print("artifact.bin: %d bytes compressed, %d decompressed" % (len(output), len(decompressed)))
print("Verification data saved to /var/lib/task/.verification.json")
