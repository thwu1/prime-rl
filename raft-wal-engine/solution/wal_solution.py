
"""
Write-Ahead Log engine with CRC integrity, multi-segment storage,
snapshot-based compaction, and crash recovery.
"""

import os
import struct
import json
import zlib
import threading
from typing import Optional

SEGMENT_MAGIC = b'WAL1'
SNAPSHOT_MAGIC = b'SNAP'
SEGMENT_HEADER_SIZE = 16  # 4 (magic) + 8 (first_index) + 4 (entry_count)


class WALEntry:
    __slots__ = ('index', 'term', 'command')

    def __init__(self, index: int, term: int, command: bytes):
        self.index = index
        self.term = term
        self.command = command


class Snapshot:
    __slots__ = ('last_included_index', 'last_included_term', 'state')

    def __init__(self, last_included_index: int, last_included_term: int, state: dict):
        self.last_included_index = last_included_index
        self.last_included_term = last_included_term
        self.state = state


class WALEngine:
    def __init__(self, directory: str, max_entries_per_segment: int = 1000):
        self._dir = directory
        self._max_entries = max_entries_per_segment
        self._lock = threading.Lock()
        self._next_index = 1
        self._last_term = 0
        self._snapshot_index = 0
        self._snapshot_term = 0
        self._cur_seg_first = 1
        self._cur_seg_count = 0

        os.makedirs(directory, exist_ok=True)
        self._init_from_disk()

    # ------------------------------------------------------------------
    # Initialization (no CRC verification — corruption detected on read)
    # ------------------------------------------------------------------

    def _init_from_disk(self):
        # Scan latest snapshot metadata
        snap_files = self._list_snapshot_files()
        if snap_files:
            filepath = os.path.join(self._dir, snap_files[-1])
            try:
                with open(filepath, 'rb') as f:
                    f.read(4)  # magic
                    f.read(4)  # crc — skip
                    self._snapshot_index = struct.unpack('<Q', f.read(8))[0]
                    self._snapshot_term = struct.unpack('<Q', f.read(8))[0]
                self._next_index = self._snapshot_index + 1
                self._last_term = self._snapshot_term
            except Exception:
                pass

        # Scan segment headers
        seg_files = self._list_segment_files()
        for seg_file in seg_files:
            filepath = os.path.join(self._dir, seg_file)
            try:
                with open(filepath, 'rb') as f:
                    magic = f.read(4)
                    if magic != SEGMENT_MAGIC:
                        continue
                    first_index = struct.unpack('<Q', f.read(8))[0]
                    entry_count = struct.unpack('<I', f.read(4))[0]

                    if entry_count > 0:
                        end_index = first_index + entry_count
                        if end_index > self._next_index:
                            self._next_index = end_index

                        # Walk entries to find last term (no CRC check)
                        last_term_seen = 0
                        for _ in range(entry_count):
                            f.read(4)  # crc
                            f.read(8)  # index
                            t = struct.unpack('<Q', f.read(8))[0]
                            cmd_len = struct.unpack('<I', f.read(4))[0]
                            f.read(cmd_len)
                            last_term_seen = t
                        self._last_term = last_term_seen
            except Exception:
                pass

        # Determine current segment state
        if seg_files:
            last_seg = seg_files[-1]
            try:
                with open(os.path.join(self._dir, last_seg), 'rb') as f:
                    f.read(4)
                    fi = struct.unpack('<Q', f.read(8))[0]
                    ec = struct.unpack('<I', f.read(4))[0]
                    self._cur_seg_first = fi
                    self._cur_seg_count = ec
            except Exception:
                self._cur_seg_first = self._next_index
                self._cur_seg_count = 0
        else:
            self._cur_seg_first = self._next_index
            self._cur_seg_count = 0

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------

    def _segment_path(self, first_index: int) -> str:
        return os.path.join(self._dir, f"segment_{first_index:010d}.wal")

    def _snapshot_path(self, last_index: int) -> str:
        return os.path.join(self._dir, f"snapshot_{last_index:010d}.snap")

    def _list_segment_files(self) -> list:
        try:
            return sorted(f for f in os.listdir(self._dir) if f.endswith('.wal'))
        except FileNotFoundError:
            return []

    def _list_snapshot_files(self) -> list:
        try:
            return sorted(f for f in os.listdir(self._dir) if f.endswith('.snap'))
        except FileNotFoundError:
            return []

    # ------------------------------------------------------------------
    # Binary encoding
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_entry(entry: 'WALEntry') -> bytes:
        data = struct.pack('<Q', entry.index)
        data += struct.pack('<Q', entry.term)
        data += struct.pack('<I', len(entry.command))
        data += entry.command
        crc = zlib.crc32(data) & 0xFFFFFFFF
        return struct.pack('<I', crc) + data

    def _read_segment_verified(self, filepath: str) -> list:
        with open(filepath, 'rb') as f:
            raw = f.read()

        if raw[:4] != SEGMENT_MAGIC:
            raise ValueError(f"Bad segment magic in {filepath}")

        first_index = struct.unpack('<Q', raw[4:12])[0]
        entry_count = struct.unpack('<I', raw[12:16])[0]

        entries = []
        off = SEGMENT_HEADER_SIZE
        for _ in range(entry_count):
            stored_crc = struct.unpack('<I', raw[off:off + 4])[0]
            estart = off + 4

            log_idx = struct.unpack('<Q', raw[estart:estart + 8])[0]
            term = struct.unpack('<Q', raw[estart + 8:estart + 16])[0]
            cmd_len = struct.unpack('<I', raw[estart + 16:estart + 20])[0]
            command = raw[estart + 20:estart + 20 + cmd_len]

            edata = raw[estart:estart + 20 + cmd_len]
            computed = zlib.crc32(edata) & 0xFFFFFFFF
            if stored_crc != computed:
                raise ValueError(
                    f"CRC mismatch at index {log_idx}: "
                    f"stored=0x{stored_crc:08x} computed=0x{computed:08x}"
                )

            entries.append(WALEntry(index=log_idx, term=term, command=command))
            off = estart + 20 + cmd_len

        return entries

    def _write_segment_file(self, first_index: int, entries: list) -> None:
        path = self._segment_path(first_index)
        with open(path, 'wb') as f:
            f.write(SEGMENT_MAGIC)
            f.write(struct.pack('<Q', first_index))
            f.write(struct.pack('<I', len(entries)))
            for e in entries:
                f.write(self._encode_entry(e))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, term: int, command: bytes) -> int:
        with self._lock:
            index = self._next_index
            entry = WALEntry(index=index, term=term, command=command)

            # Need a new segment?
            if self._cur_seg_count >= self._max_entries:
                self._cur_seg_first = index
                self._cur_seg_count = 0

            seg_path = self._segment_path(self._cur_seg_first)

            if self._cur_seg_count == 0:
                # Create new segment file
                with open(seg_path, 'wb') as f:
                    f.write(SEGMENT_MAGIC)
                    f.write(struct.pack('<Q', index))
                    f.write(struct.pack('<I', 1))
                    f.write(self._encode_entry(entry))
            else:
                # Append to existing segment: update count, then append bytes
                with open(seg_path, 'r+b') as f:
                    f.seek(12)
                    f.write(struct.pack('<I', self._cur_seg_count + 1))
                    f.seek(0, 2)
                    f.write(self._encode_entry(entry))

            self._cur_seg_count += 1
            self._next_index = index + 1
            self._last_term = term
            return index

    def read(self, from_index: int) -> list:
        with self._lock:
            result = []
            for seg_file in self._list_segment_files():
                fpath = os.path.join(self._dir, seg_file)
                entries = self._read_segment_verified(fpath)
                for e in entries:
                    if e.index >= from_index:
                        result.append(e)
            return result

    def read_entry(self, index: int) -> 'WALEntry':
        with self._lock:
            for seg_file in self._list_segment_files():
                fpath = os.path.join(self._dir, seg_file)
                entries = self._read_segment_verified(fpath)
                for e in entries:
                    if e.index == index:
                        return e
            raise KeyError(f"Entry not found: {index}")

    def truncate(self, from_index: int) -> None:
        with self._lock:
            for seg_file in list(self._list_segment_files()):
                fpath = os.path.join(self._dir, seg_file)
                with open(fpath, 'rb') as f:
                    magic = f.read(4)
                    fi = struct.unpack('<Q', f.read(8))[0]
                    ec = struct.unpack('<I', f.read(4))[0]

                last_in_seg = fi + ec - 1

                if fi >= from_index:
                    os.remove(fpath)
                elif last_in_seg >= from_index:
                    # Partial truncation — keep entries before from_index
                    entries = self._read_segment_verified(fpath)
                    kept = [e for e in entries if e.index < from_index]
                    os.remove(fpath)
                    if kept:
                        self._write_segment_file(kept[0].index, kept)

            self._next_index = from_index

            # Refresh current-segment bookkeeping
            seg_files = self._list_segment_files()
            if seg_files:
                last_seg = seg_files[-1]
                fpath = os.path.join(self._dir, last_seg)
                with open(fpath, 'rb') as f:
                    f.read(4)
                    fi = struct.unpack('<Q', f.read(8))[0]
                    ec = struct.unpack('<I', f.read(4))[0]
                self._cur_seg_first = fi
                self._cur_seg_count = ec
                # Read last entry term
                entries = self._read_segment_verified(fpath)
                self._last_term = entries[-1].term if entries else self._snapshot_term
            else:
                self._cur_seg_first = self._next_index
                self._cur_seg_count = 0
                self._last_term = self._snapshot_term

    def create_snapshot(self, index: int, term: int, state: dict) -> None:
        with self._lock:
            # Write snapshot file
            state_json = json.dumps(state, sort_keys=True).encode('utf-8')

            remaining = struct.pack('<Q', index)
            remaining += struct.pack('<Q', term)
            remaining += struct.pack('<I', len(state_json))
            remaining += state_json

            crc = zlib.crc32(remaining) & 0xFFFFFFFF

            spath = self._snapshot_path(index)
            with open(spath, 'wb') as f:
                f.write(SNAPSHOT_MAGIC)
                f.write(struct.pack('<I', crc))
                f.write(remaining)

            # Remove older snapshots
            for sf in self._list_snapshot_files():
                fp = os.path.join(self._dir, sf)
                fname = sf.replace('snapshot_', '').replace('.snap', '')
                try:
                    si = int(fname)
                    if si < index:
                        os.remove(fp)
                except ValueError:
                    pass

            # Remove segments fully covered by snapshot
            for seg_file in list(self._list_segment_files()):
                fpath = os.path.join(self._dir, seg_file)
                with open(fpath, 'rb') as f:
                    f.read(4)
                    fi = struct.unpack('<Q', f.read(8))[0]
                    ec = struct.unpack('<I', f.read(4))[0]
                last_in_seg = fi + ec - 1
                if last_in_seg <= index:
                    os.remove(fpath)

            self._snapshot_index = index
            self._snapshot_term = term

            # Refresh current-segment bookkeeping
            seg_files = self._list_segment_files()
            if seg_files:
                last_seg = seg_files[-1]
                fpath = os.path.join(self._dir, last_seg)
                with open(fpath, 'rb') as f:
                    f.read(4)
                    fi = struct.unpack('<Q', f.read(8))[0]
                    ec = struct.unpack('<I', f.read(4))[0]
                self._cur_seg_first = fi
                self._cur_seg_count = ec
            else:
                self._cur_seg_first = self._next_index
                self._cur_seg_count = 0

    def load_snapshot(self) -> Optional[Snapshot]:
        with self._lock:
            snap_files = self._list_snapshot_files()
            if not snap_files:
                return None

            fpath = os.path.join(self._dir, snap_files[-1])
            with open(fpath, 'rb') as f:
                magic = f.read(4)
                if magic != SNAPSHOT_MAGIC:
                    raise ValueError(f"Bad snapshot magic: {magic!r}")
                stored_crc = struct.unpack('<I', f.read(4))[0]
                remaining = f.read()

            computed = zlib.crc32(remaining) & 0xFFFFFFFF
            if stored_crc != computed:
                raise ValueError(
                    f"Snapshot CRC mismatch: stored=0x{stored_crc:08x} "
                    f"computed=0x{computed:08x}"
                )

            li = struct.unpack('<Q', remaining[0:8])[0]
            lt = struct.unpack('<Q', remaining[8:16])[0]
            slen = struct.unpack('<I', remaining[16:20])[0]
            sdata = remaining[20:20 + slen]
            state = json.loads(sdata)

            return Snapshot(last_included_index=li, last_included_term=lt, state=state)

    def last_index(self) -> int:
        with self._lock:
            return self._next_index - 1

    def last_term(self) -> int:
        with self._lock:
            return self._last_term


# ------------------------------------------------------------------
# Key-value state machine
# ------------------------------------------------------------------

class KVStateMachine:
    def __init__(self):
        self.state: dict = {}

    def apply(self, command: bytes) -> None:
        text = command.decode('utf-8')
        parts = text.split(' ', 2)
        if not parts:
            return
        op = parts[0].upper()
        if op == 'SET' and len(parts) >= 3:
            self.state[parts[1]] = parts[2]
        elif op == 'DEL' and len(parts) >= 2:
            self.state.pop(parts[1], None)

    def get_state(self) -> dict:
        return dict(self.state)

    def restore(self, state: dict) -> None:
        self.state = dict(state)


# ------------------------------------------------------------------
# Crash recovery
# ------------------------------------------------------------------

def recover(directory: str, state_machine: KVStateMachine,
            max_entries_per_segment: int = 1000) -> WALEngine:
    wal = WALEngine(directory, max_entries_per_segment)

    snap = wal.load_snapshot()
    if snap is not None:
        state_machine.restore(snap.state)
        from_index = snap.last_included_index + 1
    else:
        from_index = 1

    entries = wal.read(from_index)
    for entry in entries:
        state_machine.apply(entry.command)

    return wal
