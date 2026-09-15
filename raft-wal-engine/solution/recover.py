#!/usr/bin/env python3
"""
WAL recovery tool.
Reads RLOG/RSNP binary format as defined by the Go source at /app/gowal/.

Format notes (discovered from wal.go):
- Segment header: magic('RLOG',4) + version(uint16 LE,2) + first_index(uint64 LE,8) + entry_count(uint32 LE,4) = 18 bytes
- Entry: index(uint64 LE,8) + term(uint64 LE,8) + timestamp(int64 LE,8) + payload_len(uint32 LE,4) + payload(N) + crc32(uint32 LE,4)
  CRC-32 IEEE covers everything from index through payload (before the CRC field)
- Snapshot: magic('RSNP',4) + version(uint16 LE,2) + last_index(uint64 LE,8) + last_term(uint64 LE,8) + state_len(uint32 LE,4) + state_data(N) + crc32(uint32 LE,4)
  CRC-32 IEEE covers everything from magic through state_data (before the CRC field)
"""

import glob
import json
import os
import struct
import sys
import zlib

SEGMENT_MAGIC = b'RLOG'
SNAPSHOT_MAGIC = b'RSNP'
SEGMENT_HEADER_SIZE = 18


def read_segment(path):
    """Read and verify entries from a segment file. Returns (entries, errors)."""
    with open(path, 'rb') as f:
        data = f.read()

    fname = os.path.basename(path)

    if len(data) < SEGMENT_HEADER_SIZE:
        return [], [{'file': fname, 'error': 'file too short'}]

    magic = data[0:4]
    if magic != SEGMENT_MAGIC:
        return [], [{'file': fname, 'error': f'bad magic: {magic!r}'}]

    first_index = struct.unpack_from('<Q', data, 6)[0]
    entry_count = struct.unpack_from('<I', data, 14)[0]

    entries = []
    errors = []
    offset = SEGMENT_HEADER_SIZE

    for i in range(entry_count):
        if offset + 28 > len(data):
            errors.append({
                'file': fname,
                'index': int(first_index + i),
                'error': 'truncated entry (header incomplete)',
            })
            break

        index = struct.unpack_from('<Q', data, offset)[0]
        term = struct.unpack_from('<Q', data, offset + 8)[0]
        timestamp = struct.unpack_from('<q', data, offset + 16)[0]
        payload_len = struct.unpack_from('<I', data, offset + 24)[0]

        entry_end = offset + 28 + payload_len + 4
        if entry_end > len(data):
            errors.append({
                'file': fname,
                'index': int(index) if offset + 8 <= len(data) else int(first_index + i),
                'error': 'truncated entry (payload/CRC incomplete)',
            })
            break

        payload = data[offset + 28:offset + 28 + payload_len]
        stored_crc = struct.unpack_from('<I', data, offset + 28 + payload_len)[0]
        computed_crc = zlib.crc32(data[offset:offset + 28 + payload_len]) & 0xFFFFFFFF

        if stored_crc != computed_crc:
            errors.append({
                'file': fname,
                'index': int(index),
                'error': f'CRC mismatch: stored=0x{stored_crc:08x} computed=0x{computed_crc:08x}',
            })
            offset = entry_end
            continue

        entries.append({
            'index': int(index),
            'term': int(term),
            'timestamp': int(timestamp),
            'payload': payload.decode('utf-8'),
        })
        offset = entry_end

    return entries, errors


def read_snapshot(waldir):
    """Read and verify the latest snapshot. Returns (snapshot_data, error)."""
    snap_files = sorted(glob.glob(os.path.join(waldir, 'snapshot_*.snap')))
    if not snap_files:
        return None, None

    path = snap_files[-1]
    fname = os.path.basename(path)

    with open(path, 'rb') as f:
        data = f.read()

    if len(data) < 30:
        return None, {'file': fname, 'error': 'too short'}

    magic = data[0:4]
    if magic != SNAPSHOT_MAGIC:
        return None, {'file': fname, 'error': f'bad magic: {magic!r}'}

    stored_crc = struct.unpack_from('<I', data, len(data) - 4)[0]
    computed_crc = zlib.crc32(data[:len(data) - 4]) & 0xFFFFFFFF

    if stored_crc != computed_crc:
        return None, {
            'file': fname,
            'error': f'CRC mismatch: stored=0x{stored_crc:08x} computed=0x{computed_crc:08x}',
        }

    last_index = struct.unpack_from('<Q', data, 6)[0]
    last_term = struct.unpack_from('<Q', data, 14)[0]
    state_len = struct.unpack_from('<I', data, 22)[0]
    state_data = data[26:26 + state_len]
    state = json.loads(state_data)

    return {
        'last_index': int(last_index),
        'last_term': int(last_term),
        'state': state,
    }, None


def apply_command(state, command):
    """Apply a SET/DEL command to the key-value state."""
    parts = command.split(' ', 2)
    if parts[0] == 'SET' and len(parts) >= 3:
        state[parts[1]] = parts[2]
    elif parts[0] == 'DEL' and len(parts) >= 2:
        state.pop(parts[1], None)


def recover(waldir):
    """Recover key-value state from WAL data. Returns (state, report)."""
    all_errors = []

    snapshot, snap_error = read_snapshot(waldir)
    if snap_error:
        all_errors.append(snap_error)

    if snapshot:
        state = dict(snapshot['state'])
        replay_from = snapshot['last_index'] + 1
    else:
        state = {}
        replay_from = 1

    seg_files = sorted(glob.glob(os.path.join(waldir, 'segment_*.wal')))
    all_entries = []
    for seg_path in seg_files:
        entries, errors = read_segment(seg_path)
        all_entries.extend(entries)
        all_errors.extend(errors)

    all_entries.sort(key=lambda e: e['index'])

    for entry in all_entries:
        if entry['index'] >= replay_from:
            apply_command(state, entry['payload'])

    corrupted_indices = sorted(set(e['index'] for e in all_errors if 'index' in e))
    corrupted_files = sorted(set(e['file'] for e in all_errors))

    report = {
        'corrupted_files': corrupted_files,
        'corrupted_indices': corrupted_indices,
        'total_recoverable_entries': len(all_entries),
    }

    return state, report


if __name__ == '__main__':
    waldir = sys.argv[1] if len(sys.argv) > 1 else '/app/waldata'
    state, report = recover(waldir)

    with open('/app/recovered_state.json', 'w') as f:
        json.dump(state, f, sort_keys=True, indent=2)

    with open('/app/corruption_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Recovered {len(state)} keys")
    print(f"Found {len(report['corrupted_files'])} corrupted files")
    print(f"Corrupted indices: {report['corrupted_indices']}")
    print(f"Total recoverable entries: {report['total_recoverable_entries']}")
