#!/usr/bin/env python3
"""
Generate heap dump snapshots for the tcache poisoning forensics challenge.
Runs during Docker build and is deleted afterwards.

"""

import struct
import hashlib

HEAP_BASE = 0x55555555a000
DUMP_SIZE = 0x600

# Must match the AUDIT_KEY in heapservice.c
AUDIT_KEY = bytes([0x7a, 0x3f, 0xb1, 0x94, 0xe2, 0x55, 0x08, 0xc7,
                   0x6d, 0xa3, 0x19, 0xf0, 0x4b, 0x82, 0xd6, 0x5e])

FLAG = b"FLAG{tc4ch3_p01s0n_fd_f0r3ns1cs_a7e2b391}"

# Allocation sizes: malloc(0x80), malloc(0x20), malloc(0x40), malloc(0x40),
#                   malloc(0x60), malloc(0xA0), malloc(0x20), malloc(0x40)
# Chunk sizes:      0x90,         0x30,         0x50,         0x50,
#                   0x70,         0xB0,         0x30,         0x50
#
# Heap layout (offsets from heap base):
#   0x000: tcache_perthread_struct (chunk size 0x290)
#   0x290: Chunk 0 (size 0x90)  - banner
#   0x320: Chunk 1 (size 0x30)  - metadata
#   0x350: Chunk 2 (size 0x50)  - buffer A
#   0x3A0: Chunk 3 (size 0x50)  - buffer B
#   0x3F0: Chunk 4 (size 0x70)  - transaction log
#   0x460: Chunk 5 (size 0xB0)  - audit records
#   0x510: Chunk 6 (size 0x30)  - config
#   0x540: Chunk 7 (size 0x50)  - encrypted session token
#   0x590: Top chunk


def write_qword(dump, offset, value):
    struct.pack_into('<Q', dump, offset, value)


def write_bytes(dump, offset, data):
    dump[offset:offset + len(data)] = data


def protect_ptr(pos, ptr):
    """glibc PROTECT_PTR: mangle a tcache fd pointer."""
    return (pos >> 12) ^ ptr


def xor_encrypt(plaintext, key):
    return bytes(p ^ key[i % len(key)] for i, p in enumerate(plaintext))


def fill_pattern(dump, offset, length, seed):
    """Fill a region with a deterministic pattern."""
    for i in range(length):
        dump[offset + i] = (seed * 37 + i * 13 + 0x41) & 0xFF


def build_clean():
    dump = bytearray(DUMP_SIZE)

    # ===== tcache_perthread_struct (chunk at 0x000, size 0x290) =====
    write_qword(dump, 0x000, 0)       # prev_size
    write_qword(dump, 0x008, 0x291)   # size (PREV_INUSE)
    # counts (0x010..0x08F) and entries (0x090..0x28F) all zero

    # ===== Chunk 0: service banner (malloc(0x80), chunk_size=0x90) =====
    write_qword(dump, 0x290, 0)
    write_qword(dump, 0x298, 0x91)
    banner = b"HEAPSERVICE v2.4.1 - Secure Session Manager\x00"
    write_bytes(dump, 0x2A0, banner)
    fill_pattern(dump, 0x2A0 + len(banner), 0x80 - len(banner), 0)

    # ===== Chunk 1: metadata (malloc(0x20), chunk_size=0x30) =====
    write_qword(dump, 0x320, 0)
    write_qword(dump, 0x328, 0x31)
    write_qword(dump, 0x330, 0x0100)        # sequence number
    write_qword(dump, 0x338, 0x02)          # version
    write_qword(dump, 0x340, 0x65a1b2c3)   # timestamp
    write_qword(dump, 0x348, 0x5678)        # operational flags

    # ===== Chunk 2: buffer A (malloc(0x40), chunk_size=0x50) =====
    write_qword(dump, 0x350, 0)
    write_qword(dump, 0x358, 0x51)
    buf2 = b"SLOT2:BUFFER_ALPHA\x00"
    write_bytes(dump, 0x360, buf2)
    fill_pattern(dump, 0x360 + len(buf2), 0x40 - len(buf2), 2)

    # ===== Chunk 3: buffer B (malloc(0x40), chunk_size=0x50) =====
    write_qword(dump, 0x3A0, 0)
    write_qword(dump, 0x3A8, 0x51)
    buf3 = b"SLOT3:BUFFER_BETA\x00"
    write_bytes(dump, 0x3B0, buf3)
    fill_pattern(dump, 0x3B0 + len(buf3), 0x40 - len(buf3), 3)

    # ===== Chunk 4: transaction log (malloc(0x60), chunk_size=0x70) =====
    write_qword(dump, 0x3F0, 0)
    write_qword(dump, 0x3F8, 0x71)
    buf4 = b"SLOT4:TRANSACTION_LOG\x00"
    write_bytes(dump, 0x400, buf4)
    fill_pattern(dump, 0x400 + len(buf4), 0x60 - len(buf4), 4)

    # ===== Chunk 5: audit records (malloc(0xA0), chunk_size=0xB0) =====
    write_qword(dump, 0x460, 0)
    write_qword(dump, 0x468, 0xB1)
    buf5 = b"SLOT5:AUDIT_RECORDS\x00"
    write_bytes(dump, 0x470, buf5)
    fill_pattern(dump, 0x470 + len(buf5), 0xA0 - len(buf5), 5)

    # ===== Chunk 6: config (malloc(0x20), chunk_size=0x30) =====
    write_qword(dump, 0x510, 0)
    write_qword(dump, 0x518, 0x31)
    buf6 = b"SLOT6:CONFIG_V2\x00"
    write_bytes(dump, 0x520, buf6)
    fill_pattern(dump, 0x520 + len(buf6), 0x20 - len(buf6), 6)

    # ===== Chunk 7: encrypted session token (malloc(0x40), chunk_size=0x50) =====
    write_qword(dump, 0x540, 0)
    write_qword(dump, 0x548, 0x51)

    # Compute encrypted token
    target_addr = HEAP_BASE + 0x550  # chunk 7 userdata virtual address
    key_input = AUDIT_KEY + struct.pack('<Q', target_addr)
    key = hashlib.sha256(key_input).digest()
    plaintext = FLAG.ljust(0x40, b'\x00')
    encrypted = xor_encrypt(plaintext, key)
    write_bytes(dump, 0x550, encrypted)

    # ===== Top chunk =====
    write_qword(dump, 0x590, 0)
    write_qword(dump, 0x598, 0x20A71)

    return bytes(dump)


