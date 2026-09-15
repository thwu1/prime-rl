"""
XPROTO protocol reference validator.
Usage: validate(data: bytes) -> (bool, entries_or_error)

"""

import struct
import zlib

MAGIC = b"XPR\x01"
HEADER_LEN = 12
CRC_LEN = 4

FLAG_COMPRESSED = 0x0001
FLAG_CHECKSUM   = 0x0002
FLAG_EXTENDED   = 0x0004

TLV_STRING = 0x01
TLV_INT32  = 0x02
TLV_NESTED = 0x03
TLV_ARRAY  = 0x04
TLV_KEYVAL = 0x05

MAX_DEPTH = 4
MAX_ENTRIES = 32


def compute_crc32(data):
    return zlib.crc32(data) & 0xFFFFFFFF


def parse_tlv_entries(data, version, depth=0):
    if depth > MAX_DEPTH:
        raise ValueError("Nested depth exceeds maximum ({})".format(MAX_DEPTH))

    entries = []
    offset = 0
    while offset < len(data):
        if offset + 3 > len(data):
            raise ValueError("Truncated TLV header at offset {}".format(offset))

        tlv_type = data[offset]
        tlv_len = struct.unpack_from("<H", data, offset + 1)[0]
        offset += 3

        if offset + tlv_len > len(data):
            raise ValueError(
                "TLV value overflows data (type={:#x}, len={}, avail={})".format(
                    tlv_type, tlv_len, len(data) - offset
                )
            )

        value = data[offset : offset + tlv_len]
        offset += tlv_len

        if tlv_type == TLV_STRING:
            try:
                value.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("STRING TLV contains invalid UTF-8")

        elif tlv_type == TLV_INT32:
            if tlv_len != 4:
                raise ValueError("INT32 TLV length must be 4, got {}".format(tlv_len))

        elif tlv_type == TLV_NESTED:
            if version < 2:
                raise ValueError("NESTED type requires version >= 2")
            parse_tlv_entries(value, version, depth + 1)

        elif tlv_type == TLV_ARRAY:
            if version < 2:
                raise ValueError("ARRAY type requires version >= 2")
            if tlv_len < 1:
                raise ValueError("ARRAY TLV too short for count byte")
            count = value[0]
            if count * 4 != tlv_len - 1:
                raise ValueError(
                    "ARRAY count ({}) * 4 != length - 1 ({})".format(
                        count, tlv_len - 1
                    )
                )

        elif tlv_type == TLV_KEYVAL:
            if version < 3:
                raise ValueError("KEYVAL type requires version >= 3")
            if tlv_len < 1:
                raise ValueError("KEYVAL TLV too short")
            key_len = value[0]
            if key_len + 1 > tlv_len:
                raise ValueError(
                    "KEYVAL key_len ({}) + 1 exceeds value length ({})".format(
                        key_len, tlv_len
                    )
                )

        else:
            raise ValueError("Unknown TLV type: {:#x}".format(tlv_type))

        entries.append((tlv_type, tlv_len, value))

        if len(entries) > MAX_ENTRIES:
            raise ValueError("Too many TLV entries (max {})".format(MAX_ENTRIES))

    return entries


def validate(data):
    """Validate an XPROTO message.

    Returns (True, list_of_top_level_entries) on success,
    or (False, error_string) on failure.
    Each entry is a tuple (type_id, length, value_bytes).
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        return False, "Input must be bytes-like"

    data = bytes(data)

    if len(data) < HEADER_LEN + CRC_LEN:
        return False, "Message too short ({} bytes)".format(len(data))

    if data[:4] != MAGIC:
        return False, "Invalid magic: {!r}".format(data[:4])

    version = struct.unpack_from("<H", data, 4)[0]
    flags = struct.unpack_from("<H", data, 6)[0]
    payload_len = struct.unpack_from("<I", data, 8)[0]

    if version < 1 or version > 3:
        return False, "Invalid version: {}".format(version)

    expected_len = HEADER_LEN + payload_len + CRC_LEN
    if len(data) != expected_len:
        return False, "Length mismatch: expected {}, got {}".format(
            expected_len, len(data)
        )

    if (flags & FLAG_EXTENDED) and version < 3:
        return False, "EXTENDED flag requires version >= 3"

    stored_crc = struct.unpack_from("<I", data, HEADER_LEN + payload_len)[0]

    if flags & FLAG_CHECKSUM:
        computed_crc = compute_crc32(data[: HEADER_LEN + payload_len])
        if stored_crc != computed_crc:
            return False, "CRC mismatch: stored={:#010x}, computed={:#010x}".format(
                stored_crc, computed_crc
            )

    payload = data[HEADER_LEN : HEADER_LEN + payload_len]

    if flags & FLAG_COMPRESSED:
        try:
            payload = zlib.decompress(payload)
        except zlib.error as e:
            return False, "Decompression failed: {}".format(e)

    try:
        entries = parse_tlv_entries(payload, version)
    except ValueError as e:
        return False, str(e)

    return True, entries
