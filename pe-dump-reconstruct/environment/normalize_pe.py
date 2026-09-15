#!/usr/bin/env python3
"""
Strip overlay data from a PE file — truncate to the end of the last section's
raw data so the file can be perfectly reconstructed from a virtual memory dump.
"""
import struct
import sys


def normalize(path):
    with open(path, 'rb') as f:
        data = bytearray(f.read())

    e_lfanew = struct.unpack_from('<I', data, 0x3C)[0]
    coff = e_lfanew + 4
    num_sects = struct.unpack_from('<H', data, coff + 2)[0]
    size_opt = struct.unpack_from('<H', data, coff + 16)[0]
    opt = coff + 20

    sec_base = opt + size_opt
    file_end = struct.unpack_from('<I', data, opt + 60)[0]  # size_of_headers

    for i in range(num_sects):
        o = sec_base + i * 40
        rs = struct.unpack_from('<I', data, o + 16)[0]
        rp = struct.unpack_from('<I', data, o + 20)[0]
        end = rp + rs
        if end > file_end:
            file_end = end

    orig_len = len(data)
    if file_end < orig_len:
        print(f"normalize: stripped overlay {orig_len} -> {file_end} bytes "
              f"(removed {orig_len - file_end} bytes)")
        with open(path, 'wb') as f:
            f.write(data[:file_end])
    elif file_end > orig_len:
        print(f"normalize: padding file {orig_len} -> {file_end} bytes")
        data.extend(b'\x00' * (file_end - orig_len))
        with open(path, 'wb') as f:
            f.write(data)
    else:
        print(f"normalize: file is already {file_end} bytes, no change needed")


if __name__ == '__main__':
    normalize(sys.argv[1])
