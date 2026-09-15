#!/bin/bash

pip3 install pycryptodome==3.20.0 -q

# === Step 1: Independent AES-256-ECB verification with OpenSSL ===
echo "=== OpenSSL verification of intermediate values ==="

TEST_KEY="0101010101010101010101010101010101010101010101010101010101010101"

# Compute L = AES-256-ECB(key, 0^128) using openssl
L_HEX=$(printf '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00' \
    | openssl enc -aes-256-ecb -K "$TEST_KEY" -nosalt -nopad 2>/dev/null | xxd -p -c 32)
echo "L (openssl) = $L_HEX"

# Verify against spec: expected L = 7298caa565031eadc6ce23d23ea66378
if [ "$L_HEX" = "7298caa565031eadc6ce23d23ea66378" ]; then
    echo "L matches spec Vector 1 ✓"
else
    echo "WARNING: L does not match spec"
fi

# Also verify Vector 2 key
TEST_KEY2="0303030303030303030303030303030303030303030303030303030303030303"
L2_HEX=$(printf '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00' \
    | openssl enc -aes-256-ecb -K "$TEST_KEY2" -nosalt -nopad 2>/dev/null | xxd -p -c 32)
echo "L (key2, openssl) = $L2_HEX"
echo "MSB(L2) = $(echo $L2_HEX | cut -c1) => MSB=1 (starts with 9)"

# === Step 2: Cross-check with Go binary ===
echo ""
echo "=== Go binary derive-key cross-check ==="

NONCE="4142434445464748494a4b4c4d4e4f505152535455565758"
echo "Vector 1:"
/app/implementations/beta/xaes_tool derive-key "$TEST_KEY" "$NONCE"

echo "Vector 2:"
/app/implementations/beta/xaes_tool derive-key "$TEST_KEY2" "$NONCE"

echo ""
echo "=== Go binary encrypt verification ==="
echo "Vector 1 encrypt:"
/app/implementations/beta/xaes_tool encrypt "$TEST_KEY" "$NONCE" "584145532d3235362d47434d" ""

echo "Vector 2 encrypt:"
/app/implementations/beta/xaes_tool encrypt "$TEST_KEY2" "$NONCE" "584145532d3235362d47434d" "633273702e6f72672f584145532d3235362d47434d"

# === Step 3: Run Python analysis, produce audit report, fix, and re-encrypt ===
echo ""
echo "=== Running analysis and fix ==="
python3 /solution/analyze_and_fix.py
