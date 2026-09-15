/*
 * runtime.c - MAGMA canary runtime
 *
 * Provides the mmap-backed shared storage for canary instrumentation.
 * When MAGMA_ENABLE_CANARIES is defined, a constructor function initializes
 * the storage automatically before main() executes.
 */

#include "magma.h"
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

#define MAGMA_STORAGE_PATH "/tmp/magma_canary.raw"

magma_store_t *__magma_store = NULL;

void magma_init(void)
{
    int fd = open(MAGMA_STORAGE_PATH, O_RDWR | O_CREAT, 0644);
    if (fd < 0) {
        perror("magma_init: open");
        return;
    }

    struct stat st;
    fstat(fd, &st);

    int needs_zero = 0;
    if (st.st_size < (off_t)sizeof(magma_store_t)) {
        if (ftruncate(fd, sizeof(magma_store_t)) < 0) {
            perror("magma_init: ftruncate");
            close(fd);
            return;
        }
        needs_zero = 1;
    }

    __magma_store = (magma_store_t *)mmap(
        NULL, sizeof(magma_store_t),
        PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);

    if (__magma_store == MAP_FAILED) {
        perror("magma_init: mmap");
        __magma_store = NULL;
        return;
    }

    if (needs_zero) {
        memset(__magma_store, 0, sizeof(magma_store_t));
    }
}

void magma_log(int bug_id, int condition)
{
    if (!__magma_store) return;
    if (bug_id < 0 || bug_id >= NUM_BUGS) return;

    __magma_store->reached[bug_id]++;
    if (condition) {
        __magma_store->triggered[bug_id]++;
    }
}

#ifdef MAGMA_ENABLE_CANARIES
__attribute__((constructor))
static void magma_startup(void)
{
    magma_init();
}
#endif
