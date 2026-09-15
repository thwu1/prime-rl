#!/usr/bin/env python3
"""
Tcache chain integrity validator for HeapService heap snapshots.
Detects tcache poisoning by walking free lists and verifying fd pointers.

Usage: python3 heap_validator.py <snapshot_path>
Output: JSON to stdout with structure:
  {"compromised": bool, "poisoned_bins": [int, ...], "target_address": "0x..." or null}

"""

import json
import struct
import sys

HEAP_BASE = 0x55555555A000


def read_qword(data, offset):
    if offset + 8 > len(data):
        return 0
    return struct.unpack_from("<Q", data, offset)[0]


def protect_ptr_reverse(pos, mangled):
    """Reverse glibc safe-linking PROTECT_PTR to recover actual pointer."""
    return (pos >> 12) ^ mangled


def walk_chunks(dump):
    """Walk heap chunks after tcache_perthread_struct and return list of chunk info."""
    chunks = []
    offset = 0x290  # first user chunk (after tcache_perthread_struct)
    while offset < len(dump) - 16:
        raw_size = read_qword(dump, offset + 8)
        chunk_size = raw_size & ~0x7
        if chunk_size == 0 or chunk_size > len(dump):
            break
        ud_offset = offset + 0x10
        ud_addr = HEAP_BASE + ud_offset
        chunks.append({
            "offset": offset,
            "chunk_size": chunk_size,
            "ud_offset": ud_offset,
            "ud_addr": ud_addr,
        })
        offset += chunk_size
    return chunks


def identify_freed_chunks(dump, chunks):
    """Identify chunks freed into tcache by checking the tcache_key signature."""
    tcache_key_value = HEAP_BASE + 0x010
    freed_addrs = set()
    for chunk in chunks:
        key_off = chunk["ud_offset"] + 8
        if key_off + 8 <= len(dump):
            if read_qword(dump, key_off) == tcache_key_value:
                freed_addrs.add(chunk["ud_addr"])
    return freed_addrs


def validate_tcache_chains(dump, freed_addrs):
    """Walk every active tcache bin and validate chain integrity.

    Returns (poisoned_bins, first_target_address).
    A bin is poisoned if any fd pointer de-mangles to an address that is
    neither NULL nor a genuinely freed chunk.
    """
    poisoned_bins = []
    first_target = None

    for idx in range(64):
        count = struct.unpack_from("<H", dump, 0x010 + idx * 2)[0]
        if count == 0:
            continue

        head = read_qword(dump, 0x090 + idx * 8)
        current = head

        for step in range(count):
            if current == 0:
                break

            fd_off = current - HEAP_BASE
            if fd_off < 0 or fd_off + 8 > len(dump):
                poisoned_bins.append(idx)
                break

            stored_fd = read_qword(dump, fd_off)
            demangled = protect_ptr_reverse(current, stored_fd)

            if demangled != 0 and demangled not in freed_addrs:
                poisoned_bins.append(idx)
                if first_target is None:
                    first_target = demangled
                break

            current = demangled

    return poisoned_bins, first_target


def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "Usage: heap_validator.py <snapshot_path>"}))
        sys.exit(1)

    with open(sys.argv[1], "rb") as f:
        dump = f.read()

    if len(dump) < 0x290:
        print(json.dumps({
            "compromised": False,
            "poisoned_bins": [],
            "target_address": None,
        }))
        return

    chunks = walk_chunks(dump)
    freed_addrs = identify_freed_chunks(dump, chunks)
    poisoned_bins, target = validate_tcache_chains(dump, freed_addrs)

    result = {
        "compromised": len(poisoned_bins) > 0,
        "poisoned_bins": poisoned_bins,
        "target_address": f"0x{target:x}" if target is not None else None,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
