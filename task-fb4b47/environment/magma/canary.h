#ifndef MAGMA_CANARY_H
#define MAGMA_CANARY_H

#include "storage.h"

void magma_init(void);
void magma_log(const char *bug_id, int condition);

#ifdef MAGMA_ENABLE_CANARIES
#define MAGMA_LOG(bug_id, cond)  magma_log(bug_id, cond)
#else
#define MAGMA_LOG(bug_id, cond)  ((void)0)
#endif

/* Compound condition operators */
#define MAGMA_AND(a, b) ((a) && (b))
#define MAGMA_OR(a, b)  ((a) || (b))

#endif
