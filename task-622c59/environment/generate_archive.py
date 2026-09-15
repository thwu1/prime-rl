#!/usr/bin/env python3
"""Generate the LVFS archive and vfs_hasher.c source.
Used during Docker build only -- NOT present in final image."""
import struct
import zlib
import json
import base64
import random as _random


# ======== SBOX generation (deterministic) ========
_rng = _random.Random(0x47414D45)
SBOX = list(range(256))
_rng.shuffle(SBOX)


# ======== Custom hash function (matches vfs_hasher binary) ========
def custom_hash(data):
    h1 = 0x5A3C96E7
    h2 = 0x1B4F82D3
    for b in data:
        s = SBOX[b]
        h1 = (((h1 << 5) | (h1 >> 27)) & 0xFFFFFFFF) ^ s
        tmp = h1
        h1 = (h1 + h2) & 0xFFFFFFFF
        h2 = tmp
    return (h1 ^ h2) & 0xFFFFFFFF


# ======== Generate vfs_hasher.c ========
sbox_rows = []
for i in range(0, 256, 16):
    row = ", ".join("0x{:02x}".format(SBOX[i + j]) for j in range(16))
    sbox_rows.append("    " + row)
sbox_c = ",\n".join(sbox_rows)

# Build C source using raw string (no Python escape issues with C's \n and %s)
c_source = r'''#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

static const uint8_t SBOX[256] = {
SBOX_PLACEHOLDER
};

static uint32_t vpkg_hash(const uint8_t *data, size_t len) {
    uint32_t h1 = 0x5A3C96E7;
    uint32_t h2 = 0x1B4F82D3;
    size_t i;
    for (i = 0; i < len; i++) {
        uint8_t b = SBOX[data[i]];
        h1 = ((h1 << 5) | (h1 >> 27)) ^ (uint32_t)b;
        uint32_t tmp = h1;
        h1 = h1 + h2;
        h2 = tmp;
    }
    return h1 ^ h2;
}

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <file>\n", argv[0]);
        return 1;
    }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror("fopen"); return 1; }
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (sz == 0) {
        uint32_t h = vpkg_hash(NULL, 0);
        printf("%08x\n", h);
        fclose(f);
        return 0;
    }
    uint8_t *buf = (uint8_t *)malloc(sz);
    if (!buf) { fprintf(stderr, "malloc failed\n"); fclose(f); return 1; }
    fread(buf, 1, sz, f);
    fclose(f);
    uint32_t h = vpkg_hash(buf, (size_t)sz);
    printf("%08x\n", h);
    free(buf);
    return 0;
}
'''

c_source = c_source.replace("SBOX_PLACEHOLDER", sbox_c)

with open("/tmp/vfs_hasher.c", "w") as f:
    f.write(c_source)


# ======== LEB128 helpers ========
def write_leb128(value):
    """Encode unsigned LEB128."""
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def xor_encrypt(data, key):
    """Rolling XOR encryption."""
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


# ======== File contents ========
enc_key = b"Spl1nt3rC3ll_X0R_K3y!"

config_data = json.dumps({
    "engine_version": "UE2-Custom",
    "render_device": "D3DDrv.D3DRenderDevice",
    "audio_device": "XboxAudio.XboxAudioSubsystem",
    "session_key": base64.b64encode(enc_key).decode(),
    "max_texture_cache_mb": 432,
    "vertex_buffer_size": 26432,
    "index_buffer_size": 3384,
    "base_load_address": "0x139e585c"
}, indent=2).encode()

manifest_data = b"""<?xml version="1.0" encoding="UTF-8"?>
<build_manifest>
    <product name="OperationEchelon" codename="SC1-XBOX"/>
    <version major="3" minor="7" patch="2" tag="rc4"/>
    <build hash="a7f3b2c1d9e8" timestamp="2002-11-17T08:30:00Z"/>
    <engine>UnrealEngine2</engine>
    <target platform="xbox" architecture="x86"/>
</build_manifest>"""

csv_lines = ["timestamp,event_type,component,value"]
components = ["Renderer", "AudioSys", "PhysicsEngine",
              "NetworkMgr", "AssetLoader", "ScriptVM"]
