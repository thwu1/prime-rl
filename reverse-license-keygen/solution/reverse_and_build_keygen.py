#!/usr/bin/env python3
"""
Reverse-engineer /app/license_check and produce /app/keygen.py.

Strategy:
1. Use radare2 to find the SBOX in .rodata (256-byte permutation-like table)
2. Extract Feistel round constants from the binary
3. Identify the hash, substitution, feistel, and finalization stages
4. Write the keygen with the extracted constants
"""

import subprocess
import struct
import re
import sys
import os

BINARY = "/app/license_check"


def find_sbox_in_binary():
    """
    Search for the 256-byte S-box in .rodata by looking for a sequence
    of 256 bytes where every value 0-255 appears exactly once (a permutation).
    If not a strict permutation, find via known first bytes pattern.
    """
    with open(BINARY, "rb") as f:
        data = f.read()

    # The S-box starts with: 0x80, 0xD7, 0x98, 0x02, 0xF8, 0x4E, 0xC1, 0xD6
    sbox_prefix = bytes([0x80, 0xD7, 0x98, 0x02, 0xF8, 0x4E, 0xC1, 0xD6])
    idx = data.find(sbox_prefix)
    if idx == -1:
        # Try r2 approach
        raise RuntimeError("Could not find S-box prefix in binary")

    sbox = list(data[idx:idx + 256])
    # Validate: should contain many distinct values
    if len(set(sbox)) < 200:
        raise RuntimeError(f"S-box doesn't look right: only {len(set(sbox))} distinct values")

    return sbox


def extract_constants_via_strings():
    """
    Use strings/disassembly to confirm the binary structure.
    The key constants are known from analysis:
    - Hash init: 0x243F6A8885A308D3
    - Hash multiply: 0x100000001B3
    - Hash add: 0x9E3779B97F4A7C15
    - Rotate: 17 bits right
    - Shift: 31 bits right
    - Feistel round keys: 0xDEADBEEF, 0x0BADF00D, 0xFEEDFACE, 0x27182818
    - Feistel round muls: 0x1337CAFE, 0xCAFEBABE, 0xC0FFEE42, 0x31415927
    - Feistel shifts: 7, 11, 5, 13
    - Finalize mul1: 0xFF51AFD7ED558CCD
    - Finalize mul2: 0xC4CEB9FE1A85EC53
    - Finalize shift: 33
    """
    with open(BINARY, "rb") as f:
        data = f.read()

    # Verify key constants exist in the binary
    constants = {
        "hash_init": 0x243F6A8885A308D3,
        "hash_mul": 0x100000001B3,
        "hash_add": 0x9E3779B97F4A7C15,
        "final_mul1": 0xFF51AFD7ED558CCD,
        "final_mul2": 0xC4CEB9FE1A85EC53,
    }

    found = {}
    for name, val in constants.items():
        le_bytes = val.to_bytes(8, "little")
        if le_bytes in data:
            found[name] = val

    # Feistel constants (32-bit)
    feistel_consts = {
        "rk0": 0xDEADBEEF,
        "rk1": 0x0BADF00D,
        "rk2": 0xFEEDFACE,
        "rk3": 0x27182818,
        "rm0": 0x1337CAFE,
        "rm1": 0xCAFEBABE,
        "rm2": 0xC0FFEE42,
        "rm3": 0x31415927,
    }

    for name, val in feistel_consts.items():
        le_bytes = val.to_bytes(4, "little")
        if le_bytes in data:
            found[name] = val

    return found


def write_keygen(sbox):
    """Write the keygen.py file using extracted S-box."""
    keygen_code = '''#!/usr/bin/env python3
"""Keygen for the license_check binary."""
import sys

SBOX = {sbox}

MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1


def ror64(v, n):
    n &= 63
    return ((v >> n) | (v << (64 - n))) & MASK64


def hash_username(user: bytes) -> int:
    h = 0x243F6A8885A308D3
    for c in user:
        h ^= c
        h = (h * 0x100000001B3) & MASK64
        h = ror64(h, 17)
        h = (h + 0x9E3779B97F4A7C15) & MASK64
        h ^= h >> 31
    return h


def substitute(h: int) -> int:
    b = list(h.to_bytes(8, "little"))
    for i in range(8):
        b[i] = SBOX[b[i]]
    return int.from_bytes(bytes(b), "little")


def feistel(h: int) -> int:
    L = (h >> 32) & MASK32
    R = h & MASK32
    rk = [0xDEADBEEF, 0x0BADF00D, 0xFEEDFACE, 0x27182818]
    rm = [0x1337CAFE, 0xCAFEBABE, 0xC0FFEE42, 0x31415927]
    rs = [7, 11, 5, 13]
    for i in range(4):
        f = (R * rm[i]) & MASK32
        f ^= R >> rs[i]
        f = (f + rk[i]) & MASK32
        tmp = L ^ f
        L = R
        R = tmp
    return (L << 32) | R


def finalize(h: int) -> int:
    h ^= h >> 33
    h = (h * 0xFF51AFD7ED558CCD) & MASK64
    h ^= h >> 33
    h = (h * 0xC4CEB9FE1A85EC53) & MASK64
    h ^= h >> 33
    return h


def derive_key(username: str) -> str:
    h = hash_username(username.encode("ascii"))
    h = substitute(h)
    h = feistel(h)
    h = finalize(h)
    return "{{:04x}}-{{:04x}}-{{:04x}}-{{:04x}}".format(
        (h >> 48) & 0xFFFF, (h >> 32) & 0xFFFF,
        (h >> 16) & 0xFFFF, h & 0xFFFF
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {{sys.argv[0]}} <username>", file=sys.stderr)
        sys.exit(1)
    print(derive_key(sys.argv[1]))
'''.format(sbox=repr(sbox))

    with open("/app/keygen.py", "w") as f:
        f.write(keygen_code)
    os.chmod("/app/keygen.py", 0o755)
    print(f"Wrote keygen to /app/keygen.py")


def verify_keygen():
    """Verify the keygen works against the binary."""
    test_users = ["admin", "root", "alice"]
    for user in test_users:
        result = subprocess.run(
            ["python3", "/app/keygen.py", user],
            capture_output=True, text=True, timeout=10
        )
        key = result.stdout.strip()

        result2 = subprocess.run(
            [BINARY],
            input=f"{user}\n{key}\n",
            capture_output=True, text=True, timeout=10
        )
        status = result2.stdout.strip()
        print(f"  {user} -> {key} -> {status}")
        if status != "VALID":
            raise RuntimeError(f"Verification failed for user '{user}'")

    print("All verification checks passed!")


def main():
    print("=== Reverse Engineering /app/license_check ===")

    print("\n[1] Extracting S-box from binary...")
    sbox = find_sbox_in_binary()
    print(f"    Found S-box at binary offset, {len(set(sbox))} distinct values")

    print("\n[2] Verifying algorithm constants...")
    found = extract_constants_via_strings()
    print(f"    Found {len(found)} constants in binary")
    for name, val in found.items():
        print(f"    {name} = 0x{val:X}")

    print("\n[3] Writing keygen...")
    write_keygen(sbox)

    print("\n[4] Verifying keygen...")
    verify_keygen()

    print("\nDone!")


if __name__ == "__main__":
    main()
