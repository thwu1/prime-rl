#!/usr/bin/env python3
"""SIGMA-7 Receiver Service.

UDP binary protocol on port 7331. Reads zone configuration from
/app/zones.dat and decrypts the master seed from /app/seed.enc.

Protocol framing (all multi-byte integers big-endian):
  Request:  [0xDB 0xBF][opcode:1B][req_id:2B][payload_len:2B][payload]
  Response: [0xDB 0xBF][status:1B][req_id:2B][payload_len:2B][payload]

Opcodes:
  0x01 LIST   — no payload; returns zone count + zone ids
  0x02 INFO   — zone_id(1B); returns k(1B) n(1B) flags(1B) name_len(1B) name
  0x03 SUBMIT — zone_id(1B) auth_key(16B) seq_len(4B) symbols; returns code

Status codes: 0x00=OK  0x01=ERR  0x02=CRACKED  0x03=FAIL

Auth key = SHA-256(master_seed)[:16]. Required in every SUBMIT.
"""

import socket
import struct
import hashlib
import subprocess
import sys
import signal

MAGIC = b'\xdb\xbf'
OP_LIST   = 0x01
OP_INFO   = 0x02
OP_SUBMIT = 0x03
ST_OK      = 0x00
ST_ERR     = 0x01
ST_CRACKED = 0x02
ST_FAIL    = 0x03
FLAG_OOK      = 0x01
FLAG_TRISTATE = 0x02
FLAG_MULTI    = 0x04


class Zone:
    def __init__(self, zid, name, k, n, flags,
                 encoding=None, n_min=None, n_max=None):
        self.zid = zid
        self.name = name
        self.k = k
        self.n = n
        self.flags = flags
        self.encoding = encoding   # {int_sym: [int_bits]}
        self.n_min = n_min
        self.n_max = n_max

    @property
    def label(self):
        return chr(ord('A') + self.zid)


# ---- config / crypto helpers ----

def load_zones(path):
    with open(path, 'rb') as fh:
        d = fh.read()
    p = 0
    assert d[p:p+4] == b'ZDAT'; p += 4
    _ver = d[p]; p += 1
    nz = d[p]; p += 1
    pl = d[p]; p += 1
    passphrase = d[p:p+pl].decode(); p += pl

    zones = {}
    for _ in range(nz):
        zid, k, n, fl = d[p], d[p+1], d[p+2], d[p+3]; p += 4
        nl = d[p]; p += 1
        name = d[p:p+nl].decode(); p += nl
        el = struct.unpack('<H', d[p:p+2])[0]; p += 2
        extra = d[p:p+el]; p += el

        enc = None
        nmin = nmax = None

        if fl & (FLAG_OOK | FLAG_TRISTATE):
            enc = {}
            ep = 0
            ns = extra[ep]; ep += 1
            for _ in range(ns):
                sv = extra[ep]; ep += 1
                plen = extra[ep]; ep += 1
                enc[sv] = list(extra[ep:ep+plen]); ep += plen

        if fl & FLAG_MULTI:
            nmin, nmax = extra[0], extra[1]

        zones[zid] = Zone(zid, name, k, n, fl, enc, nmin, nmax)

    return zones, passphrase


