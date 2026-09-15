# Write-Ahead Log Binary Format Specification

## Overview

A WAL engine stores log entries across multiple segment files in a single directory.
Snapshots provide compaction by capturing state at a point in time and removing old segments.

## File Naming

- Segment files: `segment_{first_index:010d}.wal` (zero-padded, 10 digits)
- Snapshot files: `snapshot_{last_included_index:010d}.snap` (zero-padded, 10 digits)

Sorting filenames alphabetically yields chronological order.

## Segment File Format

### Segment Header (16 bytes)

| Offset | Size | Type       | Description                          |
|--------|------|------------|--------------------------------------|
| 0      | 4    | bytes      | Magic number: `0x57414C31` ("WAL1")  |
| 4      | 8    | uint64 LE  | first_index: log index of first entry|
| 12     | 4    | uint32 LE  | entry_count: number of entries       |

### Entry Format (repeated entry_count times after header)

| Offset | Size | Type       | Description                            |
|--------|------|------------|----------------------------------------|
| 0      | 4    | uint32 LE  | CRC-32 (IEEE) of bytes [4..end]        |
| 4      | 8    | uint64 LE  | log_index                              |
| 12     | 8    | uint64 LE  | term                                   |
| 20     | 4    | uint32 LE  | command_length                         |
| 24     | N    | bytes      | command_data (command_length bytes)     |

The CRC-32 covers bytes from offset 4 to the end of the entry (i.e., log_index + term + command_length + command_data). Use `zlib.crc32()` masked with `& 0xFFFFFFFF`.

## Snapshot File Format

| Offset | Size | Type       | Description                                |
|--------|------|------------|--------------------------------------------|
| 0      | 4    | bytes      | Magic number: `0x534E4150` ("SNAP")        |
| 4      | 4    | uint32 LE  | CRC-32 of all remaining bytes              |
| 8      | 8    | uint64 LE  | last_included_index                        |
| 16     | 8    | uint64 LE  | last_included_term                         |
| 24     | 4    | uint32 LE  | state_length                               |
| 28     | N    | bytes      | state_data: JSON-encoded dict, UTF-8       |

The CRC-32 covers bytes from offset 8 to EOF (last_included_index + last_included_term + state_length + state_data).

JSON encoding must use `sort_keys=True` for deterministic output.

## Multi-Segment Behavior

- Each segment holds at most `max_entries_per_segment` entries.
- When appending would exceed this limit, a new segment file is created.
- Entries have strictly monotonically increasing 1-based indices.
- Log indices are assigned automatically by the engine.

## Log Truncation (Raft Conflict Resolution)

`truncate(from_index)` removes all entries with index >= from_index:
- Segments entirely at or after from_index are deleted.
- Segments partially affected are rewritten with only the retained entries.
- After truncation, the next append receives index = from_index.

## Snapshot and Compaction

`create_snapshot(index, term, state)`:
1. Writes a new snapshot file.
2. Removes any older snapshot files.
3. Removes segment files where every entry has index <= the snapshot index.
4. Segments containing entries after the snapshot index are preserved.

## Crash Recovery

`recover(directory, state_machine, max_entries_per_segment)`:
1. Opens the WAL directory (scanning segment headers to determine state).
2. Loads the latest snapshot (with CRC verification); restores state_machine from it.
3. Replays all WAL entries after the snapshot's last_included_index into state_machine.
4. Returns the WALEngine, ready for new appends.

If no snapshot exists, replay starts from index 1.

## CRC Integrity

- `read()` and `read_entry()` MUST verify CRC on every entry read from disk.
- `load_snapshot()` MUST verify CRC on the snapshot.
- The constructor MUST NOT fail on corrupted data (corruption is detected on read).
- On CRC mismatch, raise an exception.

## Thread Safety

All public methods (`append`, `read`, `read_entry`, `truncate`, `create_snapshot`, `load_snapshot`, `last_index`, `last_term`) must be safe to call from multiple threads concurrently.

## Required API

```python
class WALEntry:
    index: int      # uint64 log index (1-based)
    term: int       # uint64 term number
    command: bytes  # raw command bytes

class Snapshot:
    last_included_index: int
    last_included_term: int
    state: dict

class WALEngine:
    def __init__(self, directory: str, max_entries_per_segment: int = 1000): ...
    def append(self, term: int, command: bytes) -> int: ...      # returns assigned index
    def read(self, from_index: int) -> list[WALEntry]: ...       # CRC-verified
    def read_entry(self, index: int) -> WALEntry: ...            # CRC-verified
    def truncate(self, from_index: int) -> None: ...
    def create_snapshot(self, index: int, term: int, state: dict) -> None: ...
    def load_snapshot(self) -> Snapshot | None: ...               # CRC-verified
    def last_index(self) -> int: ...                              # 0 if empty
    def last_term(self) -> int: ...                               # 0 if empty

class KVStateMachine:
    def __init__(self): ...
    def apply(self, command: bytes) -> None: ...       # "SET key value" or "DEL key"
    def get_state(self) -> dict[str, str]: ...
    def restore(self, state: dict[str, str]) -> None: ...

def recover(directory: str, state_machine: KVStateMachine,
            max_entries_per_segment: int = 1000) -> WALEngine: ...
```
