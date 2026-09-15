#!/usr/bin/env bash

# Deploy the forensics tool
cp /solution/flash_forensics.py /app/flash_forensics.py

# Reconstruct partition tables from all flash dumps
mkdir -p /app/reconstructed

for dump in flash_simple flash_ota flash_complex; do
    python3 /app/flash_forensics.py reconstruct \
        "/app/dumps/${dump}.bin" \
        "/app/reconstructed/${dump}_pt.bin"
done

# Validate all reconstructed tables with gen_esp32part.py
echo "Validating reconstructed partition tables..."
all_valid=true
for dump in flash_simple flash_ota flash_complex; do
    if python3 /app/tools/gen_esp32part.py --quiet "/app/reconstructed/${dump}_pt.bin" > /dev/null 2>&1; then
        echo "  ${dump}: VALID"
        python3 /app/tools/gen_esp32part.py --quiet "/app/reconstructed/${dump}_pt.bin"
    else
        echo "  ${dump}: INVALID"
        all_valid=false
    fi
done

if $all_valid; then
    echo "All reconstructed partition tables pass validation."
else
    echo "Some tables failed validation."
    exit 1
fi