def build_attacked():
    """Build the post-attack snapshot.

    Attack scenario:
    1. Service normally freed chunks 4 and 6 during operation
    2. Attacker freed chunk 3 into tcache[3] (chunk_size 0x50, idx 3)
    3. Attacker freed chunk 2 into tcache[3] (now count=2, head=chunk2)
       Chain: chunk2 -> chunk3 -> NULL
    4. Attacker used heap overflow from chunk 1 to corrupt chunk 2's fd
       Original: PROTECT_PTR(chunk2_addr, chunk3_addr)
       Poisoned: PROTECT_PTR(chunk2_addr, chunk7_addr)
    5. IDS detected the corruption before the attacker could allocate

    The snapshot preserves the poisoned tcache state.
    Chunk 7 still contains the encrypted session token (unchanged).
    """
    dump = bytearray(build_clean())

    tcache_key = HEAP_BASE + 0x010  # tcache_perthread_struct userdata

    # === NORMAL OPERATION CHANGES (red herrings) ===

    # Chunk 1: timestamp updated during normal service operation
    write_qword(dump, 0x340, 0x65a1b3d4)

    # Chunk 5: audit log entry appended (normal write)
    write_bytes(dump, 0x470 + 20, b"[UPD:0x3d4]\x00")

    # === FREE: Chunk 4 into tcache[5] (chunk_size 0x70, idx 5) - NORMAL ===
    struct.pack_into('<H', dump, 0x010 + 5 * 2, 1)            # count[5] = 1
    write_qword(dump, 0x090 + 5 * 8, HEAP_BASE + 0x400)       # entries[5]
    # Chunk 4 freed: first 16 bytes become fd + tcache_key
    chunk4_fd_addr = HEAP_BASE + 0x400
    write_qword(dump, 0x400, protect_ptr(chunk4_fd_addr, 0))   # fd -> NULL (tail)
    write_qword(dump, 0x408, tcache_key)                       # tcache key
    # Remaining data in chunk 4 untouched (tcache free only writes first 16 bytes)

    # === FREE: Chunk 6 into tcache[1] (chunk_size 0x30, idx 1) - NORMAL ===
    struct.pack_into('<H', dump, 0x010 + 1 * 2, 1)            # count[1] = 1
    write_qword(dump, 0x090 + 1 * 8, HEAP_BASE + 0x520)       # entries[1]
    chunk6_fd_addr = HEAP_BASE + 0x520
    write_qword(dump, 0x520, protect_ptr(chunk6_fd_addr, 0))   # fd -> NULL (tail)
    write_qword(dump, 0x528, tcache_key)

    # === FREE: Chunk 3 into tcache[3] (chunk_size 0x50, idx 3) - ATTACK step 1 ===
    # Then FREE: Chunk 2 into tcache[3] - ATTACK step 2
    # Chain: chunk2 (head) -> chunk3 (tail) -> NULL
    # tcache[3] count=2
    struct.pack_into('<H', dump, 0x010 + 3 * 2, 2)            # count[3] = 2
    write_qword(dump, 0x090 + 3 * 8, HEAP_BASE + 0x360)       # entries[3] = chunk2

    # Chunk 3: tail of tcache[3], fd -> NULL
    chunk3_fd_addr = HEAP_BASE + 0x3B0
    write_qword(dump, 0x3B0, protect_ptr(chunk3_fd_addr, 0))   # fd -> NULL
    write_qword(dump, 0x3B8, tcache_key)

    # Chunk 2: head of tcache[3], fd POISONED to point to chunk 7
    chunk2_fd_addr = HEAP_BASE + 0x360
    target_addr = HEAP_BASE + 0x550  # chunk 7 userdata
    # Normal fd would be: protect_ptr(chunk2_fd_addr, chunk3_userdata_addr)
    # Poisoned fd:        protect_ptr(chunk2_fd_addr, target_addr)
    poisoned_fd = protect_ptr(chunk2_fd_addr, target_addr)
    write_qword(dump, 0x360, poisoned_fd)
    write_qword(dump, 0x368, tcache_key)

    # Chunk 7: UNCHANGED - still has the encrypted session token
    # (attack was stopped before the attacker could consume the tcache entries)

    return bytes(dump)


if __name__ == '__main__':
    clean_data = build_clean()
    with open('/app/snapshot_clean.bin', 'wb') as f:
        f.write(clean_data)

    attacked_data = build_attacked()
    with open('/app/snapshot_attacked.bin', 'wb') as f:
        f.write(attacked_data)

    # Verification
    target_addr = HEAP_BASE + 0x550
    key_input = AUDIT_KEY + struct.pack('<Q', target_addr)
    key = hashlib.sha256(key_input).digest()
    encrypted = clean_data[0x550:0x590]
    decrypted = xor_encrypt(encrypted, key)
    flag = decrypted.rstrip(b'\x00').decode()
    assert flag == FLAG.decode(), f"Verification failed: {flag}"
    print(f"Snapshots generated. Verification: {flag}")
