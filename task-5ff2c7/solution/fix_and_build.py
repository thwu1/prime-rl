#!/usr/bin/env python3
"""
Fix all bugs in the C/Python SP 800-185 implementation and build it.

Fixes applied:
1. Makefile: change from static archive (ar rcs) to shared library (gcc -shared -fPIC)
2. keccak.c theta step: swap D[x] = C[(x+1)%5] ^ rot64(C[(x+4)%5], 1)
                     to  D[x] = C[(x+4)%5] ^ rot64(C[(x+1)%5], 1)
3. keccak.c rho offset: RHO_OFFSETS[2][3] from 14 to 15
4. keccak.c round constant: RC[11] from 0x000000008000000B to 0x000000008000000A
5. sp800_185.py right_encode: swap bytes([n]) + x_bytes to x_bytes + bytes([n])
6. sp800_185.py: implement KMAC and TupleHash
"""

import subprocess
import os

os.chdir('/app')


# === Step 1: Fix the Makefile to build a shared library ===

MAKEFILE_FIXED = """CC = gcc
CFLAGS = -Wall -Wextra -O2 -fPIC

all: libkeccak.so

libkeccak.so: keccak.o
\t$(CC) -shared -o $@ $<

keccak.o: keccak.c keccak.h
\t$(CC) $(CFLAGS) -c -o $@ $<

debug_test: debug_test.c keccak.c keccak.h
\t$(CC) $(CFLAGS) -g -o $@ debug_test.c keccak.c

clean:
\trm -f *.o libkeccak.a libkeccak.so debug_test

.PHONY: all clean
"""

with open('/app/Makefile', 'w') as f:
    f.write(MAKEFILE_FIXED)
print("Fixed Makefile: builds shared library with -fPIC -shared")


# === Step 2: Fix keccak.c bugs ===

with open('/app/keccak.c', 'r') as f:
    c_code = f.read()

# Bug 1: Theta step - indices are swapped
# Buggy:  D[x] = C[(x + 1) % 5] ^ rot64(C[(x + 4) % 5], 1);
# Correct: D[x] = C[(x + 4) % 5] ^ rot64(C[(x + 1) % 5], 1);
c_code = c_code.replace(
    'D[x] = C[(x + 1) % 5] ^ rot64(C[(x + 4) % 5], 1);',
    'D[x] = C[(x + 4) % 5] ^ rot64(C[(x + 1) % 5], 1);'
)

# Bug 2: RHO_OFFSETS[2][3] = 14 should be 15
c_code = c_code.replace(
    '{62,  6, 43, 14, 61},',
    '{62,  6, 43, 15, 61},'
)

# Bug 3: RC[11] wrong value (0B should be 0A)
c_code = c_code.replace(
    '0x000000008000000BULL,',
    '0x000000008000000AULL,'
)

with open('/app/keccak.c', 'w') as f:
    f.write(c_code)
print("Fixed keccak.c: theta indices, rho offset [2][3], round constant RC[11]")


# === Step 3: Build the shared library ===

result = subprocess.run(['make', 'clean'], cwd='/app', capture_output=True, text=True)
result = subprocess.run(['make'], cwd='/app', capture_output=True, text=True)
print(f"Build: {result.stdout.strip()}")
if result.returncode != 0:
    print(f"Build error: {result.stderr}")
    raise RuntimeError("make failed")

# Verify the library is correct (informational)
import shutil
if shutil.which('file'):
    result = subprocess.run(['file', '/app/libkeccak.so'], capture_output=True, text=True)
    print(f"Library type: {result.stdout.strip()}")
if shutil.which('nm'):
    result = subprocess.run(['nm', '-D', '/app/libkeccak.so'], capture_output=True, text=True)
    print(f"Exported symbols: {result.stdout.strip()}")


# === Step 4: Fix sp800_185.py ===

