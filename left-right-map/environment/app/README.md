# Left-Right Concurrent Multi-Value Map

A thread-safe multi-value map supporting one writer and multiple concurrent
readers. Readers experience wait-free access and see consistent, isolated
snapshots of the map state.

## Architecture

The library maintains **two internal copies** of a dictionary-based multi-value
map. Readers access one copy while the writer prepares updates on the other.
When the writer calls `publish()`, the copies swap roles, making buffered
writes visible to readers.

### Epoch Tracking

Each `ReadHandle` maintains an epoch counter (a mutable `[int]`). The parity
of the epoch distinguishes state:

- **Even** = idle (not currently reading)
- **Odd** = actively reading (holding a `ReadGuard`)

The writer uses epoch snapshots to determine when it is safe to modify the
stale copy. After each swap, it records every reader's current epoch. On the
**next** publish, it waits only for readers whose recorded epoch was odd
(meaning they were reading the copy that is about to become the write target).
If a reader's epoch has changed since the snapshot, it has already released
its guard.

### Oplog & Dual Application

Operations after the first publish are buffered in an **operational log
(oplog)**. Each entry must be applied to **both** copies — once when it is
first published, and again on the following publish to bring the other copy
up to date. A `swap_index` tracks which entries have been applied once
(and still need a second application) versus entries that are brand new.

The publish cycle:
1. Apply `oplog[0..swap_index]` to the write copy (second application)
2. Drain those entries
3. Apply remaining oplog entries (first application)
4. Set `swap_index = len(remaining_oplog)`
5. Swap the copies

### First-Publish Optimization

Before the first `publish()`, no readers can be on the write copy, so
operations are applied directly (bypassing the oplog).

## Usage

```python
from left_right_map import LeftRightMap

w, r = LeftRightMap.new()
w.insert("key", "value1")
w.insert("key", "value2")
w.publish()  # make writes visible to readers

print(r.get("key"))  # ["value1", "value2"]
```

## API Reference

### `LeftRightMap.new() -> (WriteHandle, ReadHandle)`

Create a new map. Returns a write handle and a read handle.

### WriteHandle (single writer)

| Method | Description |
|---|---|
| `insert(key, value)` | Add value to the set for key |
| `remove_value(key, value)` | Remove a specific value from key |
| `remove_entry(key)` | Remove key and all its values |
| `clear()` | Remove all entries |
| `publish()` | Atomically expose all pending writes to readers |
| `has_pending()` | True if unpublished operations exist |
| `destroy()` | Shut down the map |

### ReadHandle (per-thread reader)

| Method | Description |
|---|---|
| `enter() -> ReadGuard or None` | Acquire a snapshot (None after destroy) |
| `get(key)` | Convenience: read values for key |
| `len()` | Number of keys |
| `contains_key(key)` | Check key existence |
| `keys()` | List of all keys |
| `clone()` | Create an independent reader for another thread |
| `was_dropped()` | True if writer called destroy |

### ReadGuard (snapshot access)

Provides a frozen view of the map at the time `enter()` was called.

| Method | Description |
|---|---|
| `get(key)` | Read values for key (returns a copy) |
| `len()` | Number of keys in snapshot |
| `contains_key(key)` | Check key existence in snapshot |
| `keys()` | List of keys in snapshot |
| `release()` | Release the guard |

Supports `with` statement for automatic release.

## Concurrency Guarantees

- Multiple readers never block each other.
- A `ReadGuard` provides a frozen snapshot unaffected by concurrent publishes.
- `publish()` is atomic: readers see either all or none of a batch of writes.
- Guards that existed before `destroy()` remain usable until released.
- Values returned by `get()` are independent copies.
