/*
 * canary.h - MAGMA-style ground-truth canary instrumentation framework
 *
 * Provides compile-time canary instrumentation for vulnerability detection.
 * When MAGMA_ENABLE_CANARIES is defined, MAGMA_LOG() records when buggy code
 * paths are reached and when exploit-triggering conditions are met.
 *
 * Usage:
 *   MAGMA_LOG("BUG_ID", trigger_condition);
 *     - Always increments the "reached" counter for BUG_ID
 *     - Increments the "triggered" counter when trigger_condition is true
 *     - Dumps counters to file on each call (crash-safe)
 *
 *   MAGMA_AND(a, b) / MAGMA_OR(a, b):
 *     - Branchless logical operators for use in trigger conditions
 *     - Must be used instead of && and || to avoid creating branches
 *       that confuse coverage-guided fuzzers
 */

#ifndef CANARY_H
#define CANARY_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    unsigned long reached;
    unsigned long triggered;
} bug_counter_t;

#define MAX_BUGS 64

extern bug_counter_t __magma_bugs[MAX_BUGS];
extern int __magma_bug_count;
extern char *__magma_bug_names[MAX_BUGS];
extern const char *__magma_output_path;

static inline int __magma_register_bug(const char *name) {
    for (int i = 0; i < __magma_bug_count; i++) {
        if (strcmp(__magma_bug_names[i], name) == 0) return i;
    }
    int idx = __magma_bug_count++;
    __magma_bug_names[idx] = strdup(name);
    __magma_bugs[idx].reached = 0;
    __magma_bugs[idx].triggered = 0;
    return idx;
}

static inline void __magma_dump(const char *path) {
    FILE *f = fopen(path, "w");
    if (!f) return;
    for (int i = 0; i < __magma_bug_count; i++) {
        fprintf(f, "%s_R,%lu\n%s_T,%lu\n",
                __magma_bug_names[i], __magma_bugs[i].reached,
                __magma_bug_names[i], __magma_bugs[i].triggered);
    }
    fclose(f);
}

static inline void __magma_init(const char *output_path) {
    __magma_output_path = output_path;
}

#ifdef MAGMA_ENABLE_CANARIES
#define MAGMA_LOG(bug_id, trigger_cond) do { \
    int __idx = __magma_register_bug(bug_id); \
    __magma_bugs[__idx].reached++; \
    if (trigger_cond) { \
        __magma_bugs[__idx].triggered++; \
    } \
    if (__magma_output_path) __magma_dump(__magma_output_path); \
} while(0)
#else
#define MAGMA_LOG(bug_id, trigger_cond) do { } while(0)
#endif

/* Branchless logical operators — use these instead of && and || in
 * MAGMA_LOG trigger conditions to avoid creating branches that confuse
 * coverage-guided fuzzers. */
#define MAGMA_AND(a, b) ((!!(a)) & (!!(b)))
#define MAGMA_OR(a, b)  ((!!(a)) | (!!(b)))

#endif /* CANARY_H */
