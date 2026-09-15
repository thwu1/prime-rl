
"""
Fix the three bugs in /app/tweetnacl.c.

Bug 1 (Salsa20 core): The first rotation constant in the quarter-round
was changed from 7 to 6. The Salsa20 specification (DJB, "The Salsa20
family of stream ciphers") defines the quarter-round as:
    b ^= (a+d) <<< 7
    c ^= (b+a) <<< 9
    d ^= (c+b) <<< 13
    a ^= (d+c) <<< 18
The value 6 is wrong; it must be 7.

Bug 2 (Poly1305 clamping): The clamping mask for r[4] was changed from
252 (0xFC) to 248 (0xF8). Per the Poly1305 specification, certain bits
of the r key must be cleared. For bytes at positions 4, 8, 12, the
bottom two bits must be cleared, giving a mask of 252 (binary 11111100).
The value 248 (binary 11111000) clears an extra bit incorrectly.

Bug 3 (SHA-512 IV): The first byte of the SHA-512 initialization vector
was changed from 0x6a to 0x6b. The correct SHA-512 IV (FIPS 180-4)
starts with H0 = 6a09e667f3bcc908, so the first byte in big-endian
storage is 0x6a, not 0x6b.
"""

import sys

with open('/app/tweetnacl.c', 'r') as f:
    src = f.read()

original = src

# Bug 1: Salsa20 core rotation constant 6 -> 7
src = src.replace('L32(t[0]+t[3], 6)', 'L32(t[0]+t[3], 7)', 1)

# Bug 2: Poly1305 clamping mask 248 -> 252
src = src.replace('r[4]&=248', 'r[4]&=252', 1)

# Bug 3: SHA-512 IV first byte 0x6b -> 0x6a
src = src.replace('0x6b,0x09,0xe6,0x67', '0x6a,0x09,0xe6,0x67', 1)

if src == original:
    print("WARNING: No changes were made. Bugs may already be fixed.", file=sys.stderr)
    sys.exit(1)

with open('/app/tweetnacl.c', 'w') as f:
    f.write(src)

print("Fixed 3 bugs in tweetnacl.c:")
print("  1. Salsa20 core: rotation constant 6 -> 7")
print("  2. Poly1305: clamping mask r[4]&=248 -> r[4]&=252")
print("  3. SHA-512: IV[0] 0x6b -> 0x6a")
