A Lisp interpreter at `/app/` represents all runtime values as 16-byte tagged unions (`struct Value` in `/app/value.h`). Each value carries a `ValueType` enum and a payload union, wasting memory and preventing values from fitting in a single machine register.

Refactor the value representation so that `sizeof(Value)` is exactly **8 bytes** while preserving complete behavioral compatibility. All eight value types (nil, bool, integer, float, string, symbol, cons, builtin) must remain fully functional. Integers may be restricted to the signed 32-bit range. IEEE 754 special float values (infinity, negative infinity) must remain correct.

The codebase uses direct struct field access patterns (`v.type`, `v.as.integer`, `v.as.cons->car`) throughout `/app/value.c` and `/app/lisp.c` — all such accesses must be updated.

Requirements:
- `make -C /app clean all` succeeds cleanly under `-Wall -Wextra`
- `/app/lisp --sizeof` reports `8`
- The code compiles and runs cleanly with UndefinedBehaviorSanitizer enabled (`-fsanitize=undefined -fno-sanitize-recover=all`)
- No invalid memory accesses under Valgrind (leaks are acceptable — there is no GC)
- `/app/size_report.txt` contains a `pahole` struct layout analysis of the final binary compiled with DWARF debug info