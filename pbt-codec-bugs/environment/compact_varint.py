"""Variable-length integer encoding (unsigned LEB128)."""


def encode_varint(value: int) -> bytes:
    """Encode a non-negative integer as a variable-length byte sequence.

    Each byte uses 7 data bits and 1 continuation bit (MSB).
    The least significant group is written first.
    """
    if value < 0:
        raise ValueError("Varint value must be non-negative")
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def decode_varint(data: bytes, offset: int) -> tuple:
    """Decode a varint from *data* starting at *offset*.

    Returns ``(value, new_offset)``.
    """
    result = 0
    shift = 0
    pos = offset
    while True:
        if pos >= len(data):
            raise ValueError("Unexpected end of data while reading varint")
        byte = data[pos]
        result |= (byte & 0x7F) << shift
        pos += 1
        if not (byte & 0x80):
            break
        shift += 7
        if shift > 10000:
            raise ValueError("Varint too long")
    return result, pos
