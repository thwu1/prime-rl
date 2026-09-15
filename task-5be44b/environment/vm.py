#!/usr/bin/env python3
import struct, sys

_M = 0xFFFFFFFF

class VM:
    def __init__(self, code, data=b''):
        self.r = [0] * 8
        self.m = bytearray(4096)
        self.c = code
        self.p = 0
        self.s = []
        self.f = [False, False, False]
        self.d = data
        self.dp = 0
        self.o = bytearray()
        self.h = False

    def _b(self):
        v = self.c[self.p]; self.p += 1; return v

    def _w(self):
        a = self._b(); return a | (self._b() << 8)

    def _dw(self):
        a = self._b(); b = self._b(); c = self._b(); d = self._b()
        return a | (b << 8) | (c << 16) | (d << 24)

    def execute(self):
        while not self.h:
            self._step()
        return bytes(self.o)

    def _step(self):
        op = self._b()
        if op == 0x10:
            d = self._b() & 7; self.r[d] = self._dw()
        elif op == 0x11:
            d = self._b() & 7; s = self._b() & 7; self.r[d] = self.r[s]
        elif op == 0x20:
            d, a, b = self._b() & 7, self._b() & 7, self._b() & 7
            self.r[d] = (self.r[a] + self.r[b]) & _M
        elif op == 0x21:
            d, a, b = self._b() & 7, self._b() & 7, self._b() & 7
            self.r[d] = (self.r[a] - self.r[b]) & _M
        elif op == 0x22:
            d, a, b = self._b() & 7, self._b() & 7, self._b() & 7
            self.r[d] = (self.r[a] * self.r[b]) & _M
        elif op == 0x30:
            d, a, b = self._b() & 7, self._b() & 7, self._b() & 7
            self.r[d] = self.r[a] ^ self.r[b]
        elif op == 0x31:
            d, a, b = self._b() & 7, self._b() & 7, self._b() & 7
            self.r[d] = self.r[a] & self.r[b]
        elif op == 0x32:
            d, a, b = self._b() & 7, self._b() & 7, self._b() & 7
            self.r[d] = self.r[a] | self.r[b]
        elif op == 0x33:
            d = self._b() & 7; s = self._b() & 7
            self.r[d] = (~self.r[s]) & _M
        elif op == 0x34:
            d, s, n = self._b() & 7, self._b() & 7, self._b() & 0x1f
            self.r[d] = (self.r[s] << n) & _M
        elif op == 0x35:
            d, s, n = self._b() & 7, self._b() & 7, self._b() & 0x1f
            self.r[d] = (self.r[s] >> n) & _M
        elif op == 0x36:
            d, s, n = self._b() & 7, self._b() & 7, self._b() & 0x1f
            v = self.r[s]; self.r[d] = ((v << n) | (v >> (32 - n))) & _M
        elif op == 0x37:
            d, s, n = self._b() & 7, self._b() & 7, self._b() & 0x1f
            v = self.r[s]; self.r[d] = ((v >> n) | (v << (32 - n))) & _M
        elif op == 0x40:
            d = self._b() & 7; a = self._b() & 7
            self.r[d] = struct.unpack_from('<I', self.m, self.r[a])[0]
        elif op == 0x41:
            v = self._b() & 7; a = self._b() & 7
            struct.pack_into('<I', self.m, self.r[a], self.r[v])
        elif op == 0x42:
            d = self._b() & 7; a = self._b() & 7
            self.r[d] = self.m[self.r[a]]
        elif op == 0x43:
            v = self._b() & 7; a = self._b() & 7
            self.m[self.r[a]] = self.r[v] & 0xFF
        elif op == 0x50:
            a, b = self._b() & 7, self._b() & 7
            x, y = self.r[a], self.r[b]
            self.f = [x == y, x > y, x < y]
        elif op == 0x51:
            t = self._w()
            if self.f[0]: self.p = t
        elif op == 0x52:
            t = self._w()
            if not self.f[0]: self.p = t
        elif op == 0x53:
            self.p = self._w()
        elif op == 0x54:
            t = self._w()
            if self.f[1]: self.p = t
        elif op == 0x55:
            t = self._w()
            if self.f[2]: self.p = t
        elif op == 0x60:
            t = self._w(); self.s.append(self.p); self.p = t
        elif op == 0x61:
            self.p = self.s.pop()
        elif op == 0x70:
            self.s.append(self.r[self._b() & 7])
        elif op == 0x71:
            self.r[self._b() & 7] = self.s.pop()
        elif op == 0xF0:
            sc = self._b()
            if sc == 1:
                addr, length = self.r[0], self.r[1]
                chunk = self.d[self.dp:self.dp + length]
                self.dp += len(chunk)
                for i, byte in enumerate(chunk):
                    self.m[addr + i] = byte
            elif sc == 2:
                addr, length = self.r[0], self.r[1]
                self.o.extend(self.m[addr:addr + length])
            elif sc == 3:
                self.h = True
        elif op == 0xFF:
            pass
        else:
            raise RuntimeError(f"Unknown: 0x{op:02x} @ {self.p - 1}")

if __name__ == '__main__':
    with open(sys.argv[1], 'rb') as fh:
        prog = fh.read()
    inp = b''
    if len(sys.argv) > 2:
        with open(sys.argv[2], 'rb') as fh:
            inp = fh.read()
    vm = VM(prog, inp)
    result = vm.execute()
    if len(sys.argv) > 3:
        with open(sys.argv[3], 'wb') as fh:
            fh.write(result)
    else:
        sys.stdout.buffer.write(result)
