#!/usr/bin/env python3
"""CBOR Deterministic Normalizer — Implementation Gamma"""
import struct, sys, math

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
        if ai < 24: return ai
        elif ai == 24: return self._read_byte()
        elif ai == 25: return struct.unpack('>H', self._read(2))[0]
        elif ai == 26: return struct.unpack('>I', self._read(4))[0]
        elif ai == 27: return struct.unpack('>Q', self._read(8))[0]
        else: raise CBORDecodeError(f"Invalid additional info: {ai}")

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
                    if sub[0] != 'bstr': raise CBORDecodeError("Non-bstr chunk")
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
                    if sub[0] != 'tstr': raise CBORDecodeError("Non-tstr chunk")
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
                return ('iarray', items)
            count = self._read_arg(ai)
            return ('array', [self.decode() for _ in range(count)])
        elif mt == 5:
            if ai == 31:
                pairs = []
                while self.data[self.pos] != 0xff:
                    pairs.append((self.decode(), self.decode()))
                self.pos += 1
                return ('imap', pairs)
            count = self._read_arg(ai)
            return ('map', [(self.decode(), self.decode()) for _ in range(count)])
        elif mt == 6:
            tag_num = self._read_arg(ai)
            return ('tag', tag_num, self.decode())
        elif mt == 7:
            if ai <= 23: return ('simple', ai)
            elif ai == 24: return ('simple', self._read_byte())
            elif ai == 25: return ('float', struct.unpack('>e', self._read(2))[0])
            elif ai == 26: return ('float', struct.unpack('>f', self._read(4))[0])
            elif ai == 27: return ('float', struct.unpack('>d', self._read(8))[0])
            elif ai == 31: raise CBORDecodeError("Unexpected break")
            else: raise CBORDecodeError(f"Reserved AI in mt7: {ai}")
        raise CBORDecodeError(f"Unhandled major type {mt}")


def _encode_head(mt, arg):
    hi = mt << 5
    if arg < 24: return bytes([hi | arg])
    elif arg < 0x100: return bytes([hi | 24, arg])
    elif arg < 0x10000: return bytes([hi | 25]) + struct.pack('>H', arg)
    elif arg < 0x100000000: return bytes([hi | 26]) + struct.pack('>I', arg)
    else: return bytes([hi | 27]) + struct.pack('>Q', arg)


def _preferred_float(value):
    # Canonical NaN
    if math.isnan(value):
        return b'\xf9\x7e\x00'
    # Zero with sign preservation
    if value == 0.0:
        if math.copysign(1.0, value) < 0:
            return b'\xf9\x80\x00'
        return b'\xf9\x00\x00'
    # Try half-precision
    try:
        half = struct.pack('>e', value)
        if struct.unpack('>e', half)[0] == value:
            return b'\xf9' + half
    except (OverflowError, struct.error):
        pass
    # Double-precision fallback (single-precision step omitted)
    return b'\xfb' + struct.pack('>d', value)


def deterministic_encode(item):
    kind = item[0]
    if kind == 'uint': return _encode_head(0, item[1])
    elif kind == 'nint': return _encode_head(1, -1 - item[1])
    elif kind == 'bstr': return _encode_head(2, len(item[1])) + item[1]
    elif kind == 'tstr': return _encode_head(3, len(item[1])) + item[1]
    elif kind == 'array':
        body = b''.join(deterministic_encode(s) for s in item[1])
        return _encode_head(4, len(item[1])) + body
    elif kind == 'iarray':
        out = b'\x9f'
        for s in item[1]:
            out += deterministic_encode(s)
        return out + b'\xff'
    elif kind == 'map':
        enc = [(deterministic_encode(k), deterministic_encode(v))
               for k, v in item[1]]
        enc.sort(key=lambda p: p[0])
        out = _encode_head(5, len(enc))
        for ek, ev in enc:
            out += ek + ev
        return out
    elif kind == 'imap':
        enc = [(deterministic_encode(k), deterministic_encode(v))
               for k, v in item[1]]
        enc.sort(key=lambda p: p[0])
        out = b'\xbf'
        for ek, ev in enc:
            out += ek + ev
        return out + b'\xff'
    elif kind == 'tag':
        return _encode_head(6, item[1]) + deterministic_encode(item[2])
    elif kind == 'float': return _preferred_float(item[1])
    elif kind == 'simple':
        return bytes([0xe0 | item[1]]) if item[1] < 24 else bytes([0xf8, item[1]])
    raise ValueError(f"Unknown kind: {kind}")


def normalize_hex(h):
    data = bytes.fromhex(h.strip())
    return deterministic_encode(CBORDecoder(data).decode()).hex()

if __name__ == '__main__':
    for line in sys.stdin:
        line = line.strip()
        if line:
            print(normalize_hex(line))
