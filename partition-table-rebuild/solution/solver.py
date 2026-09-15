#!/usr/bin/env python3
"""
Solver for ESP32 partition table pipeline recovery.

1. Fix two regressions in gen_esp32part.py
2. Extract and decode the reference partition table from the flash dump
3. Compute optimal layouts for each target configuration
4. Generate validated binaries using the fixed tool
"""
import math
import os
import subprocess
import sys

GEN_TOOL = '/app/tools/gen_esp32part.py'
OUTPUT_DIR = '/app/output'
FLASH_IMG = '/app/legacy_flash.img'
PT_OFFSET_IN_FLASH = 0x8000
PT_DATA_SIZE = 0xC00  # MAX_PARTITION_LENGTH

# Fixed partition sizes from spec
NVS_SIZE = 0x4000
OTADATA_SIZE = 0x2000
PHY_SIZE = 0x1000
FACTORY_SIZE = 0x100000
COREDUMP_SIZE = 0x10000
NVS_KEYS_SIZE = 0x1000
TELEMETRY_SIZE = 0x4000

TAIL_SIZE = COREDUMP_SIZE + NVS_KEYS_SIZE + TELEMETRY_SIZE  # 0x15000

# Target configurations (derived from spec + tool source code analysis)
CONFIGS = {
    'config_a': {
        'flash_bytes': 0x400000,
        'pt_offset': 0x8000,
        'secure': None,
        'app_size_align': 0x1000,  # no secure boot: 4KB app size alignment
        'gen_flags': ['--flash-size', '4MB'],
    },
    'config_b': {
        'flash_bytes': 0x400000,
        'pt_offset': 0x8000,
        'secure': 'v1',
        'app_size_align': 0x10000,  # secure boot v1: 64KB app size alignment
        'gen_flags': ['--secure', 'v1', '--flash-size', '4MB'],
    },
    'config_c': {
        'flash_bytes': 0x1000000,
        'pt_offset': 0x10000,
        'secure': 'v2',
        'app_size_align': 0x1000,  # secure boot v2: 4KB app size alignment
        'gen_flags': ['--secure', 'v2', '--flash-size', '16MB', '--offset', '0x10000'],
    },
}


# ===== Step 1: Fix gen_esp32part.py regressions =====

def fix_tool():
    """Fix two regressions introduced during refactor:
    1. PARTITION_TABLE_SIZE doubled from 0x1000 to 0x2000 — the partition table
       occupies exactly one 4KB flash sector, not two.
    2. Overlap check uses <= instead of < — adjacent partitions where one ends
       exactly where the next begins are valid, not overlapping.
    """
    with open(GEN_TOOL, 'r') as f:
        source = f.read()

    # Fix 1: Restore correct partition table size (one 4KB sector)
    source = source.replace(
        'PARTITION_TABLE_SIZE = 0x2000  # Size of partition table',
        'PARTITION_TABLE_SIZE = 0x1000  # Size of partition table'
    )

    # Fix 2: Restore correct overlap check (strictly less than, not <=)
    source = source.replace(
        'if last is not None and p.offset <= last.offset + last.size:',
        'if last is not None and p.offset < last.offset + last.size:'
    )

    with open(GEN_TOOL, 'w') as f:
        f.write(source)
    print("Fixed gen_esp32part.py regressions")


# ===== Step 2: Extract and decode reference PT from flash dump =====

