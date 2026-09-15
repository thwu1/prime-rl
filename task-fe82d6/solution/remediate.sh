#!/bin/bash
#
# Remediation script for Transit secrets engine compliance violations.
# Assumes OpenBao is running with the initial (non-compliant) state loaded.

set -e

export BAO_ADDR="http://127.0.0.1:8200"
export BAO_TOKEN="test-root-token"
export VAULT_ADDR="$BAO_ADDR"
export VAULT_TOKEN="$BAO_TOKEN"

# Install dependencies for BYOK import
pip3 install cryptography==42.0.5 requests==2.31.0 -q

# ============================================================
# REMEDIATE primary-enc: exportability, rotation, constraints
# ============================================================

# Enable exportable (policy section 3: disaster recovery)
bao write transit/keys/primary-enc/config exportable=true > /dev/null

# Rotate to version 5 (policy section 1: minimum 5 versions)
for i in 1 2 3 4; do
    bao write -f transit/keys/primary-enc/rotate > /dev/null
done
echo "primary-enc rotated to version 5"

# ============================================================
# ENCRYPT records at current (latest) version
# ============================================================

mkdir -p /app/results

RECORD1=$(cat /app/data/record1.txt)
RECORD2=$(cat /app/data/record2.txt)
RECORD3=$(cat /app/data/record3.txt)

R1_B64=$(echo -n "$RECORD1" | base64 -w0)
R2_B64=$(echo -n "$RECORD2" | base64 -w0)
R3_B64=$(echo -n "$RECORD3" | base64 -w0)

CT1=$(bao write -format=json transit/encrypt/primary-enc \
    plaintext="$R1_B64" | jq -r '.data.ciphertext')

CT2=$(bao write -format=json transit/encrypt/primary-enc \
    plaintext="$R2_B64" | jq -r '.data.ciphertext')

CT3=$(bao write -format=json transit/encrypt/primary-enc \
    plaintext="$R3_B64" | jq -r '.data.ciphertext')

jq -n \
    --arg p1 "$RECORD1" --arg c1 "$CT1" \
    --arg p2 "$RECORD2" --arg c2 "$CT2" \
    --arg p3 "$RECORD3" --arg c3 "$CT3" \
    '[{plaintext: $p1, ciphertext: $c1},
      {plaintext: $p2, ciphertext: $c2},
      {plaintext: $p3, ciphertext: $c3}]' \
    > /app/results/ciphertexts.json

echo "Records encrypted at latest version"

# ============================================================
# SET VERSION CONSTRAINTS (policy section 2: rolling window)
# Latest=5, window=3 → min_decryption=3, min_encryption=5
# ============================================================

bao write transit/keys/primary-enc/config \
    min_decryption_version=3 \
    min_encryption_version=5 > /dev/null

echo "Version constraints set"

# ============================================================
# TRIM deprecated key versions (policy section 5)
# ============================================================

bao write transit/keys/primary-enc/trim min_available_version=3 > /dev/null

echo "Old key versions trimmed"

# ============================================================
# PROVISION auth-hmac key (policy section 6)
# ============================================================

bao write transit/keys/auth-hmac type=hmac key_size=64 > /dev/null

echo "auth-hmac key created with 64-byte key"

# ============================================================
# HMAC evidence
# ============================================================

HMAC_DATA=$(cat /app/data/hmac_data.txt)
HMAC_B64=$(echo -n "$HMAC_DATA" | base64 -w0)

HMAC_RESULT=$(bao write -format=json transit/hmac/auth-hmac \
    input="$HMAC_B64" | jq -r '.data.hmac')

jq -n --arg hmac "$HMAC_RESULT" \
    '{hmac: $hmac}' \
    > /app/results/hmac_result.json

echo "HMAC evidence produced"

# ============================================================
# BYOK IMPORT of external legacy key (policy section 7)
# ============================================================

python3 /app/byok_import.py imported-legacy /app/external_key.hex

echo "External key imported via BYOK"

# Export imported key for verification evidence
EXPORTED_B64=$(bao read -format=json transit/export/encryption-key/imported-legacy \
    | jq -r '.data.keys["1"]')
EXPORTED_HEX=$(python3 -c "import base64; print(base64.b64decode('$EXPORTED_B64').hex())")

jq -n --arg hex "$EXPORTED_HEX" \
    '{exported_hex: $hex}' \
    > /app/results/imported_key_verification.json

echo "Import verification evidence produced"

# ============================================================
# DIGITAL SIGNATURE evidence (policy section 8)
# ============================================================

SIGN_PAYLOAD=$(cat /app/data/sign_payload.txt)
SIGN_B64=$(echo -n "$SIGN_PAYLOAD" | base64 -w0)

SIGNATURE=$(bao write -format=json transit/sign/tenant-sign \
    input="$SIGN_B64" | jq -r '.data.signature')

jq -n --arg input "$SIGN_B64" --arg sig "$SIGNATURE" \
    '{input: $input, signature: $sig}' \
    > /app/results/signature.json

echo "Signature evidence produced"

# ============================================================
# DATA ENCRYPTION KEY (policy section 9)
# ============================================================

DK_CT=$(bao write -f -format=json transit/datakey/wrapped/primary-enc \
    | jq -r '.data.ciphertext')

jq -n --arg ct "$DK_CT" \
    '{ciphertext: $ct}' \
    > /app/results/datakey.json

echo "Wrapped data key evidence produced"

echo ""
echo "Remediation complete. All evidence artifacts in /app/results/"
ls -la /app/results/
