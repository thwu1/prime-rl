#!/usr/bin/env python3
"""Fix the four bugs in the streaming pipeline code.

Bug 1 — WatermarkCombiner._compute_combined():
    Uses max() instead of min(). The combined watermark must be the
    MINIMUM across all input channels, because only the slowest channel
    determines how far event-time has definitively progressed.

Bug 2 — KeyedStateBackend (get_state / set_state / clear_state):
    Uses only ``state_name`` as the storage key, ignoring the ``key``
    parameter. This causes state for different keys (e.g. different
    account IDs) to collide. The fix namespaces storage by combining
    key and state_name into a composite key.

Bug 3 — CheckpointCoordinator (trigger / acknowledge):
    Tracks acknowledgments with an integer counter instead of a set of
    task IDs. A duplicate ack from the same task increments the counter
    and may cause premature checkpoint completion. The fix uses a set
    to track which unique tasks have acked.

Bug 4 — TransactionSource.restore():
    Restores offset to ``state["offset"] - 1``, causing the last
    already-processed event to be replayed on recovery. The snapshot
    stores the index of the NEXT event to emit, so restore should use
    the value directly without subtracting.
"""

import re


def fix_streaming():
    with open("/app/streaming.py", "r") as f:
        code = f.read()

    # --- Bug 1: WatermarkCombiner max → min ---
    code = code.replace(
        "return max(self._channel_marks.values())",
        "return min(self._channel_marks.values())",
    )

    # --- Bug 2: KeyedStateBackend — add key namespace ---
    code = code.replace(
        'return self._store.get(state_name, default)',
        'return self._store.get(f"{key}:{state_name}", default)',
    )
    code = code.replace(
        'self._store[state_name] = value',
        'self._store[f"{key}:{state_name}"] = value',
    )
    code = code.replace(
        'self._store.pop(state_name, None)',
        'self._store.pop(f"{key}:{state_name}", None)',
    )

    # --- Bug 3: CheckpointCoordinator counter → set ---
    code = code.replace(
        'self._pending[checkpoint_id] = 0',
        'self._pending[checkpoint_id] = set()',
    )
    code = code.replace(
        'self._pending[checkpoint_id] += 1',
        'self._pending[checkpoint_id].add(task_id)',
    )
    code = code.replace(
        'if self._pending[checkpoint_id] >= self._num_tasks:',
        'if len(self._pending[checkpoint_id]) >= self._num_tasks:',
    )

    with open("/app/streaming.py", "w") as f:
        f.write(code)


def fix_pipeline():
    with open("/app/pipeline.py", "r") as f:
        code = f.read()

    # --- Bug 4: TransactionSource.restore offset ---
    code = code.replace(
        'self._offset = state["offset"] - 1',
        'self._offset = state["offset"]',
    )

    with open("/app/pipeline.py", "w") as f:
        f.write(code)


if __name__ == "__main__":
    fix_streaming()
    fix_pipeline()
    print("All four bugs fixed.")