for i in range(500):
    h = 8 + i // 3600
    m = (i // 60) % 60
    s = i % 60
    ts = "2002-11-17T{:02d}:{:02d}:{:02d}Z".format(h, m, s)
    if i % 12 == 7:
        evt = "ERROR"
    elif i % 5 == 0:
        evt = "WARNING"
    elif i % 3 == 0:
        evt = "DEBUG"
    else:
        evt = "INFO"
    comp = components[i % len(components)]
    val = (i * 7 + 13) % 10000
    csv_lines.append("{},{},{},{}".format(ts, evt, comp, val))
telemetry_data = "\n".join(csv_lines).encode()

flag = b"FLAG{l1n3ar1z3d_vfs_r3v3rs3_3ngin33r3d}"
encrypted_payload = xor_encrypt(flag, enc_key)

trace_data = b"""[TRACE] 2002-11-17T08:30:01Z ULinkerLoad - Loading System\\Engine.u
[TRACE] 2002-11-17T08:30:01Z ULinkerLoad - Loading System\\Core.u
[TRACE] 2002-11-17T08:30:02Z StaticLoadObject - ini:Engine.Engine.GameEngine
[TRACE] 2002-11-17T08:30:02Z CompactIndex - Value=0xE10 (3600 decimal)
[TRACE] 2002-11-17T08:30:03Z ExportPreload - class=0x0 super=0xFFFFFFFE size=0x3A8
[WARN]  2002-11-17T08:30:03Z Seek is no-op in linearized stream
[TRACE] 2002-11-17T08:30:04Z FileTable - 3582 entries, 54 linker objects
[ERROR] 2002-11-17T08:30:05Z Virtual addrs != physical offsets
[TRACE] 2002-11-17T08:30:05Z Layout: SEQUENTIAL from data_start
[DEBUG] 2002-11-17T08:30:06Z integrity_token=ECHO-7F3A9B2D
[TRACE] 2002-11-17T08:30:07Z MegaMerge complete"""

header_dat = struct.pack("<4sIIII",
    b"HDR\x00",
    0x139e585c,
    0x139b92b4,
    0x9fe3c5a3,
    0x00648EEE
)


# ======== Build LVFS archive ========
files = [
    ("engine/config.json",        config_data,       0x0000),
    ("engine/build_manifest.xml", manifest_data,     0x0001),
    ("data/telemetry.csv",        telemetry_data,    0x0001),
    ("data/secret_payload.bin",   encrypted_payload, 0x0002),
    (".internal/trace.log",       trace_data,        0x0005),
    ("assets/header.dat",         header_dat,        0x0000),
]

# Virtual addresses -- deliberately misleading (from original engine load addresses)
vaddrs = [0x139e585c, 0x13482120, 0x00534090,
          0x005FDFA0, 0x007165F0, 0x009600F0]

# File table
ft = bytearray()
ft.extend(write_leb128(len(files)))
for i, (name, data, flags) in enumerate(files):
    nb = name.encode("utf-8")
    ft.extend(write_leb128(len(nb)))
    ft.extend(nb)
    ft.extend(struct.pack("<I", vaddrs[i]))
    ft.extend(struct.pack("<I", len(data)))
    ft.extend(struct.pack("<H", flags))

# Data section (sequential, 8-byte aligned)
ds = bytearray()
for name, data, flags in files:
    if flags & 0x01:
        comp = zlib.compress(data, 6)
        ds.extend(struct.pack("<I", len(comp)))
        ds.extend(comp)
    else:
        ds.extend(data)
    pad = (8 - len(ds) % 8) % 8
    ds.extend(b"\x00" * pad)

body = bytes(ft) + bytes(ds)

# Final archive
out = bytearray()
out.extend(b"LVFS")
out.extend(struct.pack("<H", 1))
out.extend(struct.pack("<H", 0x0001))
out.extend(struct.pack("<I", len(ft)))
out.extend(struct.pack("<I", len(body)))
cbody = zlib.compress(body, 6)
out.extend(struct.pack("<I", len(cbody)))
out.extend(cbody)

with open("/app/archive.vfs", "wb") as f:
    f.write(out)

print("Generated archive.vfs: {} bytes "
      "({} files, body {} -> {} compressed)".format(
          len(out), len(files), len(body), len(cbody)))
print("Generated vfs_hasher.c with {}-byte SBOX".format(len(SBOX)))

# Sanity check: verify hash function consistency
test_val = custom_hash(b"test")
print("Hash self-test: custom_hash(b'test') = {:08x}".format(test_val))