def extract_reference():
    """Extract the partition table binary from the legacy flash dump and decode it."""
    with open(FLASH_IMG, 'rb') as f:
        f.seek(PT_OFFSET_IN_FLASH)
        pt_data = f.read(PT_DATA_SIZE)

    ref_bin = '/tmp/extracted_pt.bin'
    with open(ref_bin, 'wb') as f:
        f.write(pt_data)

    # Decode to CSV using the fixed tool
    result = subprocess.run(
        [sys.executable, GEN_TOOL, '-q', ref_bin, '/tmp/reference.csv'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Warning: Could not decode reference: {result.stderr}", file=sys.stderr)

    print("Reference PT extracted from flash dump and decoded:")
    if os.path.exists('/tmp/reference.csv'):
        with open('/tmp/reference.csv', 'r') as f:
            print(f.read())

    os.unlink(ref_bin)


# ===== Step 3: Compute optimal partition layouts =====

def maximize_ota(ota_start, flash_size, tail_size, app_size_align):
    """Find the maximum equal OTA slot size X.

    OTA_0 starts at ota_start (64KB aligned).
    OTA_1 starts at the next 64KB boundary after OTA_0 ends.
    X must be a multiple of app_size_align.
    OTA_1 end + tail_size must fit within flash_size.
    """
    max_x = (flash_size - ota_start - tail_size) // 2
    max_x = (max_x // app_size_align) * app_size_align

    for x in range(max_x, 0, -app_size_align):
        ota0_end = ota_start + x
        if ota0_end % 0x10000 == 0:
            ota1_start = ota0_end
        else:
            ota1_start = ((ota0_end // 0x10000) + 1) * 0x10000
        ota1_end = ota1_start + x
        if ota1_end + tail_size <= flash_size:
            return x

    raise ValueError("Cannot fit OTA slots in available flash")


def compute_layout(cfg):
    """Compute full partition layout for a configuration."""
    pt_offset = cfg['pt_offset']
    pt_size = 0x1000  # partition table is exactly one 4KB sector
    first_available = pt_offset + pt_size

    entries = []
    cursor = first_available

    # Data partitions (4KB offset alignment)
    entries.append(('nvs', 'data', 'nvs', cursor, NVS_SIZE, ''))
    cursor += NVS_SIZE

    entries.append(('otadata', 'data', 'ota', cursor, OTADATA_SIZE, ''))
    cursor += OTADATA_SIZE

    entries.append(('phy_init', 'data', 'phy', cursor, PHY_SIZE, ''))
    cursor += PHY_SIZE

    # Factory app (64KB offset alignment — from tool's ALIGNMENT dict)
    factory_offset = math.ceil(cursor / 0x10000) * 0x10000
    entries.append(('factory', 'app', 'factory', factory_offset, FACTORY_SIZE, ''))
    cursor = factory_offset + FACTORY_SIZE

    # OTA slots (64KB offset alignment, size alignment per secure boot mode)
    ota_start = cursor
    assert ota_start % 0x10000 == 0, "OTA start must be 64KB aligned"

    ota_size = maximize_ota(ota_start, cfg['flash_bytes'], TAIL_SIZE, cfg['app_size_align'])

    ota0_offset = ota_start
    entries.append(('ota_0', 'app', 'ota_0', ota0_offset, ota_size, ''))

    ota0_end = ota0_offset + ota_size
    if ota0_end % 0x10000 == 0:
        ota1_offset = ota0_end
    else:
        ota1_offset = ((ota0_end // 0x10000) + 1) * 0x10000
    entries.append(('ota_1', 'app', 'ota_1', ota1_offset, ota_size, ''))
    cursor = ota1_offset + ota_size

    # Tail partitions (data, 4KB alignment)
    entries.append(('coredump', 'data', 'coredump', cursor, COREDUMP_SIZE, ''))
    cursor += COREDUMP_SIZE

    entries.append(('nvs_keys', 'data', 'nvs_keys', cursor, NVS_KEYS_SIZE, 'encrypted'))
    cursor += NVS_KEYS_SIZE

    entries.append(('telemetry', 'data', '0xFE', cursor, TELEMETRY_SIZE, ''))
    cursor += TELEMETRY_SIZE

    assert cursor <= cfg['flash_bytes'], (
        f"Layout exceeds flash: 0x{cursor:x} > 0x{cfg['flash_bytes']:x}"
    )

    return entries, ota_size


# ===== Step 4: Generate partition table binaries =====

def write_csv(entries, csv_path):
    """Write a partition table CSV file."""
    lines = [
        '# ESP-IDF Partition Table',
        '# Name, Type, SubType, Offset, Size, Flags',
    ]
    for name, ptype, subtype, offset, size, flags in entries:
        line = f'{name},{ptype},{subtype},0x{offset:x},0x{size:x},{flags}'
        lines.append(line)
    with open(csv_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def generate_binary(csv_path, bin_path, flags):
    """Run gen_esp32part.py to convert CSV to validated binary."""
    cmd = [sys.executable, GEN_TOOL, '-q'] + flags + [csv_path, bin_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: gen_esp32part.py failed for {csv_path}:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)


def main():
    # Step 1: Fix the tool
    fix_tool()

    # Step 2: Extract and analyze reference
    extract_reference()

    # Step 3 & 4: Compute layouts and generate binaries
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for config_name, cfg in CONFIGS.items():
        print(f"\n=== {config_name} ===")
        print(f"  Flash: {cfg['flash_bytes'] // (1024*1024)} MB")
        print(f"  Secure boot: {cfg['secure'] or 'none'}")
        print(f"  PT offset: 0x{cfg['pt_offset']:x}")
        print(f"  App size align: 0x{cfg['app_size_align']:x}")

        entries, ota_size = compute_layout(cfg)

        print(f"  OTA slot size: 0x{ota_size:x} ({ota_size // 1024} KB)")
        print(f"  Layout:")
        for name, ptype, subtype, offset, size, flags in entries:
            flag_str = f' [{flags}]' if flags else ''
            print(f"    {name:12s} {ptype:4s}/{subtype:8s} "
                  f"0x{offset:06x}  0x{size:06x}{flag_str}")

        csv_path = os.path.join(OUTPUT_DIR, f'{config_name}.csv')
        bin_path = os.path.join(OUTPUT_DIR, f'{config_name}.bin')

        write_csv(entries, csv_path)
        generate_binary(csv_path, bin_path, cfg['gen_flags'])

        print(f"  -> {bin_path} ({os.path.getsize(bin_path)} bytes)")

    print("\nAll configurations generated successfully.")


if __name__ == '__main__':
    main()
