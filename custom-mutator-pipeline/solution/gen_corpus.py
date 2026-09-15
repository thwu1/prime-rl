#!/usr/bin/env python3
"""Generate a diverse seed corpus for XPROTO fuzzing."""


import struct
import zlib
import os

MAGIC = b"XPR\x01"

FLAG_COMPRESSED = 0x0001
FLAG_CHECKSUM = 0x0002
FLAG_EXTENDED = 0x0004


def make_tlv(type_id, value):
    return struct.pack("<BH", type_id, len(value)) + value


def make_message(version, flags, tlv_entries, compress=False):
    payload = b"".join(tlv_entries)
    if compress:
        flags |= FLAG_COMPRESSED
        payload = zlib.compress(payload)
    header = MAGIC + struct.pack("<HHI", version, flags, len(payload))
    pre_crc = header + payload
    crc = zlib.crc32(pre_crc) & 0xFFFFFFFF
    return pre_crc + struct.pack("<I", crc)


def main():
    os.makedirs("/app/corpus", exist_ok=True)

    # Seed 1: v1, STRING + INT32, checksum
    with open("/app/corpus/seed_v1_basic.xproto", "wb") as f:
        f.write(make_message(1, FLAG_CHECKSUM, [
            make_tlv(0x01, b"hello world"),
            make_tlv(0x02, struct.pack("<I", 42)),
        ]))

    # Seed 2: v2, NESTED + ARRAY, checksum
    inner = make_tlv(0x01, b"nested") + make_tlv(0x02, struct.pack("<I", 100))
    with open("/app/corpus/seed_v2_nested.xproto", "wb") as f:
        f.write(make_message(2, FLAG_CHECKSUM, [
            make_tlv(0x03, inner),
            make_tlv(0x04, bytes([3]) + struct.pack("<III", 1, 2, 3)),
        ]))

    # Seed 3: v3, KEYVAL + STRING, checksum + extended
    with open("/app/corpus/seed_v3_keyval.xproto", "wb") as f:
        f.write(make_message(3, FLAG_CHECKSUM | FLAG_EXTENDED, [
            make_tlv(0x05, bytes([4]) + b"name" + b"test_value"),
            make_tlv(0x01, b"associated text"),
            make_tlv(0x02, struct.pack("<I", 999)),
        ]))

    # Seed 4: v2, compressed, no checksum
    with open("/app/corpus/seed_v2_compressed.xproto", "wb") as f:
        f.write(make_message(2, 0, [
            make_tlv(0x01, b"compressed data"),
            make_tlv(0x02, struct.pack("<I", 0xDEADBEEF)),
            make_tlv(0x04, bytes([2]) + struct.pack("<II", 10, 20)),
        ], compress=True))

    # Seed 5: v1, minimal INT32
    with open("/app/corpus/seed_v1_minimal.xproto", "wb") as f:
        f.write(make_message(1, FLAG_CHECKSUM, [
            make_tlv(0x02, struct.pack("<I", 0)),
        ]))

    # Seed 6: v2, multiple strings
    with open("/app/corpus/seed_v2_strings.xproto", "wb") as f:
        f.write(make_message(2, FLAG_CHECKSUM, [
            make_tlv(0x01, b"A"),
            make_tlv(0x01, b"short string"),
            make_tlv(0x01, b"a medium length string value here"),
            make_tlv(0x02, struct.pack("<I", 255)),
        ]))

    print("Generated 6 seed files in /app/corpus/")


if __name__ == "__main__":
    main()
