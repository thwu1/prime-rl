A simplified conservative mark-sweep garbage collector at `/app/gc.c` (API in `/app/gc.h`) contains several interacting bugs that cause incorrect collection behavior. Fix all bugs so the GC meets the following requirements.

**Conservative Pointer Scanning**: The GC must recognize both exact and interior pointers. If any registered root contains a value that points anywhere within an allocated object's memory range (not just its start address), that object must survive collection.

**Object Content Scanning**: When tracing a non-atomic object for pointers during marking, every pointer-sized word within the object's full allocation must be examined. No portion of the object may be skipped.

**Disappearing Links**: `gc_register_disappearing_link(void **link)` registers a pointer location. When the object that `*link` points to is determined unreachable during collection, `*link` must be set to `NULL` before the object is reclaimed.

**Finalization**: Registered finalizers must be called when their associated object becomes unreachable, subject to these constraints:

- Finalizers must observe the object's data intact (not zeroed or freed).
- If unreachable finalizable object A contains a pointer to unreachable finalizable object B, A's finalizer must execute before B's (topological ordering).
- If unreachable finalizable objects form a pointer cycle, none of them are finalized. They survive the current collection with their finalizer registrations intact.
- Non-cyclic unreachable finalizable objects must still be finalized even when other objects in the same cycle are skipped.
- After finalization, the object and everything reachable from it must survive the current sweep. The finalizer registration is consumed (one-shot).

**Collection Phase Ordering**: The phases within `gc_collect()` must be sequenced so that disappearing links and finalizers are processed while object metadata and contents remain valid and accessible.

**Build**: `gcc -std=c11 -o test /app/gc.c test_program.c -I/app -g -O1 -Wall` must compile cleanly.

All modifications go in `/app/gc.c`. Do not change `/app/gc.h`.
