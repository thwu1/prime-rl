#!/bin/bash
#
# Verifies a PDDB export file's HMAC tags using openssl dgst.
# Usage: verify_export.sh <export_file> <password>
#
# Python is used ONLY for JSON parsing. All HMAC computation
# is performed by openssl dgst -sha256 -hmac.

EXPORT_FILE="$1"
PASSWORD="$2"

if [ -z "$EXPORT_FILE" ] || [ -z "$PASSWORD" ]; then
    echo "Usage: $0 <export_file> <password>"
    exit 1
fi

# Extract salt (python3 for JSON parsing only)
SALT=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['salt'])" "$EXPORT_FILE")

# Derive HMAC key using openssl
HMAC_KEY=$(printf '%s' "${SALT}:export-hmac-key" | openssl dgst -sha256 -hmac "$PASSWORD" | sed 's/^.*= //')

# Get entry count
COUNT=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['entries']))" "$EXPORT_FILE")

if [ "$COUNT" -eq 0 ]; then
    echo "ALL_VERIFIED"
    exit 0
fi

ALL_OK=true

# Extract all entry data via python3 (JSON parsing only), pipe-delimited
while IFS='|' read -r DICT KEY DATA_B64 EXPECTED_HMAC; do
    MSG="${DICT}:${KEY}:${DATA_B64}"
    COMPUTED=$(printf '%s' "$MSG" | openssl dgst -sha256 -hmac "$HMAC_KEY" | sed 's/^.*= //')

    if [ "$COMPUTED" = "$EXPECTED_HMAC" ]; then
        echo "VERIFIED: ${DICT}/${KEY}"
    else
        echo "FAILED: ${DICT}/${KEY}"
        ALL_OK=false
    fi
done < <(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
for e in d['entries']:
    print(f\"{e['dictionary']}|{e['key']}|{e['data_b64']}|{e['hmac']}\")
" "$EXPORT_FILE")

if [ "$ALL_OK" = true ]; then
    echo "ALL_VERIFIED"
    exit 0
else
    echo "VERIFICATION_FAILED"
    exit 1
fi
