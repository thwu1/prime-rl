#!/usr/bin/env python3
"""Create the complete ground-truth canary instrumentation system from scratch."""

import os


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    print(f"  Created {path}")


# ============================================================
# CREATE 1: magma/canary.h — canary runtime header
# Non-short-circuiting operators use noinline function calls
# so both arguments are evaluated before entry.
# ============================================================
write_file("/app/magma/canary.h", r"""#ifndef MAGMA_CANARY_H
#define MAGMA_CANARY_H

#include "storage.h"

void magma_init(void);
void magma_log(const char *bug_id, int condition);

__attribute__((noinline)) int magma_and(int a, int b);
__attribute__((noinline)) int magma_or(int a, int b);

#ifdef MAGMA_ENABLE_CANARIES
#define MAGMA_LOG(bug_id, cond)  magma_log(bug_id, cond)
#else
#define MAGMA_LOG(bug_id, cond)  ((void)0)
#endif

#define MAGMA_AND(a, b)  magma_and(a, b)
#define MAGMA_OR(a, b)   magma_or(a, b)

#endif
""")

# ============================================================
# CREATE 2: magma/canary.c — canary runtime implementation
# ============================================================
write_file("/app/magma/canary.c", r"""#include "canary.h"
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

__attribute__((noinline))
int magma_and(int a, int b) {
    return a && b;
}

__attribute__((noinline))
int magma_or(int a, int b) {
    return a || b;
}
""")

# ============================================================
# CREATE 3: magma/monitor.c — standalone CSV monitor
# Reads MAGMA_STORAGE env var for file path.
# ============================================================
write_file("/app/magma/monitor.c", r"""#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "storage.h"

int main(void) {
    const char *path = getenv("MAGMA_STORAGE");
    if (!path) path = "/tmp/magma_canaries.bin";

    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "monitor: cannot open %s\n", path);
        return 1;
    }

    magma_storage_t s;
    memset(&s, 0, sizeof(s));
    size_t nread = fread(&s, 1, sizeof(s), f);
    fclose(f);

    if (nread < 8) {
        fprintf(stderr, "monitor: file too small (%zu bytes)\n", nread);
        return 1;
    }

    if (s.magic != MAGMA_STORAGE_MAGIC) {
        fprintf(stderr, "monitor: bad magic 0x%08X\n", s.magic);
        return 1;
    }

    printf("bug_id,reached,triggered\n");
    for (uint32_t i = 0; i < s.num_bugs && i < MAGMA_MAX_BUGS; i++) {
        printf("%s,%u,%u\n", s.bugs[i].id, s.bugs[i].reached, s.bugs[i].triggered);
    }

    return 0;
}
""")

# ============================================================
# CREATE 4: Updated Makefile with CANARIES/FIXES and monitor
# ============================================================
makefile = "CC = gcc\nCFLAGS = -Wall -g -Imagma/\n\n"
makefile += "ifeq ($(CANARIES),1)\nCFLAGS += -DMAGMA_ENABLE_CANARIES\nendif\n\n"
makefile += "ifeq ($(FIXES),1)\nCFLAGS += -DMAGMA_ENABLE_FIXES\nendif\n\n"
makefile += "all: imgutil_driver monitor\n\n"
makefile += "imgutil_driver: src/imgutil.c src/driver.c magma/canary.c magma/storage.c\n"
makefile += "\t$(CC) $(CFLAGS) -o $@ $^\n\n"
makefile += "monitor: magma/monitor.c\n"
makefile += "\t$(CC) -Wall -g -Imagma/ -o $@ $<\n\n"
makefile += "clean:\n"
makefile += "\trm -f imgutil_driver monitor\n\n"
makefile += ".PHONY: all clean\n"

write_file("/app/Makefile", makefile)

# ============================================================
# CREATE 5: Instrument src/imgutil.c with three-tier guards
# ============================================================
write_file("/app/src/imgutil.c", r"""#include "imgutil.h"
#include <string.h>
#include <stdlib.h>
#include "canary.h"

/* BUG001: Integer overflow in dimension validation. */
int img_validate_dimensions(unsigned int width, unsigned int height, unsigned int bpp) {
#ifdef MAGMA_ENABLE_FIXES
    uint64_t total_size_64 = (uint64_t)width * height * bpp;
    if (total_size_64 > MAX_IMAGE_SIZE) return -1;
    return (int)total_size_64;
#else
    unsigned int total_size = width * height * bpp;
#ifdef MAGMA_ENABLE_CANARIES
    MAGMA_LOG("BUG001", ((uint64_t)width * height * bpp) != (uint64_t)total_size);
#endif
    if (total_size > MAX_IMAGE_SIZE) return -1;
    return (int)total_size;
#endif
}

/* BUG002: Heap buffer over-read in palette lookup. */
int img_apply_palette(unsigned char *pixels, int num_pixels,
                      const unsigned char *palette, int palette_entries) {
    for (int i = 0; i < num_pixels; i++) {
        int idx = pixels[i];
#ifdef MAGMA_ENABLE_FIXES
        if (idx >= palette_entries) {
            pixels[i] = 0;
            continue;
        }
#else
#ifdef MAGMA_ENABLE_CANARIES
        MAGMA_LOG("BUG002", idx >= palette_entries);
#endif
#endif
        pixels[i] = palette[idx];
    }
    return 0;
}

/* BUG003: Off-by-one in scanline sub-filter. */
int img_filter_scanline(unsigned char *scanline, int length, unsigned char filter_type) {
    if (filter_type != 1) return 0;
#ifdef MAGMA_ENABLE_FIXES
    for (int i = 1; i < length; i++) {
        scanline[i] = (scanline[i] + scanline[i - 1]) & 0xFF;
    }
#else
    for (int i = 1; i <= length; i++) {
#ifdef MAGMA_ENABLE_CANARIES
        MAGMA_LOG("BUG003", i == length);
#endif
        scanline[i] = (scanline[i] + scanline[i - 1]) & 0xFF;
    }
#endif
    return 0;
}

/* BUG004: Missing bounds check in metadata copy. */
int img_parse_metadata(const char *data, int length, char *output, int output_size) {
    int write_pos = 0;
    for (int i = 0; i < length; i++) {
        if (data[i] == '\n') continue;
#ifdef MAGMA_ENABLE_FIXES
        if (write_pos >= output_size - 1) break;
#else
#ifdef MAGMA_ENABLE_CANARIES
        MAGMA_LOG("BUG004", write_pos >= output_size);
#endif
#endif
        output[write_pos++] = data[i];
    }
    output[write_pos] = '\0';
    return write_pos;
}

/* BUG005: Signed integer confusion in chunk length validation. */
int img_validate_chunk(const unsigned char *chunk, int chunk_len) {
    unsigned int raw = ((unsigned int)chunk[0] << 24) | ((unsigned int)chunk[1] << 16) |
                       ((unsigned int)chunk[2] << 8) | (unsigned int)chunk[3];
#ifdef MAGMA_ENABLE_FIXES
    if (raw > (unsigned int)(chunk_len - 4)) return -1;
    return (int)raw;
#else
    int stated_len = (int)raw;
#ifdef MAGMA_ENABLE_CANARIES
    MAGMA_LOG("BUG005", stated_len < 0);
#endif
    if (stated_len > chunk_len - 4) return -1;
    return stated_len;
#endif
}
""")

print("\nAll files created successfully.")
