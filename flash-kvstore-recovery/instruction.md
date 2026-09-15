A NOR flash memory simulator is at `/app/flash_sim.py`. A C reference implementation of a log-structured flash key-value store (TKV1 format) is at `/app/tickv_ref/` (source: `tickv.h`, `tickv.c`, `tickv_tool.c`; compiled CLI: `tickv_tool`).

Implement `/app/kvstore.py` — a Python `FlashKVStore` class that is binary-format-compatible with this C reference implementation. Images written by either implementation must be correctly readable by the other.

Required class interface:

- `FlashKVStore(flash: FlashSimulator)` — construct from flash, recovering any existing data
- `format()` — prepare flash for use
- `put(key: bytes, value: bytes) -> bool` — store a pair (False if flash full)
- `get(key: bytes) -> Optional[bytes]` — retrieve value or None
- `delete(key: bytes) -> bool` — remove key (True if existed)
- `compact()` — reclaim space from invalidated entries
- `list_keys() -> list[bytes]` — all live keys

Beyond basic format compatibility, the implementation must satisfy three additional requirements where the C reference is deficient:

**Crash-safe writes**: If a power failure occurs at any point during a `put()` that overwrites an existing key, recovery must produce either the old value or the new value — never lose the key entirely. The C reference does NOT satisfy this property; analyze it to understand why, and fix it.

**Crash-safe compaction**: If a power failure occurs at any point during `compact()`, no live key-value pair may be lost. After power-on recovery, every key that was live before compaction began must still be retrievable with its correct value. The C reference's compaction is NOT crash-safe either; design yours so that the invariant "every live entry exists on at least one valid flash page" holds at every instant during the operation.

**Wear-leveling**: NOR flash pages have finite erase endurance (~100K cycles). When activating a new page, the implementation must distribute wear across pages to maximize flash lifetime. Wear history must persist across power cycles.

Use the C source and `tickv_tool` CLI to reverse-engineer the on-flash binary format and validate cross-implementation compatibility.