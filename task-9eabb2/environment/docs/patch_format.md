# MAGMA Patch Format Specification

## Overview

MAGMA instruments known bugs using unified diff patches that wrap vulnerable code
in conditional compilation guards. Each patch creates two alternative code paths:

1. **Fixed path** (`MAGMA_ENABLE_FIXES`): The corrected code that eliminates the bug
2. **Canary path** (`MAGMA_ENABLE_CANARIES`): An oracle that detects when the bug's
   trigger condition is met, while leaving the original buggy code in place

## Patch Structure

A MAGMA patch modifies the source code to add conditional compilation blocks:

```c
#ifdef MAGMA_ENABLE_FIXES
    // Corrected code path — vulnerability eliminated
    corrected_implementation();
#else
    // Original buggy code remains for fuzzing
#ifdef MAGMA_ENABLE_CANARIES
    MAGMA_LOG("%MAGMA_BUG%", trigger_condition);
#endif
    original_buggy_code();
#endif
```

### Key elements:

- `#ifdef MAGMA_ENABLE_FIXES` wraps the corrected code
- `#ifdef MAGMA_ENABLE_CANARIES` wraps the oracle instrumentation
- `MAGMA_LOG(bug_id, condition)` records when a bug is reached and triggered
- `%MAGMA_BUG%` is a token replaced with the bug identifier during patch application

## MAGMA_LOG Semantics

```c
MAGMA_LOG(char *bug_id, int trigger_condition)
```

Every call to MAGMA_LOG increments the **reached** counter for that bug. If
`trigger_condition` evaluates to non-zero (true), the **triggered** counter
is also incremented.

- **Reached (BUG_R)**: The code path containing the bug was executed
- **Triggered (BUG_T)**: The input state makes the vulnerability exploitable

The trigger condition must precisely capture the boolean condition under which
the vulnerability becomes dangerous — not merely when the code path is executed.

## Branchless Logical Operators

Compound trigger conditions MUST use `MAGMA_AND` and `MAGMA_OR` macros instead
of C's `&&` and `||` operators. The standard short-circuit operators create
branches that confuse coverage-guided fuzzers:

```c
// WRONG — creates branches visible to coverage instrumentation
MAGMA_LOG("BUG001", a > 0 && b < len);

// CORRECT — branchless evaluation
MAGMA_LOG("BUG001", MAGMA_AND(a > 0, b < len));
```

Definitions:
```c
#define MAGMA_AND(a, b) ((!!(a)) & (!!(b)))
#define MAGMA_OR(a, b)  ((!!(a)) | (!!(b)))
```

## Build Modes

The same patched source compiles in three modes:

| Mode | Flags | Behavior |
|------|-------|----------|
| Canary | `-DMAGMA_ENABLE_CANARIES` | Bugs active + oracle logging |
| Fixed | `-DMAGMA_ENABLE_FIXES` | Bugs fixed, no canaries |
| Default | (none) | Bugs active, no instrumentation |

## Patch File Format

Patches are standard unified diffs with `a/` and `b/` path prefixes:

```
--- a/mfp.c
+++ b/mfp.c
@@ -line,count +line,count @@
 context line
-removed line
+added line
 context line
```

The `%MAGMA_BUG%` token in the patch is replaced by `apply_patches.sh` with
the patch filename (without extension). For example, `MFP001.patch` results
in `MAGMA_LOG("MFP001", ...)` in the compiled source.

## Example: Real MAGMA Patch (CVE-2018-13785, libpng)

```c
+#ifdef MAGMA_ENABLE_FIXES
     size_t row_factor = (size_t)png_ptr->width * (size_t)png_ptr->channels * ...
+#else
+    size_t row_factor_l = (size_t)png_ptr->width * ...
+#ifdef MAGMA_ENABLE_CANARIES
+    MAGMA_LOG("%MAGMA_BUG%", row_factor_l == ((size_t)1 << (sizeof(png_uint_32) * 8)));
+#endif
+    size_t row_factor = (png_uint_32)row_factor_l;  // Truncation causes bug
+#endif
```

In this example:
- **Fix**: Uses `size_t` for the full-precision computation
- **Bug**: Truncates the result to `png_uint_32` (32-bit), losing upper bits
- **Oracle**: Detects when truncation actually changes the value (overflow condition)
