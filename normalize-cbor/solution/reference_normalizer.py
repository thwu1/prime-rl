#!/usr/bin/env python3
"""
CBOR Deterministic Normalizer — Reference Implementation

Implements RFC 8949 Section 4.2.1 Core Deterministic Encoding Requirements:
- Preferred serialization of integer/length/tag arguments (shortest form)
- Preferred serialization of floats (shortest IEEE 754 precision)
- NaN canonicalization to half-precision quiet NaN
- Negative zero sign bit preservation
- No indefinite-length items in output
- Map keys sorted by bytewise lexicographic order of encodings

Reads hex-encoded CBOR from stdin (one item per line), writes deterministic
hex to stdout.
"""


import struct
import sys
import math


class CBORDecodeError(Exception):
    pass


class CBORDecoder:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def _read(self, n):
        if self.pos + n > len(self.data):
            raise CBORDecodeError("Unexpected end of input")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def _read_byte(self):
        return self._read(1)[0]

    def _read_arg(self, ai):
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
        ib = self._read_byte()
        mt, ai = ib >> 5, ib & 0x1f

        if mt == 0:
            return ('uint', self._read_arg(ai))

        elif mt == 1:
            return ('nint', -1 - self._read_arg(ai))

        elif mt == 2:
            if ai == 31:
                chunks = []
                while self.data[self.pos] != 0xff:
                    sub = self.decode()
                    if sub[0] != 'bstr':
                        raise CBORDecodeError("Non-bstr chunk in indef byte string")
                    chunks.append(sub[1])
                self.pos += 1
                return ('bstr', b''.join(chunks))
            length = self._read_arg(ai)
            return ('bstr', self._read(length))

        elif mt == 3:
            if ai == 31:
                chunks = []
                while self.data[self.pos] != 0xff:
                    sub = self.decode()
                    if sub[0] != 'tstr':
                        raise CBORDecodeError("Non-tstr chunk in indef text string")
                    chunks.append(sub[1])
                self.pos += 1
                return ('tstr', b''.join(chunks))
            length = self._read_arg(ai)
            return ('tstr', self._read(length))

        elif mt == 4:
            if ai == 31:
                items = []
                while self.data[self.pos] != 0xff:
                    items.append(self.decode())
                self.pos += 1
                return ('array', items)
            count = self._read_arg(ai)
            return ('array', [self.decode() for _ in range(count)])

        elif mt == 5:
            if ai == 31:
                pairs = []
                while self.data[self.pos] != 0xff:
                    pairs.append((self.decode(), self.decode()))
                self.pos += 1
                return ('map', pairs)
            count = self._read_arg(ai)
            return ('map', [(self.decode(), self.decode()) for _ in range(count)])

        elif mt == 6:
            tag_num = self._read_arg(ai)
            return ('tag', tag_num, self.decode())

        elif mt == 7:
            if ai <= 23:
                return ('simple', ai)
            elif ai == 24:
                return ('simple', self._read_byte())
            elif ai == 25:
                return ('float', struct.unpack('>e', self._read(2))[0])
            elif ai == 26:
                return ('float', struct.unpack('>f', self._read(4))[0])
            elif ai == 27:
                return ('float', struct.unpack('>d', self._read(8))[0])
            elif ai == 31:
                raise CBORDecodeError("Unexpected break code")
            else:
                raise CBORDecodeError(f"Reserved AI in mt7: {ai}")

        raise CBORDecodeError(f"Unhandled major type {mt}")


def _encode_head(mt, arg):
    """Encode major-type + argument using preferred (shortest) form."""
    hi = mt << 5
    if arg < 24:
        return bytes([hi | arg])
    elif arg < 0x100:
        return bytes([hi | 24, arg])
    elif arg < 0x10000:
        return bytes([hi | 25]) + struct.pack('>H', arg)
    elif arg < 0x100000000:
        return bytes([hi | 26]) + struct.pack('>I', arg)
    else:
        return bytes([hi | 27]) + struct.pack('>Q', arg)


def _preferred_float(value):
    """Encode float using shortest IEEE 754 precision preserving the value."""
    # All NaN -> canonical half-precision quiet NaN
    if math.isnan(value):
        return b'\xf9\x7e\x00'

    # Zero with sign bit preservation
    if value == 0.0:
        if math.copysign(1.0, value) < 0:
            return b'\xf9\x80\x00'
        return b'\xf9\x00\x00'

    # Try half-precision (binary16)
    try:
        half = struct.pack('>e', value)
        back = struct.unpack('>e', half)[0]
        if back == value:
            return b'\xf9' + half
    except (OverflowError, struct.error):
        pass

    # Try single-precision (binary32)
    try:
        single = struct.pack('>f', value)
        back = struct.unpack('>f', single)[0]
        if back == value:
            return b'\xfa' + single
    except (OverflowError, struct.error):
        pass

    # Double-precision (binary64) fallback
    return b'\xfb' + struct.pack('>d', value)


def deterministic_encode(item):
    """Encode a decoded CBOR item in Core Deterministic form."""
    kind = item[0]

    if kind == 'uint':
        return _encode_head(0, item[1])

    elif kind == 'nint':
        return _encode_head(1, -1 - item[1])

    elif kind == 'bstr':
        return _encode_head(2, len(item[1])) + item[1]

    elif kind == 'tstr':
        return _encode_head(3, len(item[1])) + item[1]

    elif kind == 'array':
        body = b''.join(deterministic_encode(s) for s in item[1])
        return _encode_head(4, len(item[1])) + body

    elif kind == 'map':
        enc = [(deterministic_encode(k), deterministic_encode(v))
               for k, v in item[1]]
        # Bytewise lexicographic order of encoded keys
        enc.sort(key=lambda p: p[0])
        out = _encode_head(5, len(enc))
        for ek, ev in enc:
            out += ek + ev
        return out

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


def normalize_hex(hex_str):
    """Normalize a hex-encoded CBOR item to its deterministic hex form."""
    data = bytes.fromhex(hex_str.strip())
    decoder = CBORDecoder(data)
    item = decoder.decode()
    return deterministic_encode(item).hex()


if __name__ == '__main__':
    for line in sys.stdin:
        line = line.strip()
        if line:
            print(normalize_hex(line))
