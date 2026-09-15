#ifndef MAGMA_STORAGE_H
#define MAGMA_STORAGE_H

#include <stdint.h>

#define MAGMA_MAX_BUGS 32
#define MAGMA_STORAGE_MAGIC 0x4D474D41  /* "MGMA" */
#define MAGMA_BUG_ID_LEN 16

typedef struct {
    char id[MAGMA_BUG_ID_LEN];
    uint32_t reached;
    uint32_t triggered;
} magma_bug_t;

typedef struct {
    uint32_t magic;
    uint32_t num_bugs;
    magma_bug_t bugs[MAGMA_MAX_BUGS];
} magma_storage_t;

magma_storage_t *magma_storage_init(void);
int magma_storage_find(magma_storage_t *s, const char *bug_id);
int magma_storage_register(magma_storage_t *s, const char *bug_id);

#endif
