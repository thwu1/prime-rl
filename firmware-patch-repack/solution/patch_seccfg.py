#!/usr/bin/env python3
"""Patch the SECCFG security configuration block in a gateway ELF binary."""
import struct
import sys

MARKER = b"SECCFG\x00\x00"


def main():
    path = sys.argv[1]
    with open(path, "rb") as f:
        data = bytearray(f.read())

    idx = data.find(MARKER)
    if idx < 0:
        raise ValueError("SECCFG marker not found in binary")

    print(f"Found SECCFG at offset {idx:#x}")

    # Struct layout (packed, 28 bytes):
    #   [0:8]   magic "SECCFG\0\0"
    #   [8:10]  max_channel    uint16 LE
    #   [10]    require_auth   uint8
    #   [11]    tls_mode       uint8
    #   [12:16] session_timeout uint32 LE
    #   [16]    allow_debug    uint8
    #   [17]    cert_verify    uint8
    #   [18:20] min_key_bits   uint16 LE
    #   [20:28] reserved

    old = {
        "max_channel": struct.unpack_from("<H", data, idx + 8)[0],
        "require_auth": data[idx + 10],
        "tls_mode": data[idx + 11],
        "session_timeout": struct.unpack_from("<I", data, idx + 12)[0],
        "allow_debug": data[idx + 16],
        "cert_verify": data[idx + 17],
        "min_key_bits": struct.unpack_from("<H", data, idx + 18)[0],
    }
    print(f"  Before: {old}")

    # Apply hardening patches
    struct.pack_into("<H", data, idx + 8, 16)     # max_channel: 17 -> 16
    data[idx + 10] = 1                              # require_auth: 0 -> 1
    data[idx + 11] = 2                              # tls_mode: 0 -> 2 (required)
    # session_timeout at idx+12: leave as-is (86400)
    data[idx + 16] = 0                              # allow_debug: 1 -> 0
    data[idx + 17] = 1                              # cert_verify: 0 -> 1
    struct.pack_into("<H", data, idx + 18, 2048)   # min_key_bits: 512 -> 2048

    new = {
        "max_channel": struct.unpack_from("<H", data, idx + 8)[0],
        "require_auth": data[idx + 10],
        "tls_mode": data[idx + 11],
        "session_timeout": struct.unpack_from("<I", data, idx + 12)[0],
        "allow_debug": data[idx + 16],
        "cert_verify": data[idx + 17],
        "min_key_bits": struct.unpack_from("<H", data, idx + 18)[0],
    }
    print(f"  After:  {new}")

    with open(path, "wb") as f:
        f.write(data)


if __name__ == "__main__":
    main()
