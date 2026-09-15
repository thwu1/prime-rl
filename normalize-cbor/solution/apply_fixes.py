#!/usr/bin/env python3
"""
Apply targeted fixes to the buggy CBOR deterministic normalizer pipeline.

Reads /app/pipeline.py, identifies and fixes four encoding defects:
1. Off-by-one in argument width boundary (0xFF vs 0x100)
2. Missing NaN canonicalization (NaN != NaN causes fallthrough to f64)
3. Negative zero sign loss (Python -0.0 == 0.0 matches zero fast-path)
4. Wrong map key sort algorithm (length-first vs bytewise-lexicographic)
"""


import sys

with open('/app/pipeline.py', 'r') as f:
    code = f.read()

original = code

# --- Fix 1: Argument encoding boundary ---
# The bug uses "arg < 0xFF" (255), excluding 255 from the u8 range.
# Correct threshold is "arg < 0x100" (256), so 0..255 all fit in u8.
code = code.replace('arg < 0xFF', 'arg < 0x100')

# --- Fix 2 & 3: NaN canonicalization and negative zero sign preservation ---
# The buggy code has a zero fast-path that matches -0.0 (since -0.0 == 0.0
# in Python), encoding it as positive zero. Also, there is no NaN special
# case, so NaN falls through all roundtrip checks (NaN != NaN) to f64.
#
# Replace the zero fast-path with proper NaN + signed-zero handling.
old_float_start = '''    # Fast path for zero
    if value == 0.0:
        return b'\\xf9\\x00\\x00\''''

new_float_start = '''    # Canonical NaN: all NaN values -> half-precision quiet NaN
    if math.isnan(value):
        return b'\\xf9\\x7e\\x00'
    # Zero with sign preservation
    if value == 0.0:
        if math.copysign(1.0, value) < 0:
            return b'\\xf9\\x80\\x00'
        return b'\\xf9\\x00\\x00\''''

code = code.replace(old_float_start, new_float_start)

# --- Fix 4: Map key sorting algorithm ---
# The bug sorts by (len(encoded_key), encoded_key) which is the
# length-first ordering from Section 4.2.3. Core Deterministic (4.2.1)
# requires pure bytewise lexicographic comparison of encoded keys.
code = code.replace(
    'encoded.sort(key=lambda p: (len(p[0]), p[0]))',
    'encoded.sort(key=lambda p: p[0])'
)

# Verify all fixes were applied
if code == original:
    print("ERROR: No changes were made — fix patterns may not match", file=sys.stderr)
    sys.exit(1)

with open('/app/pipeline.py', 'w') as f:
    f.write(code)

print("Applied 4 fixes to /app/pipeline.py")
