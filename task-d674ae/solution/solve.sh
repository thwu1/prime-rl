#!/bin/bash

set -e

# ---- Step 1: Build and analyse original firmware ----
cd /app
make -C firmware clean
make -C firmware
arm-none-eabi-objdump -d firmware/keyfob.elf > firmware/keyfob.dis

# ---- Step 2: Run automated audit & generate fixes ----
python3 /solution/audit_and_fix.py

# ---- Step 3: Build and verify fixed firmware ----
make -C firmware_fixed clean
make -C firmware_fixed

# Confirm verify_pin no longer branches to memcmp
arm-none-eabi-objdump -d firmware_fixed/keyfob.elf > firmware_fixed/keyfob.dis
if grep -A 200 '<verify_pin>:' firmware_fixed/keyfob.dis | grep -q 'memcmp'; then
    echo "ERROR: fixed verify_pin still calls memcmp"
    exit 1
fi

echo "Audit and fix complete – all checks passed."
