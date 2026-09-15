#!/usr/bin/env python3
"""Generates .vault binary archives with the proprietary container format.
Uses LCG-based encryption for file data and a different PRNG for metadata."""
import struct, zlib, hashlib, json, os, sys

def file_encrypt(data, filename, seed):
    state = seed ^ (zlib.crc32(filename.encode('ascii')) & 0xFFFFFFFF)
    result = bytearray(len(data))
    for i in range(len(data)):
        state = (state * 0x41C64E6D + 0x3039) & 0xFFFFFFFF
        key_byte = (state >> 16) & 0xFF
        result[i] = data[i] ^ key_byte
    return bytes(result)

def meta_encrypt(data, seed):
    state = (seed << 24) | (seed << 16) | (seed << 8) | seed
    result = bytearray(len(data))
    for i in range(len(data)):
        state = (state * 0x6C078965 + 1) & 0xFFFFFFFF
        key_byte = (state >> 24) & 0xFF
        result[i] = data[i] ^ key_byte
    return bytes(result)

def compact_int_encode(value):
    if value < 128:
        return bytes([value])
    elif value < 16384:
        return bytes([0x80 | ((value >> 8) & 0x3F), value & 0xFF])
    else:
        return bytes([0xC0 | ((value >> 24) & 0x3F), (value >> 16) & 0xFF,
                      (value >> 8) & 0xFF, value & 0xFF])

def get_main_files():
    files = []
    files.append(("config.ini", b"""[system]
name = VaultOS
version = 3.7.2
arch = x86_64
boot_mode = secure
watchdog_timeout = 120

[network]
interface = eth0
gateway = 10.0.42.1
netmask = 255.255.255.0
dns_primary = 8.8.8.8
dns_secondary = 1.1.1.1
mtu = 1500

[security]
auth_mode = certificate
cipher_suite = AES-256-GCM
key_rotation_days = 90
max_failed_attempts = 5
lockout_duration = 300

[logging]
level = INFO
max_size_mb = 50
rotation_count = 10
syslog_server = 10.0.42.200
""", False))
    files.append(("firmware.bin", bytes([(i * 7 + 13) & 0xFF for i in range(2048)]), True))
    files.append(("keys.db", b"""# Key Database v2.1
# Format: KEY_ID=HEX_VALUE
KEY_001=a4f8c92e1b3d7056
KEY_002=7e2b90d4c6a1f538
KEY_003=d91e47f2b08c3a65
KEY_004=b27f63a8d4e09c11
KEY_005=8c4de2710f5a39b7
MASTER=5c8a2f71e39d04b6
RECOVERY=91a7c53f2d8b064e
""", False))
    files.append(("manifest.json", json.dumps({
        "package": "vault-system", "version": "1.0.0",
        "components": ["config.ini", "firmware.bin", "keys.db", "secret.dat", "checksums.txt"],
        "build_id": "BLD-2024-0847", "target_arch": "x86_64", "min_firmware": "2.5.0"
    }, indent=2).encode('utf-8'), True))
    secret_msg = b"VAULT_SECRET_PAYLOAD:The_quick_brown_fox_jumps_over_42_lazy_dogs!"
    files.append(("secret.dat", secret_msg + b'\x00' * (256 - len(secret_msg)), True))
    checksums_lines = [f"SHA256({n}) = {hashlib.sha256(c).hexdigest()}" for n, c, _ in files[:5]]
    files.append(("checksums.txt", "\n".join(checksums_lines).encode('utf-8') + b"\n", False))
    long_name = "system_diagnostics_report_" + "a" * 96 + "_v2.log"
    diag_content = b"DIAGNOSTIC REPORT\n" + b"=" * 40 + b"\n"
    diag_content += b"CPU: nominal\nMEM: 87% utilized\nDISK: 62% utilized\n"
    diag_content += b"THERMAL: 42C core, 38C ambient\nSTATUS: ALL SYSTEMS OPERATIONAL\n"
    files.append((long_name, diag_content, False))
    return files

def get_test_files():
    files = []
    files.append(("alpha.txt", b"Hello from alpha file! This is test content.\n", False))
    files.append(("beta.bin", bytes([(i * 3 + 5) & 0xFF for i in range(512)]), True))
    files.append(("gamma.json", json.dumps({"test": True, "value": 42}).encode(), True))
    return files

def build_vault(output_path, seed, files, author="VaultMaster"):
    file_entries, compressed_datas = [], []
    for name, content, encrypted in files:
        crc = zlib.crc32(content) & 0xFFFFFFFF
        to_compress = file_encrypt(content, name, seed) if encrypted else content
        compressed = zlib.compress(to_compress, 6)
        file_entries.append({
            "name": name, "compressed_size": len(compressed),
            "decompressed_size": len(content), "crc32": crc,
            "flags": 0x01 if encrypted else 0x00
        })
        compressed_datas.append(compressed)

    file_table = bytearray()
    for entry in file_entries:
        name_bytes = entry["name"].encode('ascii')
        file_table.extend(compact_int_encode(len(name_bytes)))
        file_table.extend(name_bytes)
        file_table.extend(struct.pack('<I', entry["compressed_size"]))
        file_table.extend(struct.pack('<I', entry["decompressed_size"]))
        file_table.extend(struct.pack('<I', entry["crc32"]))
        file_table.append(entry["flags"])

    data_section = bytearray()
    for c in compressed_datas:
        data_section.extend(c)

    all_crcs_hex = "".join(f"{e['crc32']:08x}" for e in file_entries)
    verification_token = hashlib.sha256(all_crcs_hex.encode()).hexdigest()
    all_contents = b"".join(c for _, c, _ in files)
    integrity_hash = hashlib.sha256(all_contents).hexdigest()

    metadata_json = json.dumps({
        "format": "vault-archive", "version": 3, "created": "2024-03-15T08:30:00Z",
        "author": author, "entry_count": len(files),
        "verification_token": verification_token, "integrity_hash": integrity_hash,
    }).encode('utf-8')
    meta_enc = meta_encrypt(metadata_json, seed)
    metadata_section = struct.pack('<I', len(meta_enc)) + meta_enc

    header_size = 24
    data_offset = header_size + len(file_table)
    metadata_offset = data_offset + len(data_section)

    header = bytearray()
    header.extend(b'\xC0\xDE\xFA\x17')
    header.extend(struct.pack('<H', 3))
    header.extend(struct.pack('<H', 1))
    header.extend(struct.pack('<I', len(files)))
    header.extend(struct.pack('<I', data_offset))
    header.extend(struct.pack('<I', metadata_offset))
    header.extend(bytes([seed]))
    header.extend(b'\x00\x00\x00')

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(header)
        f.write(file_table)
        f.write(data_section)
        f.write(metadata_section)

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "main"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "/app/archive.vault"
    if mode == "main":
        build_vault(out_path, 0x4B, get_main_files(), "VaultMaster")
    elif mode == "test":
        build_vault(out_path, 0x37, get_test_files(), "TestGen")
