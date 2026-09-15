A compiled reference implementation of a KV cache block manager for LLM inference serving is installed at `/app/reference/` as a native Python extension module (`block_manager_ref`). No source code is provided.

Write a pure Python implementation at `/app/block_manager.py` that is behaviorally identical to the reference. Your class must be named `BlockManager` and subclass `BlockManagerInterface` from `/app/block_manager_interface.py`.

## Resources

- `/app/reference/` — compiled `.so` module, importable but not human-readable. Binary analysis tools (`nm`, `strings`, `readelf`, `objdump`, `strace`, `ltrace`) are available.
- `/app/block_manager_interface.py` — abstract base class, data structures, and method signatures.
- `/app/explore.py` — interactive harness for probing the reference module with arbitrary operation sequences.
- `/app/traces/` — recorded operation traces (JSON) for replay.

## Acceptance criteria

Your implementation must produce identical `MemorySnapshot` values and consistent `SequenceStatus` values as the reference for any valid operation sequence. Physical block IDs may differ, but memory accounting, block-sharing behavior, and all cumulative counters must match exactly.