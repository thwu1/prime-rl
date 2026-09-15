#!/usr/bin/env python3
"""
Solve the LVFS archive + ELF hasher reverse engineering task.

Phase 1: Reverse engineer the LVFS binary archive format.
Phase 2: Reverse engineer the stripped ELF to extract the custom hash algorithm.
Phase 3: Create custom_hash.py and write answer.txt.
"""
import struct
import zlib
import json
import base64
import subprocess
import os
import tempfile
import xml.etree.ElementTree as ET


# ================================================================
# Phase 1: Reverse engineer and extract LVFS archive
# ================================================================

def read_leb128(data, offset):
    """Read unsigned LEB128 from data at offset. Returns (value, new_offset)."""
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    return value, offset


def xor_decrypt(data, key):
    """Rolling XOR decryption."""
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


# Read raw archive
with open("/app/archive.vfs", "rb") as f:
    raw = f.read()

# Parse header (20 bytes)
magic = raw[0:4]
assert magic == b"LVFS", "Unexpected magic: {}".format(magic)
version = struct.unpack_from("<H", raw, 4)[0]
flags = struct.unpack_from("<H", raw, 6)[0]
ft_size = struct.unpack_from("<I", raw, 8)[0]
body_size = struct.unpack_from("<I", raw, 12)[0]
cbody_size = struct.unpack_from("<I", raw, 16)[0]

print("Header: magic={} version={} flags={:#06x}".format(magic, version, flags))
print("  file_table_size={} body_size={} compressed_body_size={}".format(
    ft_size, body_size, cbody_size))

# Decompress body
body = zlib.decompress(raw[20:20 + cbody_size])
assert len(body) == body_size, (
    "Body size mismatch: got {}, expected {}".format(len(body), body_size))

# Parse file table
off = 0
entry_count, off = read_leb128(body, off)
print("\nFile table: {} entries".format(entry_count))

entries = []
for idx in range(entry_count):
    name_len, off = read_leb128(body, off)
    name = body[off:off + name_len].decode("utf-8")
    off += name_len
    vaddr = struct.unpack_from("<I", body, off)[0]
    off += 4
    usize = struct.unpack_from("<I", body, off)[0]
    off += 4
    sflags = struct.unpack_from("<H", body, off)[0]
    off += 2
    entries.append((name, vaddr, usize, sflags))
    flag_desc = []
    if sflags & 0x01:
        flag_desc.append("COMPRESSED")
    if sflags & 0x02:
        flag_desc.append("ENCRYPTED")
    if sflags & 0x04:
        flag_desc.append("HIDDEN")
    print("  [{}] {:40s} vaddr={:#010x} size={:6d} flags={}".format(
        idx, name, vaddr, usize, ",".join(flag_desc) or "NONE"))

# Extract files sequentially from data section
# Key insight: virtual addresses are from the original engine's memory map
# and do NOT correspond to positions in this archive. Data is laid out
# sequentially after the file table.
ds_off = 0
extracted = {}

for name, vaddr, usize, sflags in entries:
    abs_off = ft_size + ds_off
    if sflags & 0x01:  # compressed
        csize = struct.unpack_from("<I", body, abs_off)[0]
        ds_off += 4
        abs_off += 4
        cdata = body[abs_off:abs_off + csize]
        ds_off += csize
        fdata = zlib.decompress(cdata)
        assert len(fdata) == usize, (
            "{}: decompressed {} != expected {}".format(name, len(fdata), usize))
    else:  # raw
        fdata = body[abs_off:abs_off + usize]
        ds_off += usize

    # 8-byte alignment padding
    ds_off = (ds_off + 7) & ~7

    extracted[name] = (sflags, fdata)

print("\nExtracted {} files".format(len(extracted)))

# Get encryption key from config.json
config = json.loads(extracted["engine/config.json"][1])
enc_key = base64.b64decode(config["session_key"])
print("Encryption key recovered: {} bytes".format(len(enc_key)))

# Decrypt encrypted entries
for name in list(extracted.keys()):
    sflags, data = extracted[name]
    if sflags & 0x02:
        extracted[name] = (sflags, xor_decrypt(data, enc_key))
        print("Decrypted: {}".format(name))


# ================================================================
# Phase 2: Reverse engineer the stripped ELF hasher binary
# ================================================================

print("\n=== Phase 2: Analyzing ELF hasher binary ===")

# Use objdump for initial recon
print("\n--- ELF section headers ---")
result = subprocess.run(
    ["objdump", "-h", "/app/vfs_hasher"],
    capture_output=True, text=True
)
for line in result.stdout.split("\n"):
    if ".rodata" in line or ".text" in line:
        print("  " + line.strip())

# Show disassembly excerpt
print("\n--- Disassembly excerpt (hash function) ---")
result = subprocess.run(
    ["objdump", "-d", "/app/vfs_hasher"],
    capture_output=True, text=True
)
disasm_lines = result.stdout.split("\n")
# Find the hash function by looking for the init constant
for i, line in enumerate(disasm_lines):
    if "5a3c96e7" in line.lower():
        # Print surrounding context
        start = max(0, i - 5)
        end = min(len(disasm_lines), i + 20)
        for dl in disasm_lines[start:end]:
            print("  " + dl)
        break

# Extract SBOX from the binary by scanning for a 256-byte permutation
with open("/app/vfs_hasher", "rb") as f:
    binary = f.read()

sbox = None
sbox_offset = None
for i in range(len(binary) - 255):
    candidate = binary[i:i + 256]
    if len(set(candidate)) == 256:
        sbox = list(candidate)
        sbox_offset = i
        break

assert sbox is not None, "Could not find SBOX in binary"
print("\nFound SBOX at binary offset {:#x} ({} unique bytes)".format(
    sbox_offset, len(set(sbox))))
print("SBOX[0:16] = {}".format(
    ["{:#04x}".format(x) for x in sbox[:16]]))

# From disassembly analysis of the hash function:
# - Two 32-bit state variables initialized to 0x5A3C96E7 and 0x1B4F82D3
# - For each input byte: substitute through SBOX, XOR into left-rotated h1,
#   then Fibonacci-style update (h1 = h1 + h2, h2 = old h1)
# - Final output: h1 XOR h2


# ================================================================
# Phase 3: Create custom_hash.py and write answer.txt
# ================================================================

print("\n=== Phase 3: Creating deliverables ===")

# Write custom_hash.py
# IMPORTANT: The generated source must NOT contain the binary's filename
# or any subprocess-related strings, as the test suite bans them.
sbox_repr = repr(sbox)
custom_hash_source = (
    '#!/usr/bin/env python3\n'
    '"""Custom hash: S-box substitution + ROL-XOR-Fibonacci state machine.\n'
    '\n'
    'Algorithm reverse-engineered from stripped ELF binary via objdump:\n'
    '  - 256-byte substitution table (S-box) in .rodata\n'
    '  - Two 32-bit state variables: h1=0x5A3C96E7, h2=0x1B4F82D3\n'
    '  - Per-byte: substitute via S-box, XOR into ROL(h1,5),\n'
    '    Fibonacci update (h1=h1+h2, h2=old_h1)\n'
    '  - Output: h1 ^ h2\n'
    '"""\n'
    '\n'
    'SBOX = ' + sbox_repr + '\n'
    '\n'
    '\n'
    'def custom_hash(data):\n'
    '    """Compute the proprietary integrity hash for arbitrary inputs."""\n'
    '    if isinstance(data, str):\n'
    '        data = data.encode()\n'
    '    h1 = 0x5A3C96E7\n'
    '    h2 = 0x1B4F82D3\n'
    '    for byte in data:\n'
    '        b = SBOX[byte]\n'
    '        h1 = (((h1 << 5) | (h1 >> 27)) & 0xFFFFFFFF) ^ b\n'
    '        tmp = h1\n'
    '        h1 = (h1 + h2) & 0xFFFFFFFF\n'
    '        h2 = tmp\n'
    '    return (h1 ^ h2) & 0xFFFFFFFF\n'
    '\n'
    '\n'
    'if __name__ == "__main__":\n'
    '    import sys\n'
    '    if len(sys.argv) != 2:\n'
    '        print("Usage: {} <file>".format(sys.argv[0]))\n'
    '        sys.exit(1)\n'
    '    with open(sys.argv[1], "rb") as f:\n'
    '        data = f.read()\n'
    '    print("{:08x}".format(custom_hash(data)))\n'
)

with open("/app/custom_hash.py", "w") as f:
    f.write(custom_hash_source)
print("Wrote /app/custom_hash.py")

# Validate custom_hash.py against the binary hasher on multiple test vectors
import importlib.util
spec = importlib.util.spec_from_file_location("custom_hash", "/app/custom_hash.py")
ch_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ch_mod)

manifest_data = extracted["engine/build_manifest.xml"][1]
py_hash = ch_mod.custom_hash(manifest_data)
print("custom_hash(manifest) = {:08x}".format(py_hash))

# Cross-validate against the binary on several test vectors
print("\nCross-validation against binary hasher:")
test_inputs = [b"test", manifest_data, bytes(range(256)), b"A" * 100]
for idx, td in enumerate(test_inputs):
    fd, tmp_path = tempfile.mkstemp(suffix=".bin")
    with os.fdopen(fd, "wb") as tf:
        tf.write(td)
    result = subprocess.run(
        ["/app/vfs_hasher", tmp_path],
        capture_output=True, text=True, timeout=10
    )
    os.unlink(tmp_path)
    expected = result.stdout.strip()
    actual = "{:08x}".format(ch_mod.custom_hash(td))
    match = "OK" if actual == expected else "MISMATCH"
    print("  Vector {} ({:5d} bytes): binary={} python={} [{}]".format(
        idx, len(td), expected, actual, match))
    assert actual == expected, "Hash mismatch on test vector {}!".format(idx)
print("All cross-validation checks passed.")

# Extract answer values

# 1. Version from build manifest XML
manifest_xml = extracted["engine/build_manifest.xml"][1].decode("utf-8")
root = ET.fromstring(manifest_xml)
v = root.find("version")
version_str = "{}.{}.{}-{}".format(
    v.get("major"), v.get("minor"), v.get("patch"), v.get("tag"))
print("\nVersion: {}".format(version_str))

# 2. Flag from decrypted payload
flag_str = extracted["data/secret_payload.bin"][1].decode("utf-8")
print("Flag: {}".format(flag_str))

# 3. Error count from telemetry CSV
telemetry = extracted["data/telemetry.csv"][1].decode("utf-8")
lines = telemetry.strip().split("\n")
error_count = sum(1 for line in lines[1:] if ",ERROR," in line)
print("Error count: {}".format(error_count))

# 4. Integrity token from hidden trace log
trace = extracted[".internal/trace.log"][1].decode("utf-8")
token = None
for line in trace.split("\n"):
    if "integrity_token=" in line:
        token = line.split("integrity_token=")[1].strip()
        break
print("Integrity token: {}".format(token))

# Write answer file
with open("/app/answer.txt", "w") as f:
    f.write("version={}\n".format(version_str))
    f.write("flag={}\n".format(flag_str))
    f.write("error_count={}\n".format(error_count))
    f.write("integrity_token={}\n".format(token))

print("\nAnswer written to /app/answer.txt")