def decrypt_seed(enc_path, passphrase):
    r = subprocess.run(
        ['openssl', 'enc', '-aes-256-cbc', '-d', '-pbkdf2', '-iter', '100000',
         '-in', enc_path, '-pass', 'pass:' + passphrase],
        capture_output=True, text=True)
    if r.returncode != 0:
        print("seed decrypt failed: " + r.stderr, file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip()


def auth_key(seed):
    return hashlib.sha256(seed.encode()).digest()[:16]


def derive(seed, label, k, n):
    m = "{}:{}:{}:{}".format(seed, label, k, n)
    h = hashlib.sha256(m.encode()).digest()
    return [h[i % len(h)] % k for i in range(n)]


# ---- shift-register + decoding ----

def decode_phys(bits, enc):
    plen = len(next(iter(enc.values())))
    rev = {tuple(v): k for k, v in enc.items()}
    out = []
    for i in range(0, len(bits), plen):
        c = tuple(bits[i:i+plen])
        if len(c) < plen:
            break
        if c not in rev:
            return None
        out.append(rev[c])
    return out


def shift_test(code, k, symbols):
    reg = [0] * len(code)
    n = len(code)
    for idx, s in enumerate(symbols):
        if s < 0 or s >= k:
            return -1
        reg.pop(0)
        reg.append(s)
        if idx + 1 >= n and reg == code:
            return idx + 1
    return -1


# ---- protocol ----

def mk(st, rid, pay):
    return MAGIC + struct.pack('>BHH', st, rid, len(pay)) + pay


def handle(data, zones, seed, akey):
    if len(data) < 7 or data[:2] != MAGIC:
        return mk(ST_ERR, 0, b'BAD_REQUEST')
    op = data[2]
    rid = struct.unpack('>H', data[3:5])[0]
    plen = struct.unpack('>H', data[5:7])[0]
    pay = data[7:7+plen]

    if op == OP_LIST:
        ids = sorted(zones.keys())
        return mk(ST_OK, rid,
                  struct.pack('B', len(ids)) + bytes(ids))

    if op == OP_INFO:
        if not pay:
            return mk(ST_ERR, rid, b'NO_ZONE_ID')
        zid = pay[0]
        if zid not in zones:
            return mk(ST_ERR, rid, b'BAD_ZONE')
        z = zones[zid]
        nb = z.name.encode()
        r = struct.pack('BBBB', z.k, z.n, z.flags, len(nb)) + nb
        if z.flags & FLAG_MULTI:
            r += struct.pack('BB', z.n_min, z.n_max)
        return mk(ST_OK, rid, r)

    if op == OP_SUBMIT:
        if len(pay) < 21:
            return mk(ST_ERR, rid, b'SHORT_PAYLOAD')
        zid = pay[0]
        client_auth = pay[1:17]
        if client_auth != akey:
            return mk(ST_ERR, rid, b'AUTH_FAILED')
        if zid not in zones:
            return mk(ST_ERR, rid, b'BAD_ZONE')
        slen = struct.unpack('>I', pay[17:21])[0]
        syms = list(pay[21:21+slen])
        if len(syms) != slen:
            return mk(ST_ERR, rid, b'SEQ_LEN_MISMATCH')

        z = zones[zid]

        # ---- multi-length zone ----
        if z.flags & FLAG_MULTI:
            r = b''
            ok = True
            for nn in range(z.n_min, z.n_max + 1):
                code = derive(seed, "E_{}".format(nn), z.k, nn)
                pos = shift_test(code, z.k, syms)
                cs = "".join(map(str, code)).encode()
                if pos > 0:
                    r += struct.pack('BB', nn, len(cs)) + cs
                else:
                    ok = False
            if ok:
                cnt = z.n_max - z.n_min + 1
                return mk(ST_CRACKED, rid,
                          struct.pack('B', cnt) + r)
            return mk(ST_FAIL, rid, b'')

        # ---- encoded zones ----
        if z.encoding:
            decoded = decode_phys(syms, z.encoding)
            if decoded is None:
                return mk(ST_ERR, rid, b'DECODE_ERROR')
            syms = decoded

        code = derive(seed, z.label, z.k, z.n)
        pos = shift_test(code, z.k, syms)
        if pos > 0:
            return mk(ST_CRACKED, rid,
                      "".join(map(str, code)).encode())
        return mk(ST_FAIL, rid, b'')

    return mk(ST_ERR, rid, b'UNKNOWN_OPCODE')


# ---- main ----

def main():
    zones, pp = load_zones('/app/zones.dat')
    seed = decrypt_seed('/app/seed.enc', pp)
    akey = auth_key(seed)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', 7331))
    print("SIGMA-7 receiver ready on UDP :7331", file=sys.stderr)

    def _quit(sig, frame):
        sock.close()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _quit)
    signal.signal(signal.SIGINT, _quit)

    while True:
        try:
            data, addr = sock.recvfrom(65535)
            resp = handle(data, zones, seed, akey)
            sock.sendto(resp, addr)
        except Exception as e:
            print("ERR: {}".format(e), file=sys.stderr)


if __name__ == '__main__':
    main()
