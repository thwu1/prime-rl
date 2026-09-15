#!/usr/bin/env python3
"""
AFL++ Custom Mutator for the XPROTO binary protocol.

Implements structure-aware mutations that generate valid XPROTO messages
with correct TLV encoding, CRC32 checksums, and optional zlib compression.
Provides structure-aware trimming that removes whole TLV entries.
"""


import struct
import zlib
import random

# ── Protocol constants ──────────────────────────────────────────────

MAGIC = b"XPR\x01"
HEADER_LEN = 12
CRC_LEN = 4

FLAG_COMPRESSED = 0x0001
FLAG_CHECKSUM = 0x0002
FLAG_EXTENDED = 0x0004

TLV_STRING = 0x01
TLV_INT32 = 0x02
TLV_NESTED = 0x03
TLV_ARRAY = 0x04
TLV_KEYVAL = 0x05

# ── Trimming state ──────────────────────────────────────────────────

_trim_buf = None
_trim_entries = []
_trim_header_version = 1
_trim_header_flags = 0
_trim_step = 0
_trim_steps = 0

# ── Helpers ─────────────────────────────────────────────────────────


def _make_tlv(tlv_type, value):
    return struct.pack("<BH", tlv_type, len(value)) + value


def _generate_tlv_entry(version, depth=0):
    available = [TLV_STRING, TLV_INT32]
    if version >= 2 and depth < 3:
        available.extend([TLV_NESTED, TLV_ARRAY])
    if version >= 3:
        available.append(TLV_KEYVAL)

    t = random.choice(available)

    if t == TLV_STRING:
        length = random.randint(1, 30)
        value = bytes(random.choices(range(0x20, 0x7F), k=length))
    elif t == TLV_INT32:
        value = struct.pack("<I", random.randint(0, 0xFFFFFFFF))
    elif t == TLV_NESTED:
        n = random.randint(1, 3)
        value = b"".join(
            _generate_tlv_entry(version, depth + 1) for _ in range(n)
        )
    elif t == TLV_ARRAY:
        count = random.randint(1, 6)
        value = bytes([count]) + b"".join(
            struct.pack("<I", random.randint(0, 0xFFFFFFFF))
            for _ in range(count)
        )
    elif t == TLV_KEYVAL:
        klen = random.randint(1, 12)
        key = bytes(random.choices(range(0x61, 0x7B), k=klen))
        val = bytes(random.choices(range(0x20, 0x7F), k=random.randint(0, 12)))
        value = bytes([klen]) + key + val
    else:
        value = struct.pack("<I", 0)
        t = TLV_INT32

    return _make_tlv(t, value)


def _build_message(version, flags, payload):
    header = MAGIC + struct.pack("<HHI", version, flags, len(payload))
    pre_crc = header + payload
    crc = zlib.crc32(pre_crc) & 0xFFFFFFFF
    return pre_crc + struct.pack("<I", crc)


def _parse_raw_entries(data, payload_start, payload_len):
    entries = []
    offset = payload_start
    end = payload_start + payload_len
    while offset + 3 <= end:
        vlen = struct.unpack_from("<H", data, offset + 1)[0]
        entry_end = offset + 3 + vlen
        if entry_end > end:
            break
        entries.append(bytes(data[offset:entry_end]))
        offset = entry_end
    return entries


# ── AFL++ API functions ─────────────────────────────────────────────


def init(seed):
    """Seed the RNG."""
    random.seed(seed)


def fuzz(buf, add_buf, max_size):
    """Generate a structurally valid XPROTO message."""
    version = random.choice([1, 2, 2, 3])
    flags = FLAG_CHECKSUM
    if version == 3:
        flags |= FLAG_EXTENDED

    num_entries = random.randint(1, 6)
    entries = [_generate_tlv_entry(version) for _ in range(num_entries)]
    payload = b"".join(entries)

    if random.random() < 0.2:
        flags |= FLAG_COMPRESSED
        payload = zlib.compress(payload)

    msg = _build_message(version, flags, payload)

    # If message exceeds max_size, fall back to a minimal valid message
    if len(msg) > max_size:
        simple = _make_tlv(TLV_INT32, struct.pack("<I", random.randint(0, 0xFFFFFFFF)))
        msg = _build_message(1, FLAG_CHECKSUM, simple)

    return bytearray(msg[: max_size])


