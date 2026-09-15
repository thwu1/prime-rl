/*
 * tickv_tool — CLI front-end for TKV1 flash images
 *
 */

#include "tickv.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---- file I/O ---- */

static uint8_t *load_image(const char *path, size_t *sz) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return NULL; }
    fseek(f, 0, SEEK_END);
    *sz = (size_t)ftell(f);
    rewind(f);
    uint8_t *buf = malloc(*sz);
    if (fread(buf, 1, *sz, f) != *sz) {
        perror("fread"); free(buf); fclose(f); return NULL;
    }
    fclose(f);
    return buf;
}

static int save_image(const char *path, const uint8_t *d, size_t sz) {
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); return -1; }
    fwrite(d, 1, sz, f);
    fclose(f);
    return 0;
}

/* ---- callbacks ---- */

static void print_key(const uint8_t *key, uint8_t kl) {
    fwrite(key, 1, kl, stdout);
    putchar('\n');
}

/* ---- commands ---- */

static int cmd_init(const char *file, int np) {
    size_t sz = (size_t)np * TKV_PAGE_SIZE;
    uint8_t *flash = malloc(sz);
    memset(flash, 0xFF, sz);
    tkv_store_t st;
    tkv_open(&st, flash, np);
    tkv_format(&st);
    int r = save_image(file, flash, sz);
    free(flash);
    if (r == 0)
        printf("Created %s: %d pages, %zu bytes\n", file, np, sz);
    return r;
}

static int cmd_put(const char *file, const char *key, const char *val) {
    size_t sz;
    uint8_t *flash = load_image(file, &sz);
    if (!flash) return 1;
    tkv_store_t st;
    tkv_open(&st, flash, (int)(sz / TKV_PAGE_SIZE));
    int r = tkv_put(&st, (const uint8_t *)key, (uint8_t)strlen(key),
                        (const uint8_t *)val, (uint32_t)strlen(val));
    if (r < 0) {
        fprintf(stderr, "put failed (flash full?)\n");
        free(flash); return 1;
    }
    save_image(file, flash, sz);
    free(flash);
    return 0;
}

static int cmd_get(const char *file, const char *key) {
    size_t sz;
    uint8_t *flash = load_image(file, &sz);
    if (!flash) return 1;
    tkv_store_t st;
    tkv_open(&st, flash, (int)(sz / TKV_PAGE_SIZE));
    uint8_t *v; uint32_t vl;
    int r = tkv_get(&st, (const uint8_t *)key, (uint8_t)strlen(key), &v, &vl);
    if (r < 0) { printf("NOT_FOUND\n"); free(flash); return 1; }
    if (vl > 0) fwrite(v, 1, vl, stdout);
    putchar('\n');
    free(flash);
    return 0;
}

static int cmd_delete(const char *file, const char *key) {
    size_t sz;
    uint8_t *flash = load_image(file, &sz);
    if (!flash) return 1;
    tkv_store_t st;
    tkv_open(&st, flash, (int)(sz / TKV_PAGE_SIZE));
    int r = tkv_delete(&st, (const uint8_t *)key, (uint8_t)strlen(key));
    if (r < 0) { printf("KEY_NOT_FOUND\n"); free(flash); return 1; }
    save_image(file, flash, sz);
    free(flash);
    return 0;
}

static int cmd_list(const char *file) {
    size_t sz;
    uint8_t *flash = load_image(file, &sz);
    if (!flash) return 1;
    tkv_store_t st;
    tkv_open(&st, flash, (int)(sz / TKV_PAGE_SIZE));
    tkv_list_keys(&st, print_key);
    free(flash);
    return 0;
}

