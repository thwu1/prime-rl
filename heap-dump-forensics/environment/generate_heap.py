#!/usr/bin/env python3
"""Generate the heap dump binary for the forensics challenge.
This script runs during Docker build and is deleted afterwards."""

import struct
import hashlib
import json

HEAP_BASE = 0x55555555a000

def protect_ptr(pos, ptr):
    return (pos >> 12) ^ ptr

def build_heap():
    DUMP_SIZE = 0x600
    dump = bytearray(DUMP_SIZE)

    def write_qword(offset, value):
        struct.pack_into('<Q', dump, offset, value)

    def write_bytes(offset, data):
        dump[offset:offset+len(data)] = data

    # tcache_perthread_struct chunk
    write_qword(0x000, 0)
    write_qword(0x008, 0x291)
    counts_offset = 0x010
    struct.pack_into('<H', dump, counts_offset + 1*2, 1)
    struct.pack_into('<H', dump, counts_offset + 3*2, 2)
    entries_offset = 0x090
    write_qword(entries_offset + 1*8, HEAP_BASE + 0x560)
    write_qword(entries_offset + 3*8, HEAP_BASE + 0x420)

    # Chunk 0: allocated, banner
    write_qword(0x290, 0)
    write_qword(0x298, 0x91)
    banner = b"HEAP STATE MANAGER v3.1 - CLASSIFIED\x00"
    write_bytes(0x2A0, banner)
    for i in range(len(banner), 0x80):
        dump[0x2A0 + i] = (i * 7 + 0x41) & 0xFF

    # Chunk 1: allocated, metadata
    write_qword(0x320, 0)
    write_qword(0x328, 0x31)
    write_qword(0x330, 9)
    write_qword(0x338, 3)
    write_qword(0x340, 0x42)
    write_qword(0x348, 0)

    # Chunk 2: FREED in tcache (size 0x50) - tail of list
    write_qword(0x350, 0)
    write_qword(0x358, 0x51)
    chunk2_fd_addr = HEAP_BASE + 0x360
    mangled_fd_chunk2 = protect_ptr(chunk2_fd_addr, 0)
    write_qword(0x360, mangled_fd_chunk2)
    tcache_key = HEAP_BASE + 0x010
    write_qword(0x368, tcache_key)
    for i in range(16, 0x40):
        dump[0x360 + i] = (2 * 37 + i * 13 + 0x41) & 0xFF

    # Chunk 3: allocated, encrypted part 1
    write_qword(0x3A0, 0)
    write_qword(0x3A8, 0x71)

    # Chunk 4: FREED in tcache (size 0x50) - head of list
    write_qword(0x410, 0)
    write_qword(0x418, 0x51)
    chunk4_fd_addr = HEAP_BASE + 0x420
    chunk2_userdata = HEAP_BASE + 0x360
    mangled_fd_chunk4 = protect_ptr(chunk4_fd_addr, chunk2_userdata)
    write_qword(0x420, mangled_fd_chunk4)
    write_qword(0x428, tcache_key)
    for i in range(16, 0x40):
        dump[0x420 + i] = (4 * 37 + i * 13 + 0x41) & 0xFF

    # Chunk 5: allocated, encrypted part 2
    write_qword(0x460, 0)
    write_qword(0x468, 0xB1)

    # Chunk 6: allocated, key derivation constant
    write_qword(0x510, 0)
    write_qword(0x518, 0x41)
    write_qword(0x520, 0xDEADBEEFCAFEBABE)
    write_bytes(0x528, b"KEYPARAMS\x00")
    for i in range(18, 0x30):
        dump[0x520 + i] = (i * 3 + 0x77) & 0xFF

    # Chunk 7: FREED in tcache (size 0x30)
    write_qword(0x550, 0)
    write_qword(0x558, 0x31)
    chunk7_fd_addr = HEAP_BASE + 0x560
    mangled_fd_chunk7 = protect_ptr(chunk7_fd_addr, 0)
    write_qword(0x560, mangled_fd_chunk7)
    write_qword(0x568, tcache_key)
    for i in range(16, 0x20):
        dump[0x560 + i] = (7 * 37 + i * 13 + 0x41) & 0xFF

    # Chunk 8: allocated, encrypted part 3
    write_qword(0x580, 0)
    write_qword(0x588, 0x61)

    # Top chunk
    write_qword(0x5E0, 0)
    write_qword(0x5E8, 0x20a21)

    # Compute key
    P1 = HEAP_BASE + 0x3B0
    P2 = 0xB1
    P3 = HEAP_BASE + 0x360
    P4 = 9
    P5 = 0xDEADBEEFCAFEBABE
    key_input = struct.pack('<QQQQQ', P1, P2, P3, P4, P5)
    key = hashlib.sha256(key_input).digest()

    def xor_encrypt(plaintext, k):
        return bytes(p ^ k[i % len(k)] for i, p in enumerate(plaintext))

    plaintext1 = b'{"part":1,"data":"h34p_chunk_"}'
    plaintext1 = plaintext1.ljust(0x60, b'\x00')
    encrypted1 = xor_encrypt(plaintext1, key)
    write_bytes(0x3B0, encrypted1)

    plaintext2 = b'{"part":2,"data":"f0r3ns1cs_"}'
    plaintext2 = plaintext2.ljust(0xA0, b'\x00')
    encrypted2 = xor_encrypt(plaintext2, key)
    write_bytes(0x470, encrypted2)

    plaintext3 = b'{"part":3,"data":"7b2e9d4a"}'
    plaintext3 = plaintext3.ljust(0x50, b'\x00')
    encrypted3 = xor_encrypt(plaintext3, key)
    write_bytes(0x590, encrypted3)

    return bytes(dump)

if __name__ == '__main__':
    dump_data = build_heap()
    with open('/app/heap_dump.bin', 'wb') as f:
        f.write(dump_data)
