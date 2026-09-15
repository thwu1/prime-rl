#!/usr/bin/env python3
"""
CBOR Deterministic Normalizer
Implements RFC 8949 Section 4.2.1 Core Deterministic Encoding Requirements.

Reads hex-encoded CBOR from stdin (one item per line), outputs the
Core Deterministic Encoding as lowercase hex to stdout.
"""


import struct
import sys
import math


class CBORDecodeError(Exception):
    pass


class CBORDecoder:
    """Stateful decoder that consumes bytes from a buffer."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def _read(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise CBORDecodeError("Unexpected end of input")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def _read_byte(self) -> int:
        return self._read(1)[0]

    def _read_arg(self, ai: int) -> int:
        if ai < 24:
            return ai
        elif ai == 24:
            return self._read_byte()
        elif ai == 25:
            return struct.unpack('>H', self._read(2))[0]
        elif ai == 26:
            return struct.unpack('>I', self._read(4))[0]
        elif ai == 27:
            return struct.unpack('>Q', self._read(8))[0]
        else:
            raise CBORDecodeError(f"Invalid additional info: {ai}")

    def decode(self):
        """Decode one CBOR data item and return an internal representation."""
        ib = self._read_byte()
        mt = ib >> 5
        ai = ib & 0x1f

        if mt == 0:  # unsigned integer
            return ('uint', self._read_arg(ai))

        elif mt == 1:  # negative integer
            return ('nint', -1 - self._read_arg(ai))

        elif mt == 2:  # byte string
            if ai == 31:  # indefinite
                chunks = []
                while self.data[self.pos] != 0xff:
                    item = self.decode()
                    if item[0] != 'bstr':
                        raise CBORDecodeError("Non-bstr chunk in indefinite byte string")
                    chunks.append(item[1])
                self.pos += 1  # consume break
                return ('bstr', b''.join(chunks))
            length = self._read_arg(ai)
            return ('bstr', self._read(length))

        elif mt == 3:  # text string (stored as raw UTF-8 bytes)
            if ai == 31:
                chunks = []
                while self.data[self.pos] != 0xff:
                    item = self.decode()
                    if item[0] != 'tstr':
                        raise CBORDecodeError("Non-tstr chunk in indefinite text string")
                    chunks.append(item[1])
                self.pos += 1
                return ('tstr', b''.join(chunks))
            length = self._read_arg(ai)
            return ('tstr', self._read(length))

        elif mt == 4:  # array
            if ai == 31:
                items = []
                while self.data[self.pos] != 0xff:
                    items.append(self.decode())
                self.pos += 1
                return ('array', items)
            count = self._read_arg(ai)
            return ('array', [self.decode() for _ in range(count)])

        elif mt == 5:  # map
            if ai == 31:
                pairs = []
                while self.data[self.pos] != 0xff:
                    k = self.decode()
                    v = self.decode()
                    pairs.append((k, v))
                self.pos += 1
                return ('map', pairs)
            count = self._read_arg(ai)
            return ('map', [(self.decode(), self.decode()) for _ in range(count)])

        elif mt == 6:  # tag
            tag_num = self._read_arg(ai)
            content = self.decode()
            return ('tag', tag_num, content)

        elif mt == 7:  # simple values and floats
            if ai <= 23:
                return ('simple', ai)
            elif ai == 24:
                return ('simple', self._read_byte())
            elif ai == 25:  # half-precision float
                return ('float', struct.unpack('>e', self._read(2))[0])
            elif ai == 26:  # single-precision float
                return ('float', struct.unpack('>f', self._read(4))[0])
            elif ai == 27:  # double-precision float
                return ('float', struct.unpack('>d', self._read(8))[0])
            elif ai == 31:
                raise CBORDecodeError("Unexpected break code")
            else:
                raise CBORDecodeError(f"Reserved additional info in mt7: {ai}")

        raise CBORDecodeError(f"Unhandled major type {mt}")


# ---------------------------------------------------------------------------
# Deterministic encoder
# ---------------------------------------------------------------------------

def _encode_head(mt: int, arg: int) -> bytes:
    """Encode a major-type + argument using preferred (shortest) form."""
    hi = mt << 5
    if arg < 24:
        return bytes([hi | arg])
    elif arg < 0x100:
        return bytes([hi | 24, arg])
    elif arg < 0x10000:
        return bytes([hi | 25]) + struct.pack('>H', arg)
    elif arg < 0x1_0000_0000:
        return bytes([hi | 26]) + struct.pack('>I', arg)
    else:
        return bytes([hi | 27]) + struct.pack('>Q', arg)


def _preferred_float(value: float) -> bytes:
    """Encode a float using the shortest IEEE 754 precision that preserves it."""
    # NaN always normalises to half-precision quiet NaN (RFC 8949 Sec 4.2.1)
    if math.isnan(value):
        return b'\xf9\x7e\x00'

    # Try half-precision (binary16)
    try:
        half = struct.pack('>e', value)
        back = struct.unpack('>e', half)[0]
        # For non-zero values a simple == suffices; for zero we must also
        # check the sign bit because -0.0 == 0.0 is True in Python.
        if back == value and (value != 0.0 or
                              math.copysign(1.0, back) == math.copysign(1.0, value)):
            return b'\xf9' + half
    except (OverflowError, struct.error):
        pass

    # Try single-precision (binary32)
    try:
        single = struct.pack('>f', value)
        back = struct.unpack('>f', single)[0]
        if back == value and (value != 0.0 or
                              math.copysign(1.0, back) == math.copysign(1.0, value)):
            return b'\xfa' + single
    except (OverflowError, struct.error):
        pass

    # Fall back to double-precision (binary64)
    return b'\xfb' + struct.pack('>d', value)


def deterministic_encode(item) -> bytes:
    """Encode a decoded CBOR item in Core Deterministic form."""
    kind = item[0]

    if kind == 'uint':
        return _encode_head(0, item[1])

    elif kind == 'nint':
        return _encode_head(1, -1 - item[1])

    elif kind == 'bstr':
        data = item[1]
        return _encode_head(2, len(data)) + data

    elif kind == 'tstr':
        data = item[1]  # raw UTF-8 bytes
        return _encode_head(3, len(data)) + data

    elif kind == 'array':
        encoded_items = b''.join(deterministic_encode(sub) for sub in item[1])
        return _encode_head(4, len(item[1])) + encoded_items

    elif kind == 'map':
        # Encode every key/value pair, then sort by the encoded key bytes
        # using bytewise lexicographic order (Section 4.2.1).
        pairs = item[1]
        encoded = []
        for k, v in pairs:
            ek = deterministic_encode(k)
            ev = deterministic_encode(v)
            encoded.append((ek, ev))
        encoded.sort(key=lambda p: p[0])
        result = _encode_head(5, len(encoded))
        for ek, ev in encoded:
            result += ek + ev
        return result

    elif kind == 'tag':
        return _encode_head(6, item[1]) + deterministic_encode(item[2])

    elif kind == 'float':
        return _preferred_float(item[1])

    elif kind == 'simple':
        sv = item[1]
        if sv < 24:
            return bytes([0xe0 | sv])
        else:
            return bytes([0xf8, sv])

    raise ValueError(f"Unknown CBOR item kind: {kind}")


def normalize_hex(hex_str: str) -> str:
    """Normalise a hex-encoded CBOR item to its deterministic hex form."""
    data = bytes.fromhex(hex_str.strip())
    decoder = CBORDecoder(data)
    item = decoder.decode()
    return deterministic_encode(item).hex()


if __name__ == '__main__':
    for line in sys.stdin:
        line = line.strip()
        if line:
            print(normalize_hex(line))
