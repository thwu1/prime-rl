/*
 * magma.h - MAGMA Ground-Truth Fuzzing Benchmark Canary API
 *
 * This header defines the instrumentation macros used by the MAGMA benchmark
 * to track when bugs are reached and triggered during fuzzing campaigns.
 *
 * Usage:
 *   #include "magma.h"
 *
 *   // Inside a function containing a known bug:
 *   #ifdef MAGMA_ENABLE_CANARIES
 *       MAGMA_LOG(BUG_ID, trigger_condition);
 *   #endif
 *
 *   #ifdef MAGMA_ENABLE_FIXES
 *       // Corrected (safe) code path
 *   #else
 *       // Original buggy code path
 *   #endif
 *
 * IMPORTANT: When the trigger condition involves multiple sub-conditions,
 * you MUST use MAGMA_AND() / MAGMA_OR() instead of && and ||.
 * Short-circuit evaluation in && and || creates implicit branches that
 * leak coverage information to coverage-guided fuzzers, biasing their
 * search strategy and invalidating ground-truth measurements.
 *
 *   WRONG:  MAGMA_LOG(BUG, cond_a && cond_b)
 *   RIGHT:  MAGMA_LOG(BUG, MAGMA_AND(cond_a, cond_b))
 *
 *   WRONG:  MAGMA_LOG(BUG, cond_a || cond_b)
 *   RIGHT:  MAGMA_LOG(BUG, MAGMA_OR(cond_a, cond_b))
 */

#ifndef MAGMA_H
#define MAGMA_H

#include <stdint.h>

/* Bug identifiers — used as array indices into canary storage */
#define IMG001 0
#define IMG002 1
#define IMG003 2
#define IMG004 3
#define IMG005 4
#define NUM_BUGS 5

/* Canary storage layout: per-bug reached and triggered counters */
typedef struct {
    uint32_t reached[NUM_BUGS];
    uint32_t triggered[NUM_BUGS];
} magma_store_t;

/* Global pointer to mmap'd canary storage (defined in runtime.c) */
extern magma_store_t *__magma_store;

/* Runtime functions (defined in runtime.c) */
void magma_init(void);
void magma_log(int bug_id, int condition);

#ifdef MAGMA_ENABLE_CANARIES

#define MAGMA_LOG(id, cond) magma_log((id), (cond))

/*
 * Bitwise logical operators that evaluate BOTH operands unconditionally.
 * Unlike && and ||, these do not short-circuit, preventing coverage
 * instrumentation from generating branches that leak information about
 * which sub-condition was satisfied.
 */
#define MAGMA_AND(a, b) ((!!(a)) & (!!(b)))
#define MAGMA_OR(a, b)  ((!!(a)) | (!!(b)))

#else /* !MAGMA_ENABLE_CANARIES */

#define MAGMA_LOG(id, cond) ((void)0)
#define MAGMA_AND(a, b) ((a) && (b))
#define MAGMA_OR(a, b)  ((a) || (b))

#endif /* MAGMA_ENABLE_CANARIES */

#endif /* MAGMA_H */
