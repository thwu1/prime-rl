The C library in `/app/` implements a binary record parsing/serialization pipeline for five telemetry record types (metric, log, alert, trace, audit). It is being integrated into a network daemon that dispatches incoming records to a pool of worker threads.

Production crash reports and data-corruption tickets have been filed against the library's concurrency properties. The current implementation is not safe for concurrent use. Audit the code, identify every source of thread-unsafety and poor production hygiene, and refactor the library so it is correct under concurrent multi-threaded access.

## What must be true when you are done

**Thread safety.** Every public API function must be fully reentrant. The library must produce correct results when four threads each perform 1000 parse/validate/format/serialize iterations concurrently, with no corruption or data races.

**No shared mutable state.** `nm librecord.a` must show zero global or file-scope mutable data symbols. Every piece of state that currently resides in a global variable, static buffer, or lazily-initialized table must be eliminated or replaced with a design that does not share mutable memory across callers.

**Target API.** The daemon team has finalized the API contract that all downstream consumers depend on. It is specified in `/app/api_spec.h`. The refactored public header (`record.h`) and implementation must conform to this API exactly. Legacy error-reporting functions and global error accessors that are not part of the target API must be removed.

**Modular source organization.** The monolithic implementation must be decomposed into multiple compilation units, each with a clear single responsibility. Shared internal helpers and constants should live in a dedicated internal header.

**Binary wire format preservation.** Golden reference records serialized by the original code are stored in `/app/golden/`. The refactored code must parse every golden file correctly and re-serialize each to byte-identical output.

**Build integrity.** `make clean && make` must succeed and produce both `librecord.a` and a working `main` executable. Update `main.c` and the `Makefile` as needed.