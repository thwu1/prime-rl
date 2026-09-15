#!/usr/bin/env bash
#
# Cross-validate CAVP intermediate AES-ECB steps using OpenSSL CLI.
# Verifies the CTR_DRBG Update function's AES-ECB block encryptions
# for Config 5 Count 0 (no-df, no personalization, no additional input).
#
# During instantiate, Update(seed_material, key=0, V=0) computes:
#   V = inc(0) = 00..01 -> block0 = AES-ECB(key=0, 00..01)
#   V = inc(V) = 00..02 -> block1 = AES-ECB(key=0, 00..02)
#   V = inc(V) = 00..03 -> block2 = AES-ECB(key=0, 00..03)
#   temp = block0 || block1 || block2
#   new_key || new_V = temp XOR entropy
#
# We verify each block with OpenSSL and confirm the XOR gives the
# expected Key and V from the CAVP intermediate reference file.

set -e

CHECKS_TOTAL=0
CHECKS_PASSED=0

AES_KEY_HEX="0000000000000000000000000000000000000000000000000000000000000000"

# Config 5, Count 0 entropy (48 bytes = seedlen for AES-256)
ENTROPY="df5d73faa468649edda33b5cca79b0b05600419ccb7a879ddfec9db32ee494e5531b51de16a30f769262474c73bec010"

# Expected post-instantiate state from CAVP intermediate reference
EXPECTED_KEY="8c52f901632d522774c08fad0eb2c33b98a701a1861aecf3d8a25860941709fd"
EXPECTED_V="217b52142105250243c0b2c206b8f59e"

# --- Check 1: AES-ECB block 0 (V = 00..01) ---
CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
PLAINTEXT1="00000000000000000000000000000001"
BLOCK0=$(echo -n "$PLAINTEXT1" | xxd -r -p | openssl enc -aes-256-ecb -nosalt -nopad -K "$AES_KEY_HEX" | xxd -p -c 32)

ENTROPY_0_16="${ENTROPY:0:32}"
RESULT1=$(python3 -c "
b=bytes.fromhex('$BLOCK0')
e=bytes.fromhex('$ENTROPY_0_16')
print(bytes(x^y for x,y in zip(b,e)).hex())
")
EXPECTED_KEY_0_16="${EXPECTED_KEY:0:32}"

if [ "$RESULT1" = "$EXPECTED_KEY_0_16" ]; then
    echo "PASS: Check 1 - AES-ECB(key=0, V=00..01) XOR entropy[0:16] = Key[0:16]"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    echo "FAIL: Check 1"
    echo "  Expected: $EXPECTED_KEY_0_16"
    echo "  Got:      $RESULT1"
fi

# --- Check 2: AES-ECB block 1 (V = 00..02) ---
CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
PLAINTEXT2="00000000000000000000000000000002"
BLOCK1=$(echo -n "$PLAINTEXT2" | xxd -r -p | openssl enc -aes-256-ecb -nosalt -nopad -K "$AES_KEY_HEX" | xxd -p -c 32)

ENTROPY_16_32="${ENTROPY:32:32}"
RESULT2=$(python3 -c "
b=bytes.fromhex('$BLOCK1')
e=bytes.fromhex('$ENTROPY_16_32')
print(bytes(x^y for x,y in zip(b,e)).hex())
")
EXPECTED_KEY_16_32="${EXPECTED_KEY:32:32}"

if [ "$RESULT2" = "$EXPECTED_KEY_16_32" ]; then
    echo "PASS: Check 2 - AES-ECB(key=0, V=00..02) XOR entropy[16:32] = Key[16:32]"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    echo "FAIL: Check 2"
    echo "  Expected: $EXPECTED_KEY_16_32"
    echo "  Got:      $RESULT2"
fi

# --- Check 3: AES-ECB block 2 (V = 00..03) -> V portion ---
CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
PLAINTEXT3="00000000000000000000000000000003"
BLOCK2=$(echo -n "$PLAINTEXT3" | xxd -r -p | openssl enc -aes-256-ecb -nosalt -nopad -K "$AES_KEY_HEX" | xxd -p -c 32)

ENTROPY_32_48="${ENTROPY:64:32}"
RESULT3=$(python3 -c "
b=bytes.fromhex('$BLOCK2')
e=bytes.fromhex('$ENTROPY_32_48')
print(bytes(x^y for x,y in zip(b,e)).hex())
")

if [ "$RESULT3" = "$EXPECTED_V" ]; then
    echo "PASS: Check 3 - AES-ECB(key=0, V=00..03) XOR entropy[32:48] = V"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    echo "FAIL: Check 3"
    echo "  Expected: $EXPECTED_V"
    echo "  Got:      $RESULT3"
fi

echo ""
echo "Cross-validation: $CHECKS_PASSED/$CHECKS_TOTAL checks passed"

# Write results for the audit report
python3 -c "
import json
result = {
    'checks': [
        {'name': 'Update block 0 (Key[0:16])', 'passed': '$RESULT1' == '$EXPECTED_KEY_0_16'},
        {'name': 'Update block 1 (Key[16:32])', 'passed': '$RESULT2' == '$EXPECTED_KEY_16_32'},
        {'name': 'Update block 2 (V)', 'passed': '$RESULT3' == '$EXPECTED_V'},
    ],
    'total': $CHECKS_TOTAL,
    'passed': $CHECKS_PASSED
}
with open('/app/cross_validation_results.json', 'w') as f:
    json.dump(result, f, indent=2)
"

if [ $CHECKS_PASSED -eq $CHECKS_TOTAL ]; then
    exit 0
else
    exit 1
fi
