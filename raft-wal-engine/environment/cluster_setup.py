#!/usr/bin/env python3
"""Generate 3-node Raft cluster WAL data with partition/crash scenario."""
import json
import os
import struct
import sys
import zlib

SEGMENT_MAGIC = b'RLOG'
SNAPSHOT_MAGIC = b'RSNP'
VERSION = 1


def command_for_index(i):
    if i % 10 == 0:
        return f"DEL key_{i - 5}"
    return f"SET key_{i} val_{i}"


def term_for_index(i):
    if i <= 50:
        return 1
    if i <= 90:
        return 2
    return 3


def apply_cmd(state, cmd):
    parts = cmd.split(' ', 2)
    if parts[0] == 'SET' and len(parts) >= 3:
        state[parts[1]] = parts[2]
    elif parts[0] == 'DEL' and len(parts) >= 2:
        state.pop(parts[1], None)


def state_through(n):
    s = {}
    for i in range(1, n + 1):
        apply_cmd(s, command_for_index(i))
    return s


def marshal_entry(index, term, payload_bytes):
    ts = 1700000000000000000 + index * 1000000
    buf = struct.pack('<Q', index)
    buf += struct.pack('<Q', term)
    buf += struct.pack('<q', ts)
    buf += struct.pack('<I', len(payload_bytes))
    buf += payload_bytes
    crc = zlib.crc32(buf) & 0xFFFFFFFF
    buf += struct.pack('<I', crc)
    return buf


def write_segment(path, entries):
    """entries: list of (index, term, payload_str)"""
    with open(path, 'wb') as f:
        f.write(SEGMENT_MAGIC)
        f.write(struct.pack('<H', VERSION))
        f.write(struct.pack('<Q', entries[0][0]))
        f.write(struct.pack('<I', len(entries)))
        for idx, term, payload in entries:
            f.write(marshal_entry(idx, term, payload.encode('utf-8')))


def write_snapshot(path, last_index, last_term, state):
    state_json = json.dumps(state, sort_keys=True).encode('utf-8')
    buf = bytearray()
    buf += SNAPSHOT_MAGIC
    buf += struct.pack('<H', VERSION)
    buf += struct.pack('<Q', last_index)
    buf += struct.pack('<Q', last_term)
    buf += struct.pack('<I', len(state_json))
    buf += state_json
    crc = zlib.crc32(bytes(buf)) & 0xFFFFFFFF
    with open(path, 'wb') as f:
        f.write(buf)
        f.write(struct.pack('<I', crc))


def seg_name(first_index):
    return f'segment_{first_index:010d}.wal'


def snap_name(last_index):
    return f'snapshot_{last_index:010d}.snap'


def corrupt_entry_payload(seg_path, entry_offset_in_seg, byte_in_payload=3):
    with open(seg_path, 'rb') as f:
        data = bytearray(f.read())
    off = 18
    for _ in range(entry_offset_in_seg):
        plen = struct.unpack_from('<I', data, off + 24)[0]
        off += 28 + plen + 4
    data[off + 28 + byte_in_payload] ^= 0xFF
    with open(seg_path, 'wb') as f:
        f.write(data)


def truncate_segment(seg_path, keep_entries):
    with open(seg_path, 'rb') as f:
        data = bytearray(f.read())
    off = 18
    for _ in range(keep_entries):
        plen = struct.unpack_from('<I', data, off + 24)[0]
        off += 28 + plen + 4
    truncated = data[:off + 8]
    with open(seg_path, 'wb') as f:
        f.write(truncated)


def build_entries(start, end):
    return [(i, term_for_index(i), command_for_index(i))
            for i in range(start, end + 1)]


def generate(cluster_dir):
    os.makedirs(cluster_dir, exist_ok=True)

    # ---- node_0 ----
    # Has all committed data. Snapshot at 30, segments 31-120.
    # Entry 67 corrupted (CRC).
    d = os.path.join(cluster_dir, 'node_0')
    os.makedirs(d)
    write_snapshot(os.path.join(d, snap_name(30)), 30, 1, state_through(30))
    write_segment(os.path.join(d, seg_name(31)), build_entries(31, 50))
    write_segment(os.path.join(d, seg_name(51)), build_entries(51, 70))
    write_segment(os.path.join(d, seg_name(71)), build_entries(71, 90))
    write_segment(os.path.join(d, seg_name(91)), build_entries(91, 110))
    write_segment(os.path.join(d, seg_name(111)), build_entries(111, 120))
    corrupt_entry_payload(os.path.join(d, seg_name(51)), 16)  # entry 67

    # ---- node_1 ----
    # Crashed during term 2 after writing stale entries 91-95 (term 2).
    # Never received term 3 entries. Segment 91 truncated to 3 entries.
    d = os.path.join(cluster_dir, 'node_1')
    os.makedirs(d)
    write_snapshot(os.path.join(d, snap_name(30)), 30, 1, state_through(30))
    write_segment(os.path.join(d, seg_name(31)), build_entries(31, 50))
    write_segment(os.path.join(d, seg_name(51)), build_entries(51, 70))
    write_segment(os.path.join(d, seg_name(71)), build_entries(71, 90))
    stale = [(i, 2, f'SET key_{i} stale_{i}') for i in range(91, 96)]
    write_segment(os.path.join(d, seg_name(91)), stale)
    truncate_segment(os.path.join(d, seg_name(91)), 3)

    # ---- node_2 ----
    # Term 3 leader. Snapshot at 90 (corrupted). Segments 91-120.
    # Entry 103 corrupted (CRC).
    d = os.path.join(cluster_dir, 'node_2')
    os.makedirs(d)
    write_snapshot(os.path.join(d, snap_name(90)), 90, 2, state_through(90))
    write_segment(os.path.join(d, seg_name(91)), build_entries(91, 110))
    write_segment(os.path.join(d, seg_name(111)), build_entries(111, 120))
    snap_path = os.path.join(d, snap_name(90))
    with open(snap_path, 'rb') as f:
        sdata = bytearray(f.read())
    sdata[30] ^= 0x20
    with open(snap_path, 'wb') as f:
        f.write(sdata)
    corrupt_entry_payload(os.path.join(d, seg_name(91)), 12)  # entry 103


if __name__ == '__main__':
    generate(sys.argv[1])
