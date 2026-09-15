# Ground-Truth Canary Instrumentation — Requirements

## Purpose

Instrument a target library to produce ground-truth measurements of fuzzer effectiveness. For each known vulnerability, the system must track:
- **reached**: how many times the vulnerability's code path was executed
- **triggered**: how many times the vulnerability condition was actually satisfied (the bug would be exploitable)

## File Layout

All files under `/app/`:

| Path | Role |
|------|------|
| `magma/storage.{h,c}` | Persistent storage backend for canary data |
| `magma/canary.{h,c}` | Instrumentation runtime API |
| `magma/monitor.c` | Standalone tool — reads stored canary data, outputs CSV |
| `Makefile` | Multi-mode build system |
| `src/imgutil.c` | Target library (instrument in place) |
| `src/imgutil.h` | Target library header (do not modify) |
| `src/driver.c` | Test driver exercising each bug (do not modify) |

## Instrumentation API

**`MAGMA_LOG(bug_id, condition)`** — When `MAGMA_ENABLE_CANARIES` is defined, records that the bug's code path was reached; if `condition` is nonzero, also records that the bug was triggered. Must compile to a no-op when canaries are disabled.

**`MAGMA_AND(a, b)` / `MAGMA_OR(a, b)`** — Logical AND/OR that must always evaluate both operands, even when the first operand alone would determine the result. This prevents coverage-guided fuzzers from observing the internal branch resolution.

## Source Instrumentation Pattern

Each vulnerability in `src/imgutil.c` must use the three-tier preprocessor guard:

```c
#ifdef MAGMA_ENABLE_FIXES
    /* corrected code that eliminates the vulnerability */
#else
    /* original vulnerable code */
  #ifdef MAGMA_ENABLE_CANARIES
    MAGMA_LOG("BUGxxx", trigger_condition);
  #endif
#endif
```

The **trigger condition** must precisely express when the vulnerability is exploitable — not merely when the surrounding code is executed. Deriving the correct condition requires analyzing each bug's semantics.

## Build System

The Makefile must support (from `/app/`):

| Command | Effect |
|---------|--------|
| `make` | Build `imgutil_driver` and `monitor` (plain mode) |
| `make CANARIES=1` | Build with `-DMAGMA_ENABLE_CANARIES` |
| `make CANARIES=1 FIXES=1` | Build with both `-DMAGMA_ENABLE_CANARIES` and `-DMAGMA_ENABLE_FIXES` |
| `make clean` | Remove all build artifacts |

## Storage

Canary data must be stored in a file whose path is read from the `MAGMA_STORAGE` environment variable (default: `/tmp/magma_canaries.bin`). The storage mechanism must ensure data is available to the monitor process after the target exits, including after abnormal termination.

## Monitor Output

CSV to stdout with header `bug_id,reached,triggered`, one row per registered bug. Must read the `MAGMA_STORAGE` environment variable for the data file path (same default as above). Exit 0 on success, 1 on error.