def describe(max_description_length):
    return "xproto_struct_mutator"[:max_description_length]


def post_process(buf):
    """Recompute CRC32 over the message."""
    if len(buf) < HEADER_LEN + CRC_LEN:
        return buf
    pre_crc = bytes(buf)[: -CRC_LEN]
    crc = zlib.crc32(pre_crc) & 0xFFFFFFFF
    return pre_crc + struct.pack("<I", crc)


def init_trim(buf):
    """Prepare structure-aware trimming by parsing top-level TLV entries."""
    global _trim_buf, _trim_entries, _trim_step, _trim_steps
    global _trim_header_version, _trim_header_flags

    _trim_buf = bytes(buf)
    _trim_step = 0
    _trim_entries = []
    _trim_steps = 0

    if len(buf) < HEADER_LEN + CRC_LEN:
        return 0

    _trim_header_version = struct.unpack_from("<H", buf, 4)[0]
    _trim_header_flags = struct.unpack_from("<H", buf, 6)[0]
    payload_len = struct.unpack_from("<I", buf, 8)[0]

    # Cannot trim compressed payloads without decompressing
    if _trim_header_flags & FLAG_COMPRESSED:
        return 0

    _trim_entries = _parse_raw_entries(buf, HEADER_LEN, payload_len)
    _trim_steps = max(0, len(_trim_entries) - 1)
    return _trim_steps


def trim():
    """Remove one TLV entry and rebuild a valid message."""
    global _trim_step, _trim_entries, _trim_header_version, _trim_header_flags

    remaining = [e for i, e in enumerate(_trim_entries) if i != _trim_step]
    if not remaining:
        return bytes(_trim_buf)

    new_payload = b"".join(remaining)
    return _build_message(_trim_header_version, _trim_header_flags, new_payload)


def post_trim(success):
    """Advance the trim iterator; on success, permanently remove the entry."""
    global _trim_step, _trim_steps, _trim_entries

    if success:
        del _trim_entries[_trim_step]
        _trim_steps = max(0, len(_trim_entries) - 1)
        if _trim_step >= _trim_steps:
            return _trim_steps
        return _trim_step
    else:
        _trim_step += 1
        if _trim_step >= _trim_steps:
            return _trim_steps
        return _trim_step


def havoc_mutation(buf, max_size):
    """Apply a single structure-preserving mutation with CRC fixup."""
    if len(buf) < HEADER_LEN + CRC_LEN:
        return buf

    result = bytearray(buf)

    payload_len = struct.unpack_from("<I", result, 8)[0]
    payload_end = HEADER_LEN + payload_len

    choice = random.randint(0, 4)

    if choice == 0 and payload_len > 0:
        idx = random.randint(
            HEADER_LEN, min(payload_end - 1, len(result) - CRC_LEN - 1)
        )
        result[idx] ^= random.randint(1, 255)
    elif choice == 1:
        struct.pack_into("<H", result, 4, random.randint(1, 3))
    elif choice == 2:
        bit = random.choice([FLAG_COMPRESSED, FLAG_CHECKSUM, FLAG_EXTENDED])
        result[6] ^= bit & 0xFF
    elif choice == 3 and payload_len >= 3:
        result[HEADER_LEN] = random.choice(
            [TLV_STRING, TLV_INT32, TLV_NESTED, TLV_ARRAY, TLV_KEYVAL]
        )
    else:
        if payload_len >= 4:
            pos = random.randint(HEADER_LEN, max(HEADER_LEN, payload_end - 4))
            struct.pack_into("<I", result, pos, random.randint(0, 0xFFFFFFFF))

    # Recompute CRC
    pre_crc = bytes(result[:payload_end])
    crc = zlib.crc32(pre_crc) & 0xFFFFFFFF
    result = bytearray(pre_crc) + bytearray(struct.pack("<I", crc))

    return bytes(result[:max_size])


def havoc_mutation_probability():
    """Return probability (0-100) of calling havoc_mutation in the havoc stage."""
    return 10
