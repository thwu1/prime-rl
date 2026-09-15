# Signal Tree Specification

## Overview

A **signal tree** is a lock-free concurrent data structure that manages 512 binary signals (indexed 0–511). Each signal can be in one of two states: **active** or **inactive**. All signals begin inactive.

The data structure supports two primary operations and must function correctly under arbitrary concurrent access from multiple threads.

## Operations

### set(index)

Activates the signal at the given index (0 ≤ index < 512).

**Behavior:**
- If the signal was previously inactive, it becomes active.
  - `signal_was_new` is set to `true`.
  - If the entire data structure had no active signals immediately before this activation, `tree_was_empty` is set to `true`.
- If the signal was already active, the call is logically a no-op.
  - `signal_was_new` is set to `false`.
  - `tree_was_empty` is set to `false`.

**Thread-safety requirement:** This operation must be **wait-free** — it must complete in a bounded number of steps regardless of contention from other threads. It must not contain retry loops.

### select(bias)

Atomically claims and deactivates one active signal, returning its index.

**Behavior:**
- If no signals are active, returns `ST_INVALID_INDEX`.
- Otherwise, finds one active signal, atomically deactivates it (so no other concurrent select can return the same signal for the same activation), and returns its index.
- The `bias` parameter is a 64-bit hint that influences which active signal is selected. Different bias values should tend to select different signals when multiple are active, helping distribute contention across threads.
- `tree_is_empty` is set to `true` if the data structure appeared to become empty as a direct result of this select.

**Thread-safety requirement:** This operation must be **lock-free** — it may retry under contention but must guarantee system-wide progress (at least one thread always makes progress).

### empty()

Returns `true` if no signals are currently active.

## Correctness Invariants

These invariants must hold under concurrent access:

1. **No lost signals:** Every newly activated signal must be selectable exactly once. At quiescence (no operations in flight), the total count of successful new activations minus the total count of successful selects must equal the number of currently active signals.

2. **No duplicate selects:** A single activation of a signal yields at most one successful select. Two concurrent selects must never both return the same signal index for the same activation.

3. **Idempotent double-set:** Setting an already-active signal does not create a second "copy." Only one select should result from multiple consecutive sets of the same index without an intervening select.

4. **Atomic claim:** The select operation must atomically transition a signal from active to inactive. There must be no window where two selects can both observe the same signal as active and both succeed in claiming it.

5. **Internal consistency:** At quiescence, the data structure's internal bookkeeping must accurately reflect which signals are active. No phantom signals (selectable but never set) or stuck signals (set but never selectable) may exist.

## Constraints

- The implementation must **not** use mutexes, condition variables, read-write locks, or any other blocking synchronization primitives.
- Use only C11 atomic operations (`<stdatomic.h>`) for thread coordination.
- The data structure must handle the full 512-signal capacity.
- Performance should scale reasonably with 4+ concurrent threads.

## API Reference

See `signal_tree.h` for the exact C function signatures, type definitions, and constants.
