# Ground-Truth Canary Instrumentation -- Specification

## Overview

The instrumentation runtime enables ground-truth measurement of fuzzer
effectiveness by tracking when bugs are **reached** (code path executed) and
**triggered** (vulnerability condition satisfied). Data is stored in mmap-based
shared memory so it persists across process crashes.

## Components

### 1. Storage Layer (magma/storage.h, magma/storage.c) — ALREADY PROVIDED

The storage layer is fully implemented. Do not modify these files.

**Binary format** (little-endian, all fields naturally aligned):

| Offset | Size | Field |
|--------|------|-------|
| 0 | 4 | `magic` (uint32_t): must be 0x4D474D41 |
| 4 | 4 | `num_bugs` (uint32_t): count of registered bugs |
| 8 + i*24 + 0 | 16 | `id` (char[16]): null-terminated bug identifier |
| 8 + i*24 + 16 | 4 | `reached` (uint32_t): times code path was executed |
| 8 + i*24 + 20 | 4 | `triggered` (uint32_t): times trigger condition was true |

Maximum 32 bug entries. Each bug entry is exactly 24 bytes.

**Storage file path**: read from `MAGMA_STORAGE` environment variable, defaulting
to `/tmp/magma_canaries.bin`.

**Provided functions**:
- `magma_storage_t *magma_storage_init(void)` — Open/create the backing file,
  mmap with `MAP_SHARED`. Initialize header if needed.
- `int magma_storage_find(magma_storage_t *s, const char *bug_id)` — Find bug
  index by ID string. Return -1 if not found.
- `int magma_storage_register(magma_storage_t *s, const char *bug_id)` — Add a
  new bug entry. Return its index.

### 2. Canary Runtime — YOU MUST CREATE: magma/canary.h, magma/canary.c

**Functions to implement**:
- `void magma_init(void)` — Initialize storage. Call once at program start.
- `void magma_log(const char *bug_id, int condition)` — Register the bug on
  first call (via `magma_storage_find` / `magma_storage_register`). Always
  increment `reached`. If `condition` is nonzero, also increment `triggered`.
- `int magma_and(int a, int b)` — Non-short-circuiting AND. Must be a real
  function call marked `__attribute__((noinline))` so both arguments are
  evaluated before entry, preventing coverage-guided fuzzers from observing
  branch behavior.
- `int magma_or(int a, int b)` — Non-short-circuiting OR. Same requirements.

**Macros to define** (in canary.h):

    #ifdef MAGMA_ENABLE_CANARIES
    #define MAGMA_LOG(bug_id, cond)  magma_log(bug_id, cond)
    #else
    #define MAGMA_LOG(bug_id, cond)  ((void)0)
    #endif

    #define MAGMA_AND(a, b)  magma_and(a, b)
    #define MAGMA_OR(a, b)   magma_or(a, b)

### 3. Monitor — YOU MUST CREATE: magma/monitor.c

Standalone program that reads the storage file and outputs CSV to stdout:

    bug_id,reached,triggered
    BUG001,5,2
    BUG002,3,1

Must read `MAGMA_STORAGE` environment variable for file path (default
`/tmp/magma_canaries.bin`). Exit 0 on success, 1 on error.

### 4. Source Instrumentation — YOU MUST INSTRUMENT: src/imgutil.c

Each vulnerability in `src/imgutil.c` must be wrapped with a three-tier
preprocessor guard:

    #ifdef MAGMA_ENABLE_FIXES
        /* Corrected code that eliminates the vulnerability */
    #else
        /* Original buggy code */
    #ifdef MAGMA_ENABLE_CANARIES
        MAGMA_LOG("BUGxxx", trigger_condition);
    #endif
    #endif

`MAGMA_LOG` must appear BEFORE the buggy operation so the canary is recorded
even if the bug causes a crash. The trigger condition must precisely express
when the vulnerability is exploitable, not merely when code is reached.

You must add `#include "canary.h"` to `src/imgutil.c`.

**Identifying bugs**: There are 5 vulnerabilities (BUG001 through BUG005), one
per function, in declaration order. You must analyze each function to determine:
  (a) what the vulnerability is,
  (b) under what precise condition it becomes exploitable, and
  (c) how to fix it.

**Do not modify** `src/driver.c` or `src/imgutil.h`.

### 5. Build System — YOU MUST UPDATE: Makefile

Must support from /app/:
- `make` — build driver AND monitor (plain mode, no canaries)
- `make CANARIES=1` — build with canary instrumentation (`-DMAGMA_ENABLE_CANARIES`)
- `make CANARIES=1 FIXES=1` — build with canaries and bug fixes (`-DMAGMA_ENABLE_FIXES`)
- `make clean` — remove all build artifacts

**Targets**:
- `imgutil_driver` — links src/imgutil.c, src/driver.c, magma/canary.c,
  magma/storage.c
- `monitor` — standalone from magma/monitor.c

**Compiler flags**:
- `-DMAGMA_ENABLE_CANARIES` when CANARIES=1
- `-DMAGMA_ENABLE_FIXES` when FIXES=1
- `-Imagma/` for include path