static int cmd_dump(const char *file) {
    size_t sz;
    uint8_t *flash = load_image(file, &sz);
    if (!flash) return 1;
    int np = (int)(sz / TKV_PAGE_SIZE);

    for (int p = 0; p < np; p++) {
        uint8_t *page = flash + p * TKV_PAGE_SIZE;
        tkv_page_hdr_t *ph = (tkv_page_hdr_t *)page;
        printf("=== Page %d (offset 0x%04x) ===\n", p, p * TKV_PAGE_SIZE);

        if (ph->magic != TKV_PAGE_MAGIC) {
            printf("  [no valid header]\n\n");
            continue;
        }
        printf("  magic=TKV1  status=0x%02x  seq=%u  erase_count=%u\n",
               ph->status, ph->sequence, ph->erase_count);

        int off = TKV_PAGE_HDR_SIZE;
        int ei  = 0;
        while (off + TKV_ENTRY_HDR_SIZE <= TKV_PAGE_SIZE) {
            tkv_entry_hdr_t *eh = (tkv_entry_hdr_t *)(page + off);
            if (eh->magic != TKV_ENTRY_MAGIC) break;
            if (eh->key_len == 0)             break;

            int total = TKV_ENTRY_HDR_SIZE + eh->key_len + eh->value_len;
            if (off + total > TKV_PAGE_SIZE) break;

            uint8_t *k = page + off + TKV_ENTRY_HDR_SIZE;
            uint8_t *v = k + eh->key_len;
            uint32_t cc = tkv_entry_crc(eh->key_len, eh->value_len,
                                        eh->key_hash, k, v);

            printf("  entry[%d] @%d: state=0x%02x  key_len=%u  value_len=%u  "
                   "hash=0x%08x  crc=%s  key=\"",
                   ei, off, eh->state, eh->key_len, eh->value_len,
                   eh->key_hash, (cc == eh->crc) ? "OK" : "BAD");
            fwrite(k, 1, eh->key_len, stdout);
            printf("\"\n");

            off += total;
            ei++;
        }
        printf("\n");
    }
    free(flash);
    return 0;
}

static int cmd_compact(const char *file) {
    size_t sz;
    uint8_t *flash = load_image(file, &sz);
    if (!flash) return 1;
    tkv_store_t st;
    tkv_open(&st, flash, (int)(sz / TKV_PAGE_SIZE));
    tkv_compact(&st);
    save_image(file, flash, sz);
    printf("Compacted %s\n", file);
    free(flash);
    return 0;
}

/* ---- main ---- */

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s <command> [args...]\n\n"
        "Commands:\n"
        "  init    <file> <num_pages>    Create and format a flash image\n"
        "  put     <file> <key> <value>  Store a key-value pair\n"
        "  get     <file> <key>          Retrieve a value\n"
        "  delete  <file> <key>          Remove a key\n"
        "  list    <file>                List all stored keys\n"
        "  dump    <file>                Show on-flash structure\n"
        "  compact <file>                Garbage-collect dead entries\n\n"
        "Each page is %d bytes.  Format identifier: TKV1.\n",
        prog, TKV_PAGE_SIZE);
}

int main(int argc, char **argv) {
    if (argc < 2) { usage(argv[0]); return 1; }
    const char *cmd = argv[1];

    if (strcmp(cmd, "init") == 0 && argc >= 4)
        return cmd_init(argv[2], atoi(argv[3]));
    if (strcmp(cmd, "put") == 0 && argc >= 5)
        return cmd_put(argv[2], argv[3], argv[4]);
    if (strcmp(cmd, "get") == 0 && argc >= 4)
        return cmd_get(argv[2], argv[3]);
    if (strcmp(cmd, "delete") == 0 && argc >= 4)
        return cmd_delete(argv[2], argv[3]);
    if (strcmp(cmd, "list") == 0 && argc >= 3)
        return cmd_list(argv[2]);
    if (strcmp(cmd, "dump") == 0 && argc >= 3)
        return cmd_dump(argv[2]);
    if (strcmp(cmd, "compact") == 0 && argc >= 3)
        return cmd_compact(argv[2]);
    if (strcmp(cmd, "--help") == 0 || strcmp(cmd, "-h") == 0)
        { usage(argv[0]); return 0; }

    fprintf(stderr, "Unknown command or missing arguments: %s\n", cmd);
    usage(argv[0]);
    return 1;
}
