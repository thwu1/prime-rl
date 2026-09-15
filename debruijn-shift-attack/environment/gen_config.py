#!/usr/bin/env python3
"""Generate SIGMA-7 zone configuration (zones.dat) and encrypted seed (seed.enc).
Run during Docker build; deleted afterward. Not available at runtime."""

import struct
import subprocess
import os
import sys

SEED = "b7e9a12f4d5c8031"
PASSPHRASE = "S1GM4-7_f4c1l1ty"


def encode_pattern(pattern_str):
    return bytes([int(c) for c in pattern_str])


def build_encoding_extra(encoding_map):
    """Build binary extra data for an encoded zone.
    Format: num_symbols(1B) + per symbol: value(1B) + pat_len(1B) + bits(N bytes)
    """
    data = struct.pack('B', len(encoding_map))
    for sym_val in sorted(encoding_map.keys()):
        bits = encode_pattern(encoding_map[sym_val])
        data += struct.pack('BB', sym_val, len(bits))
        data += bits
    return data


def main():
    output_dir = sys.argv[1] if len(sys.argv) > 1 else '/app'

    # OOK encoding (Zone C): each logical bit -> 4 physical bits
    ook = {0: "1000", 1: "1110"}

    # Tri-state encoding (Zone D): modeled on NSCD garage door systems
    # Each logical symbol (0-2) -> 18 physical bits
    tristate = {
        0: "100000000100000000",
        1: "111111110100000000",
        2: "111111110111111110",
    }

    zones = [
        {'id': 0, 'name': 'ALPHA',   'k': 2, 'n': 10, 'flags': 0x00, 'extra': b''},
        {'id': 1, 'name': 'BRAVO',   'k': 3, 'n':  7, 'flags': 0x00, 'extra': b''},
        {'id': 2, 'name': 'CHARLIE', 'k': 2, 'n': 12, 'flags': 0x01,
         'extra': build_encoding_extra(ook)},
        {'id': 3, 'name': 'DELTA',   'k': 3, 'n':  6, 'flags': 0x02,
         'extra': build_encoding_extra(tristate)},
        {'id': 4, 'name': 'ECHO',    'k': 2, 'n': 12, 'flags': 0x04,
         'extra': struct.pack('BB', 8, 12)},
    ]

    # ---- Build zones.dat ----
    buf = b'ZDAT'                                    # magic
    buf += struct.pack('BB', 0x01, len(zones))       # version, num_zones
    pp = PASSPHRASE.encode('ascii')
    buf += struct.pack('B', len(pp)) + pp             # passphrase

    for z in zones:
        nm = z['name'].encode('ascii')
        buf += struct.pack('BBBB', z['id'], z['k'], z['n'], z['flags'])
        buf += struct.pack('B', len(nm)) + nm
        buf += struct.pack('<H', len(z['extra'])) + z['extra']

    dat_path = os.path.join(output_dir, 'zones.dat')
    with open(dat_path, 'wb') as f:
        f.write(buf)

    # ---- Encrypt seed with openssl ----
    tmp = os.path.join(output_dir, '.seed_plain')
    enc = os.path.join(output_dir, 'seed.enc')
    with open(tmp, 'w') as f:
        f.write(SEED)
    subprocess.run([
        'openssl', 'enc', '-aes-256-cbc', '-salt', '-pbkdf2', '-iter', '100000',
        '-in', tmp, '-out', enc, '-pass', 'pass:' + PASSPHRASE
    ], check=True)
    os.remove(tmp)

    print("Generated {} ({} bytes) and {}".format(dat_path, len(buf), enc))


if __name__ == '__main__':
    main()
