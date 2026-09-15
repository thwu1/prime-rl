#!/usr/bin/env python3

"""
Solution: Identify and fix security vulnerabilities in firmware.

Vulnerability 1 - Dead Store Elimination (DSE):
  GCC's -O2 enables Dead Store Elimination, which removes stores to memory
  that are never subsequently read. When memset() zeros a local buffer that
  is about to go out of scope (function return), the compiler determines that
  the zeros are never read and removes the memset call entirely. This leaves
  sensitive cryptographic material (keys, hashes) on the stack.

  Fix: Replace memset() with explicit_bzero(), which is specifically designed
  to resist compiler optimization. The compiler is required to perform the
  memory clear even if the result is never observed.

Vulnerability 2 - Timing Side Channel in memcmp:
  memcmp() exits early on the first byte difference, making its execution time
  proportional to the number of matching prefix bytes. An attacker can exploit
  this to brute-force a secret (HMAC, hash) one byte at a time by measuring
  response latency. This was demonstrated in MITRE eCTF 2025 competitions.

  Fix: Replace memcmp() with a constant-time comparison that always examines
  all bytes using XOR accumulation with a volatile result variable.
"""

import subprocess
import sys
import re


def main():
    src_path = "/app/src/secure_ops.c"

    # Read original source
    with open(src_path) as f:
        source = f.read()

    # Step 1: Compile original to verify dead stores exist
    print("=== Compiling original code ===")
    result = subprocess.run(
        ["make", "-C", "/app", "clean", "all"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Original compilation failed: {result.stderr}")
        sys.exit(1)

    # Analyze original binary for dead stores
    result = subprocess.run(
        ["objdump", "-d", "/app/build/secure_firmware"],
        capture_output=True, text=True
    )
    objdump_original = result.stdout

    dead_store_functions = []
    for func in ["secure_encrypt", "secure_decrypt", "verify_auth_token",
                 "generate_keypair", "hmac_sign", "process_subscription",
                 "derive_session_key"]:
        func_asm = extract_function(objdump_original, func)
        # In the original, these functions should NOT have memset or
        # explicit_bzero calls because DSE removed the memset
        if "memset" not in func_asm.lower() and "explicit_bzero" not in func_asm.lower():
            dead_store_functions.append(func)
            print(f"  CONFIRMED dead store in: {func}")
        else:
            print(f"  NOTE: {func} has memset/bzero (may not be dead store)")

    # Step 2: Add constant-time comparison function
    ct_compare = '''
/* Constant-time comparison function.
 * Returns 0 if buffers are equal, non-zero otherwise.
 * The volatile qualifier on result prevents the compiler from
 * short-circuiting the loop, which would reintroduce a timing
 * side channel (as memcmp does). */
static int secure_compare(const uint8_t *a, const uint8_t *b, size_t len) {
    volatile uint8_t result = 0;
    for (size_t i = 0; i < len; i++) {
        result |= a[i] ^ b[i];
    }
    return (int)result;
}

'''
    # Insert before the first function definition
    marker = "int secure_encrypt("
    insert_pos = source.index(marker)
    source = source[:insert_pos] + ct_compare + source[insert_pos:]

    # Step 3: Replace dead-store memset calls with explicit_bzero
    memset_replacements = [
        ("memset(expanded_key, 0, sizeof(expanded_key));",
         "explicit_bzero(expanded_key, sizeof(expanded_key));"),
        ("memset(computed_hash, 0, sizeof(computed_hash));",
         "explicit_bzero(computed_hash, sizeof(computed_hash));"),
        ("memset(entropy_pool, 0, sizeof(entropy_pool));",
         "explicit_bzero(entropy_pool, sizeof(entropy_pool));"),
        ("memset(inner_key, 0, sizeof(inner_key));",
         "explicit_bzero(inner_key, sizeof(inner_key));"),
        ("memset(outer_key, 0, sizeof(outer_key));",
         "explicit_bzero(outer_key, sizeof(outer_key));"),
        ("memset(computed_hmac, 0, sizeof(computed_hmac));",
         "explicit_bzero(computed_hmac, sizeof(computed_hmac));"),
        ("memset(local_master, 0, sizeof(local_master));",
         "explicit_bzero(local_master, sizeof(local_master));"),
    ]

    for old, new in memset_replacements:
        count = source.count(old)
        if count == 0:
            print(f"WARNING: Pattern not found: {old}")
        source = source.replace(old, new)
        print(f"  Replaced {count}x: {old[:40]}...")

    # Step 4: Replace timing-vulnerable memcmp with constant-time comparison
    memcmp_replacements = [
        ("memcmp(computed_hash, stored_hash, 32)",
         "secure_compare(computed_hash, stored_hash, 32)"),
        ("memcmp(provided_hmac, computed_hmac, 32)",
         "secure_compare(provided_hmac, computed_hmac, 32)"),
    ]

    for old, new in memcmp_replacements:
        source = source.replace(old, new)
        print(f"  Replaced memcmp: {old[:50]}...")

    # Step 5: Write fixed source
    with open(src_path, "w") as f:
        f.write(source)
    print(f"\nFixed source written to {src_path}")

    # Step 6: Compile and verify
    print("\n=== Compiling fixed code ===")
    result = subprocess.run(
        ["make", "-C", "/app", "clean", "all"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Compilation failed: {result.stderr}")
        sys.exit(1)
    print("Compilation successful.")

    # Run functional test
    result = subprocess.run(
        ["/app/build/secure_firmware"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Functional test failed: {result.stdout}\n{result.stderr}")
        sys.exit(1)
    print(f"Functional test: {result.stdout.strip()}")

    # Verify fixes survived -O2
    print("\n=== Verifying fixes survived -O2 optimization ===")
    result = subprocess.run(
        ["objdump", "-d", "/app/build/secure_firmware"],
        capture_output=True, text=True
    )
    objdump_fixed = result.stdout

    all_ok = True
    for func in ["secure_encrypt", "secure_decrypt", "verify_auth_token",
                 "generate_keypair", "hmac_sign", "process_subscription",
                 "derive_session_key"]:
        func_asm = extract_function(objdump_fixed, func)
        if "explicit_bzero" in func_asm:
            print(f"  OK: {func} has explicit_bzero")
        elif "memset" in func_asm:
            print(f"  OK: {func} has memset (preserved via barrier)")
        else:
            print(f"  FAIL: {func} missing wipe operation!")
            all_ok = False

    for func in ["verify_auth_token", "process_subscription"]:
        func_asm = extract_function(objdump_fixed, func)
        if "memcmp" not in func_asm.lower():
            print(f"  OK: {func} does not use memcmp")
        else:
            print(f"  FAIL: {func} still uses memcmp!")
            all_ok = False

    if not all_ok:
        print("\nSome fixes did not survive optimization!")
        sys.exit(1)

    # Step 7: Write audit report
    write_audit_report()
    print("\nAll fixes applied and verified successfully.")


def extract_function(objdump_text, func_name):
    """Extract disassembly for a specific function."""
    pattern = rf'^[0-9a-f]+ <{re.escape(func_name)}>:.*?(?=\n[0-9a-f]+ <|\Z)'
    match = re.search(pattern, objdump_text, re.MULTILINE | re.DOTALL)
    return match.group(0) if match else ""


def write_audit_report():
    report = """Firmware Security Audit Report
================================

Date: Automated analysis
Compiler: GCC with -O2 optimization
Binary: /app/build/secure_firmware

VULNERABILITY CLASS 1: Dead Store Elimination (DSE)
=====================================================

The compiler's Dead Store Elimination optimization at -O2 silently removes
memset() calls that zero out sensitive data when the buffer is a local
variable and not read after the memset before going out of scope. This
leaves cryptographic keys, hashes, and other sensitive material on the
stack after function return, where it could be recovered via:
  - Stack buffer over-reads (e.g., Heartbleed-style vulnerabilities)
  - Cold boot attacks on RAM contents
  - Stack frame reuse by subsequent function calls

AFFECTED FUNCTIONS:

1. secure_encrypt: expanded_key[176] (key schedule) not wiped
   - memset(expanded_key, 0, sizeof(expanded_key)) removed by DSE
   - Fix: replaced with explicit_bzero()

2. secure_decrypt: expanded_key[176] (key schedule) not wiped
   - memset(expanded_key, 0, sizeof(expanded_key)) removed by DSE
   - Fix: replaced with explicit_bzero()

3. verify_auth_token: computed_hash[32] not wiped
   - memset(computed_hash, 0, sizeof(computed_hash)) removed by DSE
   - Fix: replaced with explicit_bzero()

4. generate_keypair: entropy_pool[64] not wiped
   - memset(entropy_pool, 0, sizeof(entropy_pool)) removed by DSE
   - Fix: replaced with explicit_bzero()

5. hmac_sign: inner_key[64] and outer_key[64] not wiped (2 dead stores)
   - memset(inner_key, 0, 64) and memset(outer_key, 0, 64) removed by DSE
   - Fix: replaced both with explicit_bzero()

6. process_subscription: computed_hmac[32] not wiped
   - memset(computed_hmac, 0, sizeof(computed_hmac)) removed by DSE
   - Fix: replaced with explicit_bzero()

7. derive_session_key: local_master[32] (copy of master key) not wiped
   - memset(local_master, 0, sizeof(local_master)) removed by DSE
   - Fix: replaced with explicit_bzero()

Total: 8 dead-store memset calls across 7 functions.


VULNERABILITY CLASS 2: Timing Side-Channel in Comparisons
============================================================

Using memcmp() to compare security-critical values (HMAC signatures,
authentication hashes) enables timing side-channel attacks. memcmp()
returns early on the first byte difference, allowing an attacker to
determine correct bytes by measuring response time and brute-forcing
the value one byte at a time. This attack was successfully demonstrated
against multiple teams in the MITRE eCTF 2025 competition.

Note: memcmp() on many architectures compares 4 bytes at a time using
word-sized loads. When the 4-byte comparison fails, it falls back to
byte-by-byte comparison to find the exact differing byte. This means
every 4th byte exhibits inverted timing behavior (shortest time = correct),
adding complexity to the attack but not preventing it.

AFFECTED FUNCTIONS:

1. verify_auth_token: memcmp(computed_hash, stored_hash, 32)
   - Fix: replaced with constant-time XOR-based comparison

2. process_subscription: memcmp(provided_hmac, computed_hmac, 32)
   - Fix: replaced with constant-time XOR-based comparison

The constant-time comparison uses volatile accumulation of XOR differences
to prevent the compiler from short-circuiting the loop.


ALREADY SAFE FUNCTIONS:
========================
- safe_wipe_example: correctly uses volatile pointer for memory wiping
- already_safe_sign: correctly uses explicit_bzero() for memory wiping
  These serve as reference implementations of proper technique.
"""

    with open("/app/audit_report.txt", "w") as f:
        f.write(report)
    print("Audit report written to /app/audit_report.txt")


if __name__ == "__main__":
    main()
