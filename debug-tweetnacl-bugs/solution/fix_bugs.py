#!/usr/bin/env python3
"""
Fix the three subtle bugs in TweetNaCl.


Bug 1 — Salsa20 quarter-round rotation constant:
  The third rotation in the Salsa20 quarter-round is 12 instead of 13.
  The correct Salsa20 quarter-round rotation constants are (7, 9, 13, 18).
  Location: core() function, line ~90.

Bug 2 — Poly1305 key clamping mask:
  The clamping mask for r[12] is 248 (0xf8) instead of 252 (0xfc).
  Per the Poly1305 specification (Bernstein 2005), r[4], r[8], r[12] must
  have their bottom TWO bits cleared, i.e., &= 252. The buggy version
  clears THREE bottom bits.
  Location: crypto_onetimeauth() function, line ~196.

Bug 3 — Ed25519 public key decompression parity check:
  In unpackneg(), the comparison for the x-coordinate parity uses !=
  instead of ==. This inverts the sign recovery during Ed25519 public key
  decompression, causing all signature verifications to fail.
  Location: unpackneg() function, line ~773.
"""

import sys

FIXES = [
    # (buggy_string, correct_string, description)
    (
        "L32(t[2]+t[1],12)",
        "L32(t[2]+t[1],13)",
        "Salsa20 rotation constant 12->13",
    ),
    (
        "r[12]&=248;",
        "r[12]&=252;",
        "Poly1305 key clamping mask 248->252",
    ),
    (
        "if (par25519(r[0]) != (p[31]>>7))",
        "if (par25519(r[0]) == (p[31]>>7))",
        "Ed25519 parity check !=  ->  ==",
    ),
]

SRC_PATH = "/app/tweetnacl.c"


def main():
    with open(SRC_PATH, "r") as f:
        src = f.read()

    for buggy, correct, desc in FIXES:
        if buggy not in src:
            if correct in src:
                print(f"  [already fixed] {desc}")
            else:
                print(f"  [WARNING] Neither buggy nor correct pattern found for: {desc}")
            continue
        src = src.replace(buggy, correct, 1)
        print(f"  [fixed] {desc}")

    with open(SRC_PATH, "w") as f:
        f.write(src)

    print("All fixes applied to", SRC_PATH)


if __name__ == "__main__":
    main()
