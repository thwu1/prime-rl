#include "canary.h"
#include <string.h>

static magma_storage_t *storage = NULL;

void magma_init(void) {
    storage = magma_storage_init();
}

void magma_log(const char *bug_id, int condition) {
    if (!storage) return;

    int idx = magma_storage_find(storage, bug_id);
    if (idx < 0) {
        idx = magma_storage_register(storage, bug_id);
        if (idx < 0) return;
    }

    storage->bugs[idx].reached++;
    if (condition) {
        storage->bugs[idx].triggered++;
    }
}
