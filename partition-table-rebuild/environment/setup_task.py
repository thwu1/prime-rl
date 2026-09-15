#!/usr/bin/env python3
"""Set up the task environment: flash image with embedded PT, buggy tool, spec."""
import os
import subprocess
import sys

FLASH_SIZE = 0x400000  # 4MB
PT_OFFSET = 0x8000
CLEAN_TOOL = '/tmp/gen_esp32part_clean.py'
BUGGY_TOOL = '/app/tools/gen_esp32part.py'

os.makedirs('/app/tools', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)

# ---------- Step 1: Generate reference partition table using the clean tool ----------

ref_csv = """\
# Legacy production partition table
# Name,   Type, SubType,  Offset,    Size,     Flags
nvs,       data, nvs,      0x9000,    0x6000,
otadata,   data, ota,      0xf000,    0x2000,
phy_init,  data, phy,      0x11000,   0x1000,
factory,   app,  factory,  0x20000,   0x100000,
ota_0,     app,  ota_0,    0x120000,  0x160000,
ota_1,     app,  ota_1,    0x280000,  0x160000,
coredump,  data, coredump, 0x3e0000,  0x10000,
"""

with open('/tmp/reference.csv', 'w') as f:
    f.write(ref_csv)

result = subprocess.run(
    [sys.executable, CLEAN_TOOL, '-q', '--flash-size', '4MB',
     '/tmp/reference.csv', '/tmp/reference.bin'],
    capture_output=True, text=True
)
if result.returncode != 0:
    print("Error generating reference: " + result.stderr, file=sys.stderr)
    sys.exit(1)

# ---------- Step 2: Embed PT in a 4MB flash image ----------

flash_img = bytearray(b'\xff' * FLASH_SIZE)
with open('/tmp/reference.bin', 'rb') as f:
    pt_data = f.read()
flash_img[PT_OFFSET:PT_OFFSET + len(pt_data)] = pt_data

with open('/app/legacy_flash.img', 'wb') as f:
    f.write(flash_img)

# ---------- Step 3: Inject regressions into gen_esp32part.py ----------

with open(CLEAN_TOOL, 'r') as f:
    source = f.read()

# Regression 1: PARTITION_TABLE_SIZE doubled (0x1000 -> 0x2000)
# This shifts the "first valid partition offset" up by one sector,
# causing the tool to reject partitions in the sector immediately
# after the partition table.
source = source.replace(
    'PARTITION_TABLE_SIZE = 0x1000  # Size of partition table',
    'PARTITION_TABLE_SIZE = 0x2000  # Size of partition table'
)

# Regression 2: Overlap check off-by-one (< -> <=)
# This causes the tool to reject adjacent (non-overlapping) partitions
# where one partition ends exactly where the next begins.
source = source.replace(
    'if last is not None and p.offset < last.offset + last.size:',
    'if last is not None and p.offset <= last.offset + last.size:'
)

with open(BUGGY_TOOL, 'w') as f:
    f.write(source)
os.chmod(BUGGY_TOOL, 0o755)

# ---------- Step 4: Write migration specification ----------

spec_content = """\
# ESP32 Partition Table Migration Specification
#
# The legacy product's partition table can be found in the flash dump
# at /app/legacy_flash.img. Use /app/tools/gen_esp32part.py to work
# with partition table binaries and CSVs.
#
# Produce validated partition table binaries for each target configuration.
# Output binaries must pass gen_esp32part.py validation with the flags
# listed in each configuration's gen_flags field.

[common]
# All configurations share these partitions in this exact order.
partition_names = [
    "nvs",        # NVS key-value store (data, nvs)
    "otadata",    # OTA selection data (data, ota)
    "phy_init",   # PHY calibration data (data, phy)
    "factory",    # Factory application (app, factory)
    "ota_0",      # OTA slot 0 (app, ota_0)
    "ota_1",      # OTA slot 1 (app, ota_1)
    "coredump",   # Core dump storage (data, coredump)
    "nvs_keys",   # NVS encryption keys (data, nvs_keys) - must be flagged 'encrypted'
    "telemetry",  # Device telemetry (data, custom subtype 0xFE)
]

[common.fixed_sizes]
nvs       = "0x4000"
otadata   = "0x2000"
phy_init  = "0x1000"
factory   = "0x100000"
coredump  = "0x10000"
nvs_keys  = "0x1000"
telemetry = "0x4000"

[common.ota_requirements]
# OTA application slots must be:
# - Equal in size
# - As large as possible given the remaining flash space after placing
#   all other partitions, subject to the alignment constraints that
#   gen_esp32part.py enforces for the configuration's secure boot mode
# Consult the tool's source code for alignment rules.

# === Target Configurations ===

[config_a]
flash_size_mb    = 4
secure_boot      = "none"
pt_offset        = "0x8000"
gen_flags        = "--flash-size 4MB"

[config_b]
flash_size_mb    = 4
secure_boot      = "v1"
pt_offset        = "0x8000"
gen_flags        = "--secure v1 --flash-size 4MB"

[config_c]
flash_size_mb    = 16
secure_boot      = "v2"
pt_offset        = "0x10000"
gen_flags        = "--secure v2 --flash-size 16MB --offset 0x10000"
"""

with open('/app/spec.toml', 'w') as f:
    f.write(spec_content)

# ---------- Cleanup ----------

os.remove('/tmp/reference.csv')
os.remove('/tmp/reference.bin')

print("Task environment generated:")
print("  /app/legacy_flash.img  (4MB flash dump, PT at offset 0x8000)")
print("  /app/tools/gen_esp32part.py  (contains regressions)")
print("  /app/spec.toml")
print("  /app/output/  (empty)")
