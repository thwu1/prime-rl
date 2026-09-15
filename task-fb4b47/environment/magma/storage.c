#include "storage.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>

static const char *get_storage_path(void) {
    const char *p = getenv("MAGMA_STORAGE");
    return p ? p : "/tmp/magma_canaries.bin";
}

magma_storage_t *magma_storage_init(void) {
    const char *path = get_storage_path();
    size_t sz = sizeof(magma_storage_t);

    int fd = open(path, O_RDWR | O_CREAT, 0666);
    if (fd < 0) {
        perror("magma_storage_init: open");
        return NULL;
    }

    if (ftruncate(fd, (off_t)sz) < 0) {
        perror("magma_storage_init: ftruncate");
        close(fd);
        return NULL;
    }

    magma_storage_t *s = (magma_storage_t *)mmap(
        NULL, sz, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);

    if (s == MAP_FAILED) {
        perror("magma_storage_init: mmap");
        return NULL;
    }

    if (s->magic != MAGMA_STORAGE_MAGIC) {
        memset(s, 0, sz);
        s->magic = MAGMA_STORAGE_MAGIC;
        s->num_bugs = 0;
    }

    return s;
}

int magma_storage_find(magma_storage_t *s, const char *bug_id) {
    for (uint32_t i = 0; i < s->num_bugs; i++) {
        if (strncmp(s->bugs[i].id, bug_id, MAGMA_BUG_ID_LEN) == 0)
            return (int)i;
    }
    return -1;
}

int magma_storage_register(magma_storage_t *s, const char *bug_id) {
    if (s->num_bugs >= MAGMA_MAX_BUGS) {
        fprintf(stderr, "magma: too many bugs registered\n");
        return -1;
    }
    int idx = (int)s->num_bugs++;
    strncpy(s->bugs[idx].id, bug_id, MAGMA_BUG_ID_LEN - 1);
    s->bugs[idx].id[MAGMA_BUG_ID_LEN - 1] = '\0';
    s->bugs[idx].reached = 0;
    s->bugs[idx].triggered = 0;
    return idx;
}
