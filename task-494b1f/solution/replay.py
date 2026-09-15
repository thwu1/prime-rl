#!/usr/bin/env python3
"""
Replay binary edit journal through PieceTable and produce output artifacts.
Supports sub-commands: replay, diffs, database, all.

"""

import struct
import os
import subprocess
import sqlite3
import sys

sys.path.insert(0, "/app")


def parse_journal(path):
    ops = []
    with open(path, 'rb') as f:
        header = f.read(8)
        assert header[:6] == b"PTEDIT", f"Bad magic: {header[:6]}"
        assert header[6] == 1, f"Unsupported version: {header[6]}"

        while True:
            opcode_byte = f.read(1)
            if not opcode_byte:
                break
            opcode = opcode_byte[0]

            if opcode == 0x01:  # INSERT
                offset, text_len = struct.unpack('<II', f.read(8))
                text = f.read(text_len).decode('utf-8')
                ops.append(('INSERT', offset, text))
            elif opcode == 0x02:  # DELETE
                offset, length = struct.unpack('<II', f.read(8))
                ops.append(('DELETE', offset, length))
            elif opcode == 0x03:  # SNAPSHOT
                snap_id = struct.unpack('<I', f.read(4))[0]
                ops.append(('SNAPSHOT', snap_id))
            elif opcode == 0x04:  # UNDO
                ops.append(('UNDO',))
            elif opcode == 0x05:  # REDO
                branch = struct.unpack('<I', f.read(4))[0]
                ops.append(('REDO', branch))
            elif opcode == 0xFF:  # END
                break
            else:
                raise ValueError(f"Unknown opcode: 0x{opcode:02x}")

    return ops


def compute_line_count(text):
    if not text:
        return 1
    c = text.count('\n')
    if not text.endswith('\n'):
        c += 1
    return c


def cmd_replay():
    """Parse journal, replay through PieceTable, write snapshot files."""
    from piece_table import PieceTable

    ops = parse_journal('/app/journal.bin')
    pt = PieceTable()

    os.makedirs('/app/output/snapshots', exist_ok=True)

    for op in ops:
        if op[0] == 'INSERT':
            pt.insert(op[1], op[2])
        elif op[0] == 'DELETE':
            pt.delete(op[1], op[2])
        elif op[0] == 'SNAPSHOT':
            with open(f'/app/output/snapshots/snapshot_{op[1]}.txt', 'w') as f:
                f.write(pt.get_text())
        elif op[0] == 'UNDO':
            pt.undo()
        elif op[0] == 'REDO':
            pt.redo(op[1])


def cmd_diffs():
    """Generate unified diffs between consecutive snapshots."""
    snap_dir = '/app/output/snapshots'
    diff_dir = '/app/output/diffs'
    os.makedirs(diff_dir, exist_ok=True)

    files = sorted(
        f for f in os.listdir(snap_dir)
        if f.startswith('snapshot_') and f.endswith('.txt')
    )

    for i in range(len(files) - 1):
        a_id = files[i].replace('snapshot_', '').replace('.txt', '')
        b_id = files[i + 1].replace('snapshot_', '').replace('.txt', '')
        with open(f'{diff_dir}/diff_{a_id}_{b_id}.patch', 'w') as out:
            subprocess.run(
                ['diff', '-u',
                 f'{snap_dir}/{files[i]}',
                 f'{snap_dir}/{files[i + 1]}'],
                stdout=out
            )


def cmd_database():
    """Create SQLite database with snapshot and diff metadata."""
    snap_dir = '/app/output/snapshots'
    diff_dir = '/app/output/diffs'
    db_path = '/app/output/versions.db'

    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        'CREATE TABLE snapshots '
        '(id INTEGER PRIMARY KEY, content TEXT, line_count INTEGER, char_count INTEGER)'
    )
    cur.execute(
        'CREATE TABLE diffs '
        '(id INTEGER PRIMARY KEY AUTOINCREMENT, from_snapshot INTEGER, '
        'to_snapshot INTEGER, additions INTEGER, deletions INTEGER)'
    )

    # Populate snapshots
    snap_files = sorted(
        f for f in os.listdir(snap_dir)
        if f.startswith('snapshot_') and f.endswith('.txt')
    )
    for snap_file in snap_files:
        sid = int(snap_file.replace('snapshot_', '').replace('.txt', ''))
        with open(f'{snap_dir}/{snap_file}') as f:
            content = f.read()
        cur.execute(
            'INSERT INTO snapshots VALUES (?, ?, ?, ?)',
            (sid, content, compute_line_count(content), len(content))
        )

    # Populate diffs
    diff_files = sorted(
        f for f in os.listdir(diff_dir)
        if f.startswith('diff_') and f.endswith('.patch')
    )
    for diff_file in diff_files:
        parts = diff_file.replace('diff_', '').replace('.patch', '').split('_')
        a, b = int(parts[0]), int(parts[1])
        with open(f'{diff_dir}/{diff_file}') as f:
            patch_lines = f.read().split('\n')
        additions = sum(
            1 for line in patch_lines
            if line.startswith('+') and not line.startswith('+++')
        )
        deletions = sum(
            1 for line in patch_lines
            if line.startswith('-') and not line.startswith('---')
        )
        cur.execute(
            'INSERT INTO diffs (from_snapshot, to_snapshot, additions, deletions) '
            'VALUES (?, ?, ?, ?)',
            (a, b, additions, deletions)
        )

    conn.commit()
    conn.close()


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if cmd == 'replay':
        cmd_replay()
    elif cmd == 'diffs':
        cmd_diffs()
    elif cmd == 'database':
        cmd_database()
    elif cmd == 'all':
        cmd_replay()
        cmd_diffs()
        cmd_database()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
