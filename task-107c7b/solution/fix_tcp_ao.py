#!/usr/bin/env python3
"""
Fix the 4 bugs in /app/tcp_ao.py per RFC 9235 Section 8 documented pitfalls.

Bug 1: KDF_LABEL includes null terminator (b"TCP-AO\\x00" -> b"TCP-AO")
Bug 2: Output length encoded in little-endian (struct.pack('<H') -> '>H')
Bug 3: KDF counter starts at i=0 (range(iterations) -> range(1, iterations+1))
Bug 4: AES-128-CMAC key normalization uses zero-padding instead of AES-CMAC(0^128, MK)

"""

import re

def fix_tcp_ao():
    with open('/app/tcp_ao.py', 'r') as f:
        code = f.read()

    # Bug 1: Remove null terminator from KDF label
    # The label "TCP-AO" should be exactly 6 bytes with no trailing null
    code = code.replace(
        'KDF_LABEL = b"TCP-AO\\x00"',
        'KDF_LABEL = b"TCP-AO"'
    )

    # Bug 2: Fix output length encoding from little-endian to big-endian (network byte order)
    # RFC 5926 Section 3.1.1: "Output_Length is represented within two octets" (network byte order)
    code = code.replace(
        "struct.pack('<H', length_bits)",
        "struct.pack('>H', length_bits)"
    )

    # Bug 3: Fix KDF counter to start at i=1 instead of i=0
    # RFC 5926 Section 3.1.1: "i always starts = 1"
    # This appears in both kdf_hmac_sha1 and kdf_aes_128_cmac
    code = code.replace(
        'for i in range(iterations):',
        'for i in range(1, iterations + 1):'
    )

    # Bug 4: Fix AES-128-CMAC key normalization
    # RFC 5926 Section 3.1.1.2: When master_key != 16 bytes,
    # K = AES-CMAC(0^128, master_key), NOT zero-padding
    code = code.replace(
        "        K = master_key.ljust(16, b'\\x00')",
        "        K = aes_128_cmac(b'\\x00' * 16, master_key)"
    )

    with open('/app/tcp_ao.py', 'w') as f:
        f.write(code)

    print("Applied 4 bug fixes to /app/tcp_ao.py")


if __name__ == '__main__':
    fix_tcp_ao()
