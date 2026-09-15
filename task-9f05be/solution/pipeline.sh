#!/bin/bash

set -e

# Step 1: Run the Python anonymization engine
python3 /app/anonymize.py

# Step 2: Validate NDJSON output with jq
echo "Validating NDJSON..."
INPUT_LINES=$(wc -l < /app/input/export.ndjson)
OUTPUT_LINES=$(wc -l < /app/output/export.ndjson)
if [ "$INPUT_LINES" -ne "$OUTPUT_LINES" ]; then
    echo "ERROR: NDJSON line count mismatch: input=$INPUT_LINES output=$OUTPUT_LINES"
    exit 1
fi
# Validate each line is valid JSON with resourceType
jq -e '.resourceType' /app/output/export.ndjson > /dev/null 2>&1
echo "NDJSON structure valid: $OUTPUT_LINES resources"

# Step 3: Generate crypto verification manifest using openssl
CRYPTO_KEY=$(jq -r '.parameters.cryptoHashKey' /app/config.json)

# Build manifest by iterating tracking data and verifying with openssl
python3 -c "
import json, subprocess, sys

tracking = json.load(open('/app/output/.tracking.json'))
verifications = []

crypto_key = '${CRYPTO_KEY}'

for entry in tracking:
    orig_id = entry['original_id']
    result = subprocess.run(
        ['openssl', 'dgst', '-sha256', '-hmac', crypto_key],
        input=orig_id.encode(),
        capture_output=True
    )
    openssl_hash = result.stdout.decode().strip().split('= ')[-1]
    verifications.append({
        'source_file': entry['source_file'],
        'resource_type': entry['resource_type'],
        'original_id': orig_id,
        'hashed_id': entry['hashed_id'],
        'openssl_output': openssl_hash,
        'verified': openssl_hash == entry['hashed_id']
    })

manifest = {'verifications': verifications}
with open('/app/output/crypto_manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)

verified_count = sum(1 for v in verifications if v['verified'])
print(f'Manifest: {verified_count}/{len(verifications)} verified')
"

echo "Pipeline complete"
