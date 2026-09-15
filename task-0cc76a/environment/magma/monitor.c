/*
 * monitor.c - MAGMA canary monitor
 *
 * Reads the mmap'd canary storage and prints a CSV summary of
 * which bugs have been reached and triggered.
 */

#include "magma.h"
#include <stdio.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>

#define MAGMA_STORAGE_PATH "/tmp/magma_canary.raw"

static const char *bug_names[] = {"IMG001", "IMG002", "IMG003", "IMG004", "IMG005"};

int main(void)
{
    int fd = open(MAGMA_STORAGE_PATH, O_RDONLY);
    if (fd < 0) {
        fprintf(stderr, "Cannot open canary storage: %s\n", MAGMA_STORAGE_PATH);
        return 1;
    }

    magma_store_t *store = (magma_store_t *)mmap(
        NULL, sizeof(magma_store_t),
        PROT_READ, MAP_PRIVATE, fd, 0);
    if (store == MAP_FAILED) {
        perror("mmap");
        close(fd);
        return 1;
    }

    printf("bug_id,reached,triggered\n");
    for (int i = 0; i < NUM_BUGS; i++) {
        printf("%s,%u,%u\n", bug_names[i], store->reached[i], store->triggered[i]);
    }

    munmap(store, sizeof(magma_store_t));
    close(fd);
    return 0;
}
