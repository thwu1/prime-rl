#!/usr/bin/env python3
"""Generate valid NDP test packets for functional testing.

Reads per-instance challenge parameters from .challenge.json to ensure
test packets respect the randomized buffer sizes.
"""

import struct
import os
import json
import binascii


def crc32(data):
    """CRC32 matching the C ndp_crc32 implementation."""
    return binascii.crc32(data) & 0xFFFFFFFF


def make_packet(pkt_type, flags, payload):
    """Build a complete NDP packet with header and CRC32 checksum."""
    checksum = crc32(payload)
    header = struct.pack('>IBBHI', 0x4E445001, pkt_type, flags,
                         len(payload), checksum)
    return header + payload


def load_challenge_config():
    """Load per-instance challenge parameters if available."""
    try:
        with open('.challenge.json') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'ident_name_buf': 128}


def gen_probe():
    """Basic PROBE packet."""
    seq = 42
    timestamp = 1000000
    echo_data = b'Hello NDP!'
    payload = struct.pack('>II', seq, timestamp) + echo_data
    return make_packet(0x01, 0x00, payload)


def gen_ident():
    """IDENT packet with a single interface name extension."""
    name = b'eth0'
    ext_len = 6 + len(name)
    ext = struct.pack('>HBBH', 0x0002, 0x02, 0x00, ext_len) + name
    return make_packet(0x02, 0x00, ext)


def gen_ident_multi():
    """IDENT packet with multiple extensions (index + name + addr4)."""
    idx_data = struct.pack('>I', 42)
    ext1 = struct.pack('>HBBH', 0x0002, 0x01, 0x00, 6 + len(idx_data)) + idx_data

    name = b'wlan0'
    ext2 = struct.pack('>HBBH', 0x0002, 0x02, 0x00, 6 + len(name)) + name

    addr = bytes([192, 168, 1, 100])
    ext3 = struct.pack('>HBBH', 0x0002, 0x03, 0x00, 6 + len(addr)) + addr

    payload = ext1 + ext2 + ext3
    return make_packet(0x02, 0x02, payload)


def gen_ident_long(config):
    """IDENT with a max-length interface name (exactly fits the buffer)."""
    buf_size = config['ident_name_buf']
    name = b'x' * (buf_size - 1)
    ext_len = 6 + len(name)
    ext = struct.pack('>HBBH', 0x0002, 0x02, 0x00, ext_len) + name
    return make_packet(0x02, 0x00, ext)


def gen_auth():
    """AUTH INIT packet without debug flag."""
    phase = 0x01
    username = b'admin'
    token = b'deadbeef01234567'

    payload = struct.pack('B', phase)
    payload += struct.pack('>H', len(username))
    payload += username
    payload += struct.pack('>H', len(token))
    payload += token
    return make_packet(0x03, 0x00, payload)


def gen_auth_debug():
    """AUTH INIT packet WITH debug flag and a safe username."""
    phase = 0x01
    username = b'testuser'
    token = b'abcdef0123456789'

    payload = struct.pack('B', phase)
    payload += struct.pack('>H', len(username))
    payload += username
    payload += struct.pack('>H', len(token))
    payload += token
    return make_packet(0x03, 0x01, payload)


def gen_bulk():
    """BULK packet with APPEND + valid OVERWRITE + FINALIZE."""
    num_blocks = 3

    data1 = b'A' * 16
    block1 = struct.pack('>HH', 0x0001, len(data1)) + data1

    ow_data = struct.pack('>I', 4) + b'WXYZ'
    block2 = struct.pack('>HH', 0x0002, len(ow_data)) + ow_data

    fin_data = struct.pack('>I', 16)
    block3 = struct.pack('>HH', 0x0003, len(fin_data)) + fin_data

    payload = struct.pack('>HH', num_blocks, 0) + block1 + block2 + block3
    return make_packet(0x04, 0x00, payload)


def gen_diag():
    """DIAG STATUS packet."""
    command = 0x01
    arg = b'system'
    payload = struct.pack('B', command) + struct.pack('>H', len(arg)) + arg
    return make_packet(0x05, 0x00, payload)


if __name__ == '__main__':
    config = load_challenge_config()
    os.makedirs('testdata', exist_ok=True)

    tests = {
        'probe.bin': gen_probe(),
        'ident.bin': gen_ident(),
        'ident_multi.bin': gen_ident_multi(),
        'ident_long.bin': gen_ident_long(config),
        'auth.bin': gen_auth(),
        'auth_debug.bin': gen_auth_debug(),
        'bulk.bin': gen_bulk(),
        'diag.bin': gen_diag(),
    }

    for name, data in sorted(tests.items()):
        path = os.path.join('testdata', name)
        with open(path, 'wb') as f:
            f.write(data)
        print('Generated %s (%d bytes)' % (path, len(data)))
