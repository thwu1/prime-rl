#!/usr/bin/env python3
"""Generate binary corpus files that trigger each known bug in libmfp."""

import struct
import os

MFP_MAGIC = 0x4D465000  # "MFP\0" in little-endian

os.makedirs('/app/corpus', exist_ok=True)


def write_raw(filename, data):
    with open(filename, 'wb') as f:
        f.write(data)


# crash_bug001.mfp — Integer truncation in mfp_normalize (MFP001)
#
# data_len=3, version(scale)=1431655766
# Product: 3 * 1431655766 = 4294967298 = 0x100000002
# Truncated to uint32: 2
# malloc(2) succeeds, loop writes 4294967298 iterations -> heap overflow
data = struct.pack('<IIII', MFP_MAGIC, 1431655766, 1, 0)  # header
data += struct.pack('<II', 1, 1)  # entry: type=1, name_len=1
data += b'A'                      # name
data += struct.pack('<I', 3)      # data_len=3
data += bytes([1, 2, 3])          # data
write_raw('/app/corpus/crash_bug001.mfp', data)


# crash_bug002.mfp — Buffer overread in name parsing (MFP002)
#
# name_len=500 but only 8 bytes remain after the name_len field.
# memcpy reads 500 bytes from buf+24 but buffer is only 32 bytes.
data = struct.pack('<IIII', MFP_MAGIC, 1, 1, 0)  # header
data += struct.pack('<II', 1, 500)                 # entry: type=1, name_len=500
data += b'A' * 8                                   # only 8 bytes of name data
write_raw('/app/corpus/crash_bug002.mfp', data)


# crash_bug003.mfp — Off-by-one in entry loop (MFP003)
#
# num_entries=2 -> calloc(2, ...) allocates array for 2 entries.
# File contains data for 3 entries so the loop doesn't break early.
# At i=2 (i <= 2 is true), writes to entries[2] which is out-of-bounds.
data = struct.pack('<IIII', MFP_MAGIC, 1, 2, 0)  # header: num_entries=2
# Entry 0
data += struct.pack('<II', 1, 1) + b'A' + struct.pack('<I', 0)
# Entry 1
data += struct.pack('<II', 2, 1) + b'B' + struct.pack('<I', 0)
# Entry 2 (extra data consumed by off-by-one iteration)
data += struct.pack('<II', 3, 1) + b'C' + struct.pack('<I', 0)
write_raw('/app/corpus/crash_bug003.mfp', data)


# crash_bug004.mfp — Division by zero in render_summary (MFP004)
#
# Entry with type=0 and non-empty data.
# sum/e->type computes sum/0 -> SIGFPE.
data = struct.pack('<IIII', MFP_MAGIC, 1, 1, 0)  # header
data += struct.pack('<II', 0, 4)                   # entry: type=0, name_len=4
data += b'test'                                    # name
data += struct.pack('<I', 4)                       # data_len=4
data += bytes([1, 2, 3, 4])                       # data
write_raw('/app/corpus/crash_bug004.mfp', data)


print("Corpus files generated:")
for f in sorted(os.listdir('/app/corpus')):
    path = os.path.join('/app/corpus', f)
    print(f"  {f}: {os.path.getsize(path)} bytes")
