#ifndef POOL_H
#define POOL_H

#include <stdint.h>
#include <stddef.h>

#define POOL_TAG(a,b,c,d) \
    ((uint32_t)(a) | ((uint32_t)(b)<<8) | ((uint32_t)(c)<<16) | ((uint32_t)(d)<<24))

typedef struct pool_header {
    uint32_t tag;
    uint32_t size;
    struct pool_header *next;
} pool_header_t;

void *pool_alloc(uint32_t pool_type, size_t size, uint32_t tag);
void  pool_free(void *ptr, uint32_t tag);
void  pool_dump_stats(void);

#define POOL_PAGED    0
#define POOL_NONPAGED 1

#endif