SP800_185_FIXED = '''\
"""
SP 800-185: SHA-3 Derived Functions (cSHAKE, KMAC, TupleHash).
Uses the Keccak-f[1600] permutation from the compiled C library libkeccak.so.
"""

import ctypes
import os

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libkeccak.so')
_keccak_lib = ctypes.CDLL(_lib_path)
_keccak_lib.keccak_f1600.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
_keccak_lib.keccak_f1600.restype = None


def keccak_f1600(state_bytes):
    """Apply Keccak-f[1600] permutation to 200 bytes via C library."""
    buf = (ctypes.c_uint8 * 200)(*state_bytes)
    _keccak_lib.keccak_f1600(buf)
    return bytes(buf)


def left_encode(x):
    """Encode integer x with its byte-length prepended (SP 800-185 Section 2.3.1)."""
    if x == 0:
        return bytes([1, 0])
    n = (x.bit_length() + 7) // 8
    x_bytes = x.to_bytes(n, \'big\')
    return bytes([n]) + x_bytes


def right_encode(x):
    """Encode integer x with its byte-length appended (SP 800-185 Section 2.3.1)."""
    if x == 0:
        return bytes([0, 1])
    n = (x.bit_length() + 7) // 8
    x_bytes = x.to_bytes(n, \'big\')
    return x_bytes + bytes([n])


def encode_string(s):
    """Encode a byte string with its bit-length prefix (SP 800-185 Section 2.3.2)."""
    return left_encode(len(s) * 8) + s


def bytepad(X, w):
    """Pad byte string X to a multiple of w bytes (SP 800-185 Section 2.3.3)."""
    z = left_encode(w) + X
    pad_len = w - (len(z) % w)
    if pad_len == w:
        pad_len = 0
    return z + bytes(pad_len)


def _sponge(rate, data, suffix, output_len):
    """Generic Keccak sponge construction."""
    state = bytearray(200)

    i = 0
    while i + rate <= len(data):
        for j in range(rate):
            state[j] ^= data[i + j]
        state = bytearray(keccak_f1600(bytes(state)))
        i += rate

    remaining = len(data) - i
    for j in range(remaining):
        state[j] ^= data[i + j]

    state[remaining] ^= suffix
    state[rate - 1] ^= 0x80
    state = bytearray(keccak_f1600(bytes(state)))

    output = bytearray()
    while len(output) < output_len:
        output.extend(state[:rate])
        if len(output) < output_len:
            state = bytearray(keccak_f1600(bytes(state)))

    return bytes(output[:output_len])


def cshake(security, X, L, N, S):
    """cSHAKE per SP 800-185 Section 6.2."""
    rate = 168 if security == 128 else 136

    if len(N) == 0 and len(S) == 0:
        return _sponge(rate, X, 0x1F, L // 8)

    prefix = bytepad(encode_string(N) + encode_string(S), rate)
    return _sponge(rate, prefix + X, 0x04, L // 8)


def kmac(security, K, X, L, S):
    """KMAC per SP 800-185 Section 8."""
    rate = 168 if security == 128 else 136
    new_X = bytepad(encode_string(K), rate) + X + right_encode(L)
    return cshake(security, new_X, L, b"KMAC", S)


def tuplehash(security, tuples, L, S):
    """TupleHash per SP 800-185 Section 9."""
    Z = b""
    for Xi in tuples:
        Z += encode_string(Xi)
    Z += right_encode(L)
    return cshake(security, Z, L, b"TupleHash", S)
'''

with open('/app/sp800_185.py', 'w') as f:
    f.write(SP800_185_FIXED)
print("Fixed sp800_185.py: right_encode byte order, implemented KMAC and TupleHash")


# === Step 5: Validate ===

print("\n=== Running validation ===")
result = subprocess.run(
    ['python3', '/app/validate.py'],
    cwd='/app', capture_output=True, text=True
)
print(result.stdout)
if result.returncode != 0:
    print(result.stderr)
    raise RuntimeError("Validation failed")
print("All tests passed!")
