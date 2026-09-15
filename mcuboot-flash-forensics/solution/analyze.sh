#!/bin/bash
set -e

# Step 1: Parse partition layout from Partition Manager YAML config
eval $(python3 /app/parse_pm.py)
echo "Partition layout: primary=$PRIMARY_OFFSET/$PRIMARY_SIZE secondary=$SECONDARY_OFFSET/$SECONDARY_SIZE"

# Step 2: Extract image slots using dd
mkdir -p /app/extracted
dd if=/app/flash_dump.bin bs=1 skip=$PRIMARY_OFFSET count=$PRIMARY_SIZE of=/app/extracted/primary.bin 2>/dev/null
dd if=/app/flash_dump.bin bs=1 skip=$SECONDARY_OFFSET count=$SECONDARY_SIZE of=/app/extracted/secondary.bin 2>/dev/null
echo "Extracted primary.bin ($(stat -c%s /app/extracted/primary.bin) bytes)"
echo "Extracted secondary.bin ($(stat -c%s /app/extracted/secondary.bin) bytes)"

# Step 3: Compute independent SHA256 checksums via openssl
openssl dgst -sha256 /app/extracted/primary.bin /app/extracted/secondary.bin > /app/extracted/checksums.txt
echo "OpenSSL checksums:"
cat /app/extracted/checksums.txt

# Step 4: Examine headers with xxd for diagnostic context
echo "=== Primary slot header (first 32 bytes) ===" > /app/extracted/header_dump.txt
xxd -l 32 /app/extracted/primary.bin >> /app/extracted/header_dump.txt
echo "" >> /app/extracted/header_dump.txt
echo "=== Secondary slot header (first 32 bytes) ===" >> /app/extracted/header_dump.txt
xxd -l 32 /app/extracted/secondary.bin >> /app/extracted/header_dump.txt

# Step 5: Run detailed forensic analysis with parsed partition offsets
python3 /app/forensic_analyzer.py \
    --primary-offset $PRIMARY_OFFSET \
    --primary-size $PRIMARY_SIZE \
    --secondary-offset $SECONDARY_OFFSET \
    --secondary-size $SECONDARY_SIZE

echo "Analysis complete. Report written to /app/report.json"
