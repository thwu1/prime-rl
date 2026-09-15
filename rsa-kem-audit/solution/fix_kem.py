#!/usr/bin/env python3
"""
Apply security fixes to the RSA-KEM implementation and write the audit
report.

Three vulnerabilities are fixed:

1. rsasve_generate: return-value mischeck — `if (ret)` treats -1 (failure
   from RSA_public_encrypt) as success because -1 is truthy in C.
2. rsasve_generate: dead error-handling code — the OPENSSL_cleanse call in
   the else branch was unreachable due to bug #1.
3. rsasve_recover: missing input-length validation — inlen is passed
   directly to RSA_private_decrypt without checking it matches the modulus
   size.
"""

import os

# ── Fix rsa_kem.c ──────────────────────────────────────────────────────────

KEM_PATH = "/app/rsa_kem.c"

with open(KEM_PATH, "r") as f:
    src = f.read()

# Fix 1 & 2: replace the buggy success check + dead else branch
old_generate = """\
    ret = RSA_public_encrypt((int)nlen, secret, out, rsa,
        RSA_NO_PADDING);
    if (ret) {
        ret = 1;
        if (outlen != NULL)
            *outlen = nlen;
        if (secretlen != NULL)
            *secretlen = nlen;
    } else {
        OPENSSL_cleanse(secret, nlen);
    }
    return ret;"""

new_generate = """\
    ret = RSA_public_encrypt((int)nlen, secret, out, rsa,
        RSA_NO_PADDING);
    if (ret <= 0 || ret != (int)nlen) {
        OPENSSL_cleanse(secret, nlen);
        return 0;
    }

    if (outlen != NULL)
        *outlen = nlen;
    if (secretlen != NULL)
        *secretlen = nlen;

    return 1;"""

assert old_generate in src, "Expected buggy rsasve_generate pattern not found"
src = src.replace(old_generate, new_generate)

# Fix 3: add inlen validation before RSA_private_decrypt
old_recover = """\
    ret = RSA_private_decrypt((int)inlen, in, secret, rsa,
        RSA_NO_PADDING);"""

new_recover = """\
    if (inlen != nlen)
        return 0;

    ret = RSA_private_decrypt((int)inlen, in, secret, rsa,
        RSA_NO_PADDING);"""

assert old_recover in src, "Expected rsasve_recover pattern not found"
src = src.replace(old_recover, new_recover)

with open(KEM_PATH, "w") as f:
    f.write(src)

print(f"Patched {KEM_PATH}")

# ── Write audit report ─────────────────────────────────────────────────────

REPORT = """\
# RSA-KEM Security Audit Report

## Summary

A security audit of the RSASVE implementation in `/app/rsa_kem.c` identified
three vulnerabilities.  All have been remediated.

---

## 1. Critical — Return-value mischeck in `rsasve_generate()`

**File:** `rsa_kem.c`, function `rsasve_generate`

**Root cause:**
After calling `RSA_public_encrypt()`, the code checked `if (ret)` to
determine success.  `RSA_public_encrypt()` returns the number of encrypted
bytes on success (a positive integer) or **-1 on failure**.  Because -1 is
non-zero (truthy) in C, `if (ret)` evaluates to *true* on failure, causing
the function to report success when the underlying RSA operation failed.

**Security impact:**
- The encapsulation function returns 1 (success) and reports output lengths
  even though no valid ciphertext was produced.
- The randomly generated secret is returned to the caller rather than being
  cleansed, potentially exposing key material.
- The peer, upon attempting decapsulation of the garbage ciphertext, will
  derive a different shared secret, causing a silent key-agreement failure
  or, in the worst case, a session with a predictable key.

**Fix:**
Replaced `if (ret)` with `if (ret <= 0 || ret != (int)nlen)`.  On failure,
`OPENSSL_cleanse(secret, nlen)` is called before returning 0.

---

## 2. High — Dead error-handling code (secret not cleansed)

**File:** `rsa_kem.c`, function `rsasve_generate`

**Root cause:**
The `else` branch containing `OPENSSL_cleanse(secret, nlen)` was dead code.
`RSA_public_encrypt()` never returns 0 — it returns a positive byte count or
-1.  Combined with the `if (ret)` bug (#1), the else branch was unreachable:
positive returns and -1 both satisfy `if (ret)`.

**Security impact:**
Secret key material (the random nonce z) remains in process memory after a
failed encapsulation and may be recoverable via memory-disclosure attacks,
core dumps, or swap.

**Fix:**
Restructured the control flow so `OPENSSL_cleanse` is called immediately on
the error path (before `return 0`), making it reachable whenever
`RSA_public_encrypt` returns a non-positive value or an unexpected length.

---

## 3. Medium — Missing input-length validation in `rsasve_recover()`

**File:** `rsa_kem.c`, function `rsasve_recover`

**Root cause:**
The function passes `inlen` directly to `RSA_private_decrypt()` without
first verifying that `inlen == nlen` (the RSA modulus byte-length).  A caller
supplying a truncated or oversized ciphertext would invoke RSA decryption
with an unexpected data length.

**Security impact:**
- Truncated ciphertext may cause `RSA_private_decrypt` to read beyond the
  caller-provided buffer.
- Oversized ciphertext could lead to undefined behaviour depending on the
  OpenSSL version and engine in use.
- An attacker able to control the ciphertext length may trigger
  distinguishable error responses, enabling padding-oracle-style analysis.

**Fix:**
Added `if (inlen != nlen) return 0;` before the call to
`RSA_private_decrypt`, rejecting ciphertext whose length does not match the
expected modulus size.
"""

with open("/app/AUDIT.md", "w") as f:
    f.write(REPORT)

print("Written /app/AUDIT.md")
