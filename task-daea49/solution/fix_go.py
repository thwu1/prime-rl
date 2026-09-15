"""Fix the five bugs in the Go XAES-256-GCM implementation.


Bug 1 - AES key size (in New):
    The AES block cipher is initialized with x.key[:16] (AES-128, 16-byte key)
    instead of x.key[:] (AES-256, 32-byte key). crypto/aes.NewCipher accepts
    both sizes without error, so this compiles and runs but uses the wrong
    block cipher for all CMAC and KDF operations.
    Fix: x.key[:16] -> x.key[:]

Bug 2 - CMAC K1 carry bit (in deriveK1):
    The left-shift carry propagation takes the LSB of the next byte (L[i+1] & 1)
    instead of the MSB (L[i+1] >> 7). This corrupts the shifted value for most
    keys where any byte has its MSB set.
    Fix: (L[i+1] & 1) -> (L[i+1] >> 7)

Bug 3 - Derived nonce slice (in deriveKeyAndNonce):
    The derived GCM nonce copies from nonce[:12] (first 12 bytes) instead of
    nonce[12:] (last 12 bytes) per Step 4 of the spec: Nx = N[12:24].
    Fix: nonce[:12] -> nonce[12:]

Bug 4 - GF(2^128) reduction polynomial (in deriveK1):
    Uses 0xE1 which is the GHASH bit-reflected representation of the GF(2^128)
    polynomial. CMAC uses the standard byte-order representation where
    R_b = 0x00...0087 (the polynomial x^7 + x^2 + x + 1 at the last byte).
    The 0xE1 value corresponds to the bit-reflected convention used in GCM's
    GHASH where x^128 + x^7 + x^2 + x + 1 maps to 0xE1 at byte[0].
    Fix: 0xE1 -> 0x87

Bug 5 - KDF counter off-by-one (in deriveKeyAndNonce):
    The KDF counter values start at 0 (m1 counter = 0x0000, m2 counter = 0x0001)
    instead of 1 (m1 counter = 0x0001, m2 counter = 0x0002) as specified by
    NIST SP 800-108r1 Section 4.1 counter-based KDF.
    Fix: m1 counter 0x00,0x00 -> 0x00,0x01; m2 counter 0x00,0x01 -> 0x00,0x02
"""

with open("/app/go_impl/xaes.go", "r") as f:
    code = f.read()

# Fix 1: AES key size - use full 32-byte key for AES-256
code = code.replace(
    "aes.NewCipher(x.key[:16])",
    "aes.NewCipher(x.key[:])",
)

# Fix 2: CMAC K1 carry bit - take MSB of next byte, not LSB
code = code.replace(
    "(L[i+1] & 1)",
    "(L[i+1] >> 7)",
)

# Fix 3: Derived nonce - use last 12 bytes, not first 12
code = code.replace(
    "copy(derivedNonce, nonce[:12])",
    "copy(derivedNonce, nonce[12:])",
)

# Fix 4: GF(2^128) polynomial - CMAC byte-order (0x87), not GHASH bit-reflected (0xE1)
code = code.replace(
    "shifted[15] ^= 0xE1",
    "shifted[15] ^= 0x87",
)

# Fix 5: KDF counter off-by-one - counters start at 1, not 0
code = code.replace(
    "m1[0], m1[1], m1[2], m1[3] = 0x00, 0x00, 0x58, 0x00",
    "m1[0], m1[1], m1[2], m1[3] = 0x00, 0x01, 0x58, 0x00",
)
code = code.replace(
    "m2[0], m2[1], m2[2], m2[3] = 0x00, 0x01, 0x58, 0x00",
    "m2[0], m2[1], m2[2], m2[3] = 0x00, 0x02, 0x58, 0x00",
)

with open("/app/go_impl/xaes.go", "w") as f:
    f.write(code)

print("Go implementation fixed (5 bugs).")
