A simple object VM at `/app/` uses **NaN-boxed values** (object pointers encoded in the mantissa bits of IEEE 754 quiet NaN representations) and a **mark-sweep garbage collector** where each object is individually `malloc`'d and linked via an intrusive singly-linked list.

This design causes heap fragmentation: after repeated GC cycles, surviving objects become scattered across the process address space with per-object allocator overhead and poor cache locality.

**Your task:** Convert the VM's memory management from mark-sweep to a **LISP2 mark-compact** garbage collector so that:

1. Objects are no longer individually `malloc`'d — eliminate the per-object `malloc`/`free` pattern entirely. The implementation in `vm.c` must contain **at most one** `free()` call (for freeing the VM struct itself in `freeVM`).
2. The VM stores objects in a contiguous `heap` array with bump-pointer allocation (not a linked list).
3. The `Object` struct must include a **forwarding address pointer** (e.g. `forwardingAddr`) used during the compaction phase to remap references.
4. The GC must implement explicit **mark-compact phases**: mark reachable objects, calculate forwarding addresses, update all references (decoding and re-encoding NaN-boxed pointers via `OBJ_VAL`/`AS_OBJ`), and compact objects via `memmove` to their forwarding addresses.
5. After garbage collection, all surviving objects occupy a contiguous memory region with **no internal gaps** — verified by checking that consecutive live objects are separated by exactly `sizeof(Object)` bytes.
6. New object allocations come from immediately after the last live object in that region.
7. All NaN-boxed value references (on the VM stack, in pair head/tail fields) remain valid when objects are relocated during collection.

**Preservation requirements:**

- The public API in `vm.h` must be preserved: `newVM`, `freeVM`, `push`, `pop`, `peek`, `pushInt`, `pushPair`, `gc`, `printValue`, `printObject`.
- All NaN-boxing macros must be preserved in `vm.h`: `SIGN_BIT`, `QNAN`, `IS_OBJ`, `AS_OBJ`, `OBJ_VAL`, `IS_NUMBER`, `NUMBER_VAL`, `IS_NIL`, `NIL_VAL`.
- The `Object` struct must retain the fields `type`, `intValue`, `head`, and `tail`.

**Verification:**

- `/app/main.c` must compile unmodified and produce correct output for all 8 test cases, ending with `ALL TESTS PASSED`. Expected output includes: `v1 = Int(42)`, `v2 = Int(17)`, `pair = Pair(Int(1), Int(2))`, `pair1 = Pair(Int(10), Int(20))`, `pair2 = Pair(Int(30), Int(40))`, `v = Int(3)`, `outer = Pair(Pair(Int(1), Int(2)), Int(3))`, `result = Pair(Pair(3.14, Int(99)), Pair(nil, true))`, a stress-test linked list starting `0 1 2 3 4` with `(total=100)`, and post-GC allocations `bottom = Int(100)`, `pair_top = Pair(Int(400), Int(500))`.
- Additional C test programs will be compiled against your `vm.h`/`vm.c` to verify: (a) after GC, surviving objects are physically contiguous with stride exactly `sizeof(Object)`, and (b) 50 rounds of interleaved garbage creation and keeper-pair allocation all survive with correct values after a final `gc()` call.
- The solution must run clean under **Valgrind** with no memory errors, zero definite leaks, and exit code 0: `cd /app && valgrind --leak-check=full --error-exitcode=99 ./vm_test`

Build and test: `cd /app && make clean && make && ./vm_test`