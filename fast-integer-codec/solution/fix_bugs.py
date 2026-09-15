#!/usr/bin/env python3
"""
fix_bugs.py — Patch all correctness bugs in /app/fastnum.c

Bug 1: kPow10[19] is a duplicate of kPow10[18] (1e18 instead of 1e19).
        This causes count_digits to return 20 for all 19-digit numbers.

Bug 2: Overflow threshold in dec_to_uint64 is UINT64_MAX/10 + 1 instead
        of UINT64_MAX/10.  Values where the accumulated result equals
        1844674407370955162 slip through and wrap on multiplication by 10.

Bug 3: nibble_to_hex uses ('a' - '9') = 40 as the jump constant instead
        of ('a' - '0' - 10) = 39.  All hex letters a-f are off by +1.

Bug 4: hex_to_nibble only handles uppercase A-F; lowercase a-f returns -1.

Bug 5: uint64_mul_overflow is a stub that always returns 0.
"""

import sys

PATH = "/app/fastnum.c"

with open(PATH, "r") as f:
    code = f.read()

original = code

# -----------------------------------------------------------------------
# Bug 1: Fix power-of-10 table entry for 10^19
# -----------------------------------------------------------------------
old_pow = (
    "UINT64_C(1000000000000000000),     /* 10^19 */"
)
new_pow = (
    "UINT64_C(10000000000000000000),    /* 10^19 */"
)
assert old_pow in code, "Cannot find kPow10[19] entry to patch"
code = code.replace(old_pow, new_pow, 1)

# -----------------------------------------------------------------------
# Bug 2: Fix overflow threshold (UINT64_MAX / 10 = 1844674407370955161)
# -----------------------------------------------------------------------
old_thresh = "UINT64_C(1844674407370955162)"
new_thresh = "UINT64_C(1844674407370955161)"
assert old_thresh in code, "Cannot find overflow threshold to patch"
code = code.replace(old_thresh, new_thresh, 1)

# -----------------------------------------------------------------------
# Bug 3: Fix hex encode constant from 40 to 39
# -----------------------------------------------------------------------
old_nibble = "((val > 9) * ('a' - '9'))"
new_nibble = "((val > 9) * ('a' - '0' - 10))"
assert old_nibble in code, "Cannot find nibble_to_hex constant to patch"
code = code.replace(old_nibble, new_nibble, 1)

# -----------------------------------------------------------------------
# Bug 4: Add lowercase hex support to hex_to_nibble
# -----------------------------------------------------------------------
old_decode = """static inline int hex_to_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}"""

new_decode = """static inline int hex_to_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}"""

assert old_decode in code, "Cannot find hex_to_nibble to patch"
code = code.replace(old_decode, new_decode, 1)

# -----------------------------------------------------------------------
# Bug 5: Implement uint64_mul_overflow
# -----------------------------------------------------------------------
old_stub = """int uint64_mul_overflow(uint64_t a, uint64_t b) {
    /* TODO: implement overflow detection for a * b */
    (void)a;
    (void)b;
    return 0;
}"""

new_impl = """int uint64_mul_overflow(uint64_t a, uint64_t b) {
    if (a == 0 || b == 0) return 0;
    return a > UINT64_MAX / b ? 1 : 0;
}"""

assert old_stub in code, "Cannot find uint64_mul_overflow stub to patch"
code = code.replace(old_stub, new_impl, 1)

# -----------------------------------------------------------------------
# Write patched file
# -----------------------------------------------------------------------
assert code != original, "No changes were made — assertions may be wrong"

with open(PATH, "w") as f:
    f.write(code)

print("All 5 bugs patched successfully.")
