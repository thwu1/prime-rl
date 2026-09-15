#!/bin/bash
#
# OpenBao Transit secrets engine: complete key lifecycle setup script.
# Starts OpenBao, configures transit, creates keys, performs crypto operations,
# and writes all results to /app/results/.

set -e

export BAO_ADDR="http://127.0.0.1:8200"
export BAO_TOKEN="test-root-token"
export VAULT_ADDR="$BAO_ADDR"
export VAULT_TOKEN="$BAO_TOKEN"
export BAO_DISABLE_MLOCK=true

# Kill any existing bao processes
pkill -f "bao server" 2>/dev/null || true
sleep 2

# Start OpenBao in dev mode
bao server -dev \
    -dev-root-token-id="$BAO_TOKEN" \
    -dev-listen-address="127.0.0.1:8200" \
    > /tmp/bao.log 2>&1 &
BAO_PID=$!

# Wait for server to be ready
for i in $(seq 1 30); do
    if curl -s "$BAO_ADDR/v1/sys/health" > /dev/null 2>&1; then
        echo "OpenBao is ready (PID: $BAO_PID)"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: OpenBao failed to start within 30 seconds"
        cat /tmp/bao.log
        exit 1
    fi
    sleep 1
done

# Enable transit secrets engine
bao secrets enable transit 2>/dev/null || echo "Transit engine already enabled"

# ============================================================
# CREATE KEYS
# ============================================================

# tenant-alpha: AES-256-GCM96, exportable
bao write transit/keys/tenant-alpha type=aes256-gcm96 exportable=true > /dev/null

# tenant-beta: ECDSA P-256 for signing
bao write transit/keys/tenant-beta type=ecdsa-p256 > /dev/null

# shared-hmac: HMAC with 64-byte key
bao write transit/keys/shared-hmac type=hmac key_size=64 > /dev/null

echo "Keys created: tenant-alpha, tenant-beta, shared-hmac"

# ============================================================
# ROTATE tenant-alpha 4 times (version 1 -> 5)
# ============================================================

for i in 1 2 3 4; do
    bao write -f transit/keys/tenant-alpha/rotate > /dev/null
done
echo "tenant-alpha rotated to version 5"

# ============================================================
# ENCRYPT RECORDS at versions >= 3
# ============================================================

mkdir -p /app/results

RECORD1=$(cat /app/data/record1.txt)
RECORD2=$(cat /app/data/record2.txt)
RECORD3=$(cat /app/data/record3.txt)

R1_B64=$(echo -n "$RECORD1" | base64 -w0)
R2_B64=$(echo -n "$RECORD2" | base64 -w0)
R3_B64=$(echo -n "$RECORD3" | base64 -w0)

# Encrypt record1 at key version 3
CT1=$(bao write -format=json transit/encrypt/tenant-alpha \
    plaintext="$R1_B64" key_version=3 | jq -r '.data.ciphertext')

# Encrypt record2 at key version 4
CT2=$(bao write -format=json transit/encrypt/tenant-alpha \
    plaintext="$R2_B64" key_version=4 | jq -r '.data.ciphertext')

# Encrypt record3 at key version 5 (latest)
CT3=$(bao write -format=json transit/encrypt/tenant-alpha \
    plaintext="$R3_B64" key_version=5 | jq -r '.data.ciphertext')

echo "Records encrypted at versions 3, 4, 5"

# ============================================================
# SET VERSION CONSTRAINTS
# ============================================================

bao write transit/keys/tenant-alpha/config \
    min_decryption_version=3 \
    min_encryption_version=4 > /dev/null

echo "Version constraints set: min_decryption=3, min_encryption=4"

# ============================================================
# REWRAP all ciphertexts to latest version
# ============================================================

CT1_RW=$(bao write -format=json transit/rewrap/tenant-alpha \
    ciphertext="$CT1" | jq -r '.data.ciphertext')

CT2_RW=$(bao write -format=json transit/rewrap/tenant-alpha \
    ciphertext="$CT2" | jq -r '.data.ciphertext')

CT3_RW=$(bao write -format=json transit/rewrap/tenant-alpha \
    ciphertext="$CT3" | jq -r '.data.ciphertext')

echo "Ciphertexts rewrapped to latest version"

# Write ciphertexts to results (using jq for safe JSON construction)
jq -n \
    --arg p1 "$RECORD1" --arg c1 "$CT1_RW" \
    --arg p2 "$RECORD2" --arg c2 "$CT2_RW" \
    --arg p3 "$RECORD3" --arg c3 "$CT3_RW" \
    '[{plaintext: $p1, ciphertext: $c1},
      {plaintext: $p2, ciphertext: $c2},
      {plaintext: $p3, ciphertext: $c3}]' \
    > /app/results/ciphertexts.json

# ============================================================
# TRIM old key versions (remove versions 1 and 2)
# ============================================================

bao write transit/keys/tenant-alpha/trim min_available_version=3 > /dev/null

echo "Old key versions trimmed (min_available_version=3)"

# ============================================================
# BYOK IMPORT of external key
# ============================================================

python3 /app/byok_import.py imported-legacy /app/external_key.hex
echo "External key imported via BYOK as 'imported-legacy'"

# ============================================================
# SIGN data with tenant-beta (ECDSA-P256)
# ============================================================

SIGN_PAYLOAD=$(cat /app/data/sign_payload.txt)
SIGN_B64=$(echo -n "$SIGN_PAYLOAD" | base64 -w0)

SIGNATURE=$(bao write -format=json transit/sign/tenant-beta \
    input="$SIGN_B64" | jq -r '.data.signature')

jq -n --arg input "$SIGN_B64" --arg sig "$SIGNATURE" \
    '{input: $input, signature: $sig}' \
    > /app/results/signature.json

echo "Data signed with tenant-beta"

# ============================================================
# GENERATE HMAC with shared-hmac
# ============================================================

HMAC_DATA=$(cat /app/data/hmac_data.txt)
HMAC_B64=$(echo -n "$HMAC_DATA" | base64 -w0)

HMAC_RESULT=$(bao write -format=json transit/hmac/shared-hmac \
    input="$HMAC_B64" | jq -r '.data.hmac')

jq -n --arg hmac "$HMAC_RESULT" \
    '{hmac: $hmac}' \
    > /app/results/hmac_result.json

echo "HMAC generated with shared-hmac"

# ============================================================
# GENERATE wrapped data encryption key
# ============================================================

DK_CT=$(bao write -f -format=json transit/datakey/wrapped/tenant-alpha \
    | jq -r '.data.ciphertext')

jq -n --arg ct "$DK_CT" \
    '{ciphertext: $ct}' \
    > /app/results/datakey.json

echo "Wrapped data key generated"

# ============================================================
echo ""
echo "Setup complete. All results written to /app/results/"
echo "OpenBao is running at $BAO_ADDR (PID: $BAO_PID)"
ls -la /app/results/
