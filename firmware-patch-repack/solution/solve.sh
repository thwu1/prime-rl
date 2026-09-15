#!/bin/bash

set -e
cd /app

# Unpack FWPK container into sections
python3 /solution/unpack_fwpk.py /app/firmware.bin /tmp/work

# Decompress payload section (GZIP -> CPIO)
gunzip -c /tmp/work/sections/payload > /tmp/work/firmware.cpio

# Extract CPIO filesystem
mkdir -p /tmp/work/root
cd /tmp/work/root
cpio -id --no-absolute-filenames < /tmp/work/firmware.cpio 2>/dev/null

# Patch gateway binary SECCFG security configuration
python3 /solution/patch_seccfg.py /tmp/work/root/usr/bin/gateway

# Decrypt config, harden, re-encrypt
python3 /solution/config_crypto.py \
    /tmp/work/sections/config.enc \
    /tmp/work/sections/meta \
    /tmp/work/sections/config.enc.new \
    /tmp/work/config_plain.txt

# Modify SquashFS: disable remote debug
unsquashfs -d /tmp/work/sqfs_out /tmp/work/root/opt/modules.sqfs
sed -i 's/REMOTE_DEBUG_ENABLED = True/REMOTE_DEBUG_ENABLED = False/' \
    /tmp/work/sqfs_out/scripts/diag.py
rm /tmp/work/root/opt/modules.sqfs
mksquashfs /tmp/work/sqfs_out /tmp/work/root/opt/modules.sqfs -noappend -comp gzip

# Update firmware version in filesystem
echo "2.0.0" > /tmp/work/root/var/firmware_version

# Create integrity manifest
python3 /solution/create_manifest.py /tmp/work/root /tmp/work/config_plain.txt

# Update firmware version in metadata section
python3 -c '
import json
with open("/tmp/work/sections/meta", "r") as f:
    meta = json.load(f)
meta["firmware_version"] = "2.0.0"
with open("/tmp/work/sections/meta.new", "w") as f:
    json.dump(meta, f, indent=2)
'

# Repack CPIO (newc format, sorted for determinism)
cd /tmp/work/root
find . -print | sort | cpio -o -H newc > /tmp/work/firmware_new.cpio 2>/dev/null

# GZIP compress
gzip -c /tmp/work/firmware_new.cpio > /tmp/work/payload_new.gz

# Rebuild FWPK container with updated sections and integrity chain
python3 /solution/repack_fwpk.py \
    /tmp/work/sections/meta.new \
    /tmp/work/payload_new.gz \
    /tmp/work/sections/config.enc.new \
    /tmp/work/sections/hmac.key \
    /app/firmware_patched.bin

echo "Firmware remediation complete: /app/firmware_patched.bin"
