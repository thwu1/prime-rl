#!/bin/bash

set -e

# Install solution dependencies
pip3 install pynacl==1.5.0 -q

# === Fix Bug 1: Salsa20 core rotation constant (14 -> 13) ===
# The Salsa20 quarter-round spec uses rotations 7, 9, 13, 18.
# The broken code has 14 instead of 13.
sed -i 's/L32(t\[2\]+t\[1\],14)/L32(t[2]+t[1],13)/' /app/tweetnacl.c

# === Fix Bug 2: Sigma constant ('K' -> 'k') ===
# The Salsa20/HSalsa20 spec uses "expand 32-byte k" (lowercase k).
# The broken code has uppercase 'K'.
sed -i 's/expand 32-byte K/expand 32-byte k/' /app/tweetnacl.c

# === Fix Bug 3: Poly1305 key clamping (r[11]&=63 -> r[11]&=15) ===
# Poly1305 spec requires r[3], r[7], r[11], r[15] to have top 4 bits clear (mask 0x0f=15).
# The broken code uses 63 (0x3f) for r[11], allowing 2 extra bits.
sed -i 's/r\[11\]&=63;/r[11]\&=15;/' /app/tweetnacl.c

# === Fix Bug 4: inv25519 exponent (a!=3 -> a!=4) ===
# Field inversion computes x^(p-2) where p=2^255-19.
# p-2 = 2^255-21 = binary ...1101011 (bits 2 and 4 are zero).
# The broken code skips bit 3 instead of bit 4.
sed -i 's/if(a!=2&&a!=3)/if(a!=2\&\&a!=4)/' /app/tweetnacl.c

# === Decrypt the challenge using PyNaCl ===
python3 /solution/decrypt_challenge.py

# === Create and compile the forgery proof-of-concept ===
cp /solution/forgery_poc.c /app/forgery_poc.c
cd /app && gcc -o forgery_poc forgery_poc.c tweetnacl.c -O2
echo "=== Forgery PoC output ==="
./forgery_poc

# === Generate the vulnerability assessment bug report ===
python3 /solution/generate_report.py
