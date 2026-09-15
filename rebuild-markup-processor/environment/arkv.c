/* arkv - Custom archive format tool */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>
#include <time.h>
#include <zlib.h>

/* ---- Constants ---- */
#define ARKV_VERSION  2
#define FLAG_CKSUM    0x01
#define FLAG_SCRAM    0x02
#define ETYPE_FILE    0
#define ETYPE_DIR     1
#define CKSUM_SEED    0x5A3C9E71UL

static const char MAGIC[4]  = {'A','R','K','V'};
static const char FOOTER[8] = {'A','R','K','V','_','E','N','D'};

/* ---- LE write helpers ---- */
static void w8(FILE *f, uint8_t v) { fputc(v, f); }
static void w16(FILE *f, uint16_t v) {
    fputc(v & 0xFF, f); fputc((v >> 8) & 0xFF, f);
}
static void w32(FILE *f, uint32_t v) {
    for (int i = 0; i < 4; i++) fputc((v >> (8*i)) & 0xFF, f);
}
static void w64(FILE *f, int64_t v) {
    uint64_t u = (uint64_t)v;
    for (int i = 0; i < 8; i++) fputc((u >> (8*i)) & 0xFF, f);
}

/* ---- LE read helpers ---- */
static int r8(FILE *f, uint8_t *v) {
    int c = fgetc(f); if (c == EOF) return -1;
    *v = (uint8_t)c; return 0;
}
static int r16(FILE *f, uint16_t *v) {
    uint8_t b[2]; if (fread(b,1,2,f) != 2) return -1;
    *v = b[0] | ((uint16_t)b[1] << 8); return 0;
}
static int r32(FILE *f, uint32_t *v) {
    uint8_t b[4]; if (fread(b,1,4,f) != 4) return -1;
    *v = b[0] | ((uint32_t)b[1]<<8) | ((uint32_t)b[2]<<16) | ((uint32_t)b[3]<<24);
    return 0;
}
static int r64(FILE *f, int64_t *v) {
    uint8_t b[8]; if (fread(b,1,8,f) != 8) return -1;
    uint64_t u = 0;
    for (int i = 7; i >= 0; i--) u = (u << 8) | b[i];
    *v = (int64_t)u; return 0;
}

/* ---- Checksum: CRC32 with custom seed ---- */
static uint32_t arkv_cksum(const uint8_t *data, uint32_t len) {
    if (data == NULL || len == 0)
        return (uint32_t)crc32(CKSUM_SEED, Z_NULL, 0);
    return (uint32_t)crc32(CKSUM_SEED, data, len);
}

/* ---- Scramble: XOR with key derived from path ---- */
static void arkv_scramble(uint8_t *data, uint32_t len, const char *key) {
    size_t kl = strlen(key);
    if (kl == 0) return;
    for (uint32_t i = 0; i < len; i++)
        data[i] ^= (uint8_t)(key[i % kl] ^ 0xA5);
}

/* ---- Header ---- */
typedef struct { uint8_t version; uint8_t flags; uint32_t count; } ArkHdr;

static int read_header(FILE *f, ArkHdr *h) {
    char m[4];
    if (fread(m,1,4,f) != 4 || memcmp(m, MAGIC, 4) != 0) {
        fprintf(stderr, "Error: not an ARKV archive\n"); return -1;
    }
    if (r8(f, &h->version) != 0) return -1;
    if (h->version != ARKV_VERSION) {
        fprintf(stderr, "Error: unsupported version %d\n", h->version); return -1;
    }
    if (r8(f, &h->flags) != 0 || r32(f, &h->count) != 0) return -1;
    return 0;
}

/* ---- Entry ---- */
typedef struct {
    char *path; uint8_t type; uint16_t mode;
    int64_t mtime; uint32_t size;
    uint8_t *data; uint32_t cksum;
} ArkEnt;

static int read_entry(FILE *f, ArkEnt *e, uint8_t flags) {
    uint16_t plen;
    if (r16(f, &plen) != 0) return -1;
    e->path = (char *)malloc(plen + 1);
    if (fread(e->path, 1, plen, f) != plen) { free(e->path); return -1; }
    e->path[plen] = '\0';

    if (r8(f, &e->type) != 0 || r16(f, &e->mode) != 0 ||
        r64(f, &e->mtime) != 0 || r32(f, &e->size) != 0) {
        free(e->path); return -1;
    }

    if (e->size > 0) {
        e->data = (uint8_t *)malloc(e->size);
        if (fread(e->data, 1, e->size, f) != e->size) {
            free(e->path); free(e->data); return -1;
        }
    } else {
        e->data = NULL;
    }

    if (flags & FLAG_CKSUM) {
        if (r32(f, &e->cksum) != 0) {
            free(e->path); free(e->data); return -1;
        }
    }
    return 0;
}

static void free_entry(ArkEnt *e) { free(e->path); free(e->data); }

/* ==== CREATE ==== */
static int cmd_create(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: arkv create <archive> <files...>\n");
        return 1;
    }
    const char *arcpath = argv[0];
    int nfiles = argc - 1;
    char **files = argv + 1;

    uint8_t flags = 0;
    const char *env;
    env = getenv("ARKV_CHECKSUM");
    if (env && strcmp(env, "1") == 0) flags |= FLAG_CKSUM;
    env = getenv("ARKV_SCRAMBLE");
    if (env && strcmp(env, "1") == 0) flags |= FLAG_SCRAM;

    FILE *out = fopen(arcpath, "wb");
    if (!out) {
        fprintf(stderr, "Error: cannot create '%s': %s\n", arcpath, strerror(errno));
        return 1;
    }

    fwrite(MAGIC, 1, 4, out);
    w8(out, ARKV_VERSION);
    w8(out, flags);
    w32(out, (uint32_t)nfiles);

    for (int i = 0; i < nfiles; i++) {
        struct stat st;
        if (stat(files[i], &st) != 0) {
            fprintf(stderr, "Error: cannot stat '%s': %s\n", files[i], strerror(errno));
            fclose(out); return 1;
        }
        uint16_t pathlen = (uint16_t)strlen(files[i]);
        w16(out, pathlen);
        fwrite(files[i], 1, pathlen, out);

        uint8_t etype = S_ISDIR(st.st_mode) ? ETYPE_DIR : ETYPE_FILE;
        w8(out, etype);
        w16(out, (uint16_t)(st.st_mode & 0xFFFF));
        w64(out, (int64_t)st.st_mtime);

        if (etype == ETYPE_FILE) {
            FILE *inf = fopen(files[i], "rb");
            if (!inf) {
                fprintf(stderr, "Error: cannot read '%s': %s\n", files[i], strerror(errno));
                fclose(out); return 1;
            }
            fseek(inf, 0, SEEK_END);
            long fsize = ftell(inf);
            fseek(inf, 0, SEEK_SET);

            uint8_t *data = NULL;
            if (fsize > 0) {
                data = (uint8_t *)malloc(fsize);
                fread(data, 1, fsize, inf);
            }
            fclose(inf);

            uint32_t cksum = arkv_cksum(data, (uint32_t)fsize);
            if (flags & FLAG_SCRAM) arkv_scramble(data, (uint32_t)fsize, files[i]);

            w32(out, (uint32_t)fsize);
            if (fsize > 0 && data) fwrite(data, 1, fsize, out);
            if (flags & FLAG_CKSUM) w32(out, cksum);
            free(data);
        } else {
            w32(out, 0);
            if (flags & FLAG_CKSUM) w32(out, arkv_cksum(NULL, 0));
        }
    }

    fwrite(FOOTER, 1, 8, out);
    fclose(out);

    printf("Created '%s': %d entries", arcpath, nfiles);
    if (flags & FLAG_CKSUM) printf(" [checksum]");
    if (flags & FLAG_SCRAM) printf(" [scrambled]");
    printf("\n");
    return 0;
}

/* ==== LIST ==== */
static int cmd_list(int argc, char **argv) {
    if (argc < 1) {
        fprintf(stderr, "Usage: arkv list <archive>\n"); return 1;
    }
    FILE *f = fopen(argv[0], "rb");
    if (!f) {
        fprintf(stderr, "Error: cannot open '%s': %s\n", argv[0], strerror(errno));
        return 1;
    }
    ArkHdr hdr;
    if (read_header(f, &hdr) != 0) { fclose(f); return 1; }

    for (uint32_t i = 0; i < hdr.count; i++) {
        ArkEnt e;
        if (read_entry(f, &e, hdr.flags) != 0) {
            fprintf(stderr, "Error: corrupt entry %u\n", i);
            fclose(f); return 1;
        }
        char ts[20];
        time_t mt = (time_t)e.mtime;
        struct tm *tm = gmtime(&mt);
        strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%S", tm);

        printf("%c %04o %10u %s %s\n",
               e.type == ETYPE_DIR ? 'd' : 'f',
               e.mode & 07777, e.size, ts, e.path);
        free_entry(&e);
    }
    fclose(f);
    return 0;
}

/* ==== EXTRACT ==== */
static void mkdirs(const char *path) {
    char *tmp = strdup(path);
    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            mkdir(tmp, 0755);
            *p = '/';
        }
    }
    free(tmp);
}

static int cmd_extract(int argc, char **argv) {
    if (argc < 1) {
        fprintf(stderr, "Usage: arkv extract <archive> [dir]\n"); return 1;
    }
    const char *target = argc >= 2 ? argv[1] : ".";

    FILE *f = fopen(argv[0], "rb");
    if (!f) {
        fprintf(stderr, "Error: cannot open '%s': %s\n", argv[0], strerror(errno));
        return 1;
    }
    ArkHdr hdr;
    if (read_header(f, &hdr) != 0) { fclose(f); return 1; }

    if (strcmp(target, ".") != 0) {
        if (mkdir(target, 0755) != 0 && errno != EEXIST) {
            fprintf(stderr, "Error: cannot create '%s': %s\n", target, strerror(errno));
            fclose(f); return 1;
        }
    }

    for (uint32_t i = 0; i < hdr.count; i++) {
        ArkEnt e;
        if (read_entry(f, &e, hdr.flags) != 0) {
            fprintf(stderr, "Error: corrupt entry %u\n", i);
            fclose(f); return 1;
        }

        if ((hdr.flags & FLAG_SCRAM) && e.data && e.size > 0)
            arkv_scramble(e.data, e.size, e.path);

        if (hdr.flags & FLAG_CKSUM) {
            uint32_t computed = arkv_cksum(e.data, e.size);
            if (computed != e.cksum)
                fprintf(stderr, "Warning: checksum mismatch for '%s'\n", e.path);
        }

        char outpath[4096];
        snprintf(outpath, sizeof(outpath), "%s/%s", target, e.path);

        if (e.type == ETYPE_DIR) {
            mkdir(outpath, e.mode & 07777);
        } else {
            mkdirs(outpath);
            FILE *of = fopen(outpath, "wb");
            if (!of) {
                fprintf(stderr, "Error: cannot write '%s': %s\n", outpath, strerror(errno));
                free_entry(&e); fclose(f); return 1;
            }
            if (e.size > 0 && e.data) fwrite(e.data, 1, e.size, of);
            fclose(of);
            chmod(outpath, e.mode & 07777);
        }

        printf("  %s\n", e.path);
        free_entry(&e);
    }
    printf("Extracted %u entries to '%s'\n", hdr.count, target);
    fclose(f);
    return 0;
}

/* ==== INFO (hidden command) ==== */
static int cmd_info(int argc, char **argv) {
    if (argc < 1) {
        fprintf(stderr, "Usage: arkv info <archive>\n"); return 1;
    }
    FILE *f = fopen(argv[0], "rb");
    if (!f) {
        fprintf(stderr, "Error: cannot open '%s': %s\n", argv[0], strerror(errno));
        return 1;
    }
    ArkHdr hdr;
    if (read_header(f, &hdr) != 0) { fclose(f); return 1; }

    printf("Archive: %s\n", argv[0]);
    printf("Version: %d\n", hdr.version);
    printf("Flags: 0x%02x", hdr.flags);
    if (hdr.flags & FLAG_CKSUM) printf(" checksum");
    if (hdr.flags & FLAG_SCRAM) printf(" scramble");
    printf("\n");
    printf("Entries: %u\n", hdr.count);

    for (uint32_t i = 0; i < hdr.count; i++) {
        ArkEnt e;
        if (read_entry(f, &e, hdr.flags) != 0) {
            fprintf(stderr, "Error: corrupt entry %u\n", i);
            fclose(f); return 1;
        }
        printf("  [%u] %s (%s, %u bytes, mode %04o)\n",
               i, e.path,
               e.type == ETYPE_DIR ? "dir" : "file",
               e.size, e.mode & 07777);
        free_entry(&e);
    }
    fclose(f);
    return 0;
}

/* ==== VERIFY (hidden command) ==== */
static int cmd_verify(int argc, char **argv) {
    if (argc < 1) {
        fprintf(stderr, "Usage: arkv verify <archive>\n"); return 1;
    }
    FILE *f = fopen(argv[0], "rb");
    if (!f) {
        fprintf(stderr, "Error: cannot open '%s': %s\n", argv[0], strerror(errno));
        return 1;
    }
    ArkHdr hdr;
    if (read_header(f, &hdr) != 0) { fclose(f); return 1; }

    if (!(hdr.flags & FLAG_CKSUM)) {
        printf("Archive has no checksums\n");
        fclose(f); return 0;
    }

    int ok = 1;
    for (uint32_t i = 0; i < hdr.count; i++) {
        ArkEnt e;
        if (read_entry(f, &e, hdr.flags) != 0) {
            fprintf(stderr, "Error: corrupt entry %u\n", i);
            fclose(f); return 1;
        }

        uint8_t *plain = NULL;
        if (e.data && e.size > 0) {
            plain = (uint8_t *)malloc(e.size);
            memcpy(plain, e.data, e.size);
            if (hdr.flags & FLAG_SCRAM) arkv_scramble(plain, e.size, e.path);
        }

        uint32_t computed = arkv_cksum(plain, e.size);
        if (computed == e.cksum) {
            printf("%s: OK\n", e.path);
        } else {
            printf("%s: FAIL (expected 0x%08x, got 0x%08x)\n",
                   e.path, e.cksum, computed);
            ok = 0;
        }
        free(plain);
        free_entry(&e);
    }
    fclose(f);
    return ok ? 0 : 1;
}

/* ==== DUMP (hidden command) ==== */
static int cmd_dump(int argc, char **argv) {
    if (argc < 1) {
        fprintf(stderr, "Usage: arkv dump <archive>\n"); return 1;
    }
    FILE *f = fopen(argv[0], "rb");
    if (!f) {
        fprintf(stderr, "Error: cannot open '%s': %s\n", argv[0], strerror(errno));
        return 1;
    }
    ArkHdr hdr;
    if (read_header(f, &hdr) != 0) { fclose(f); return 1; }

    printf("HEADER: magic=ARKV version=%d flags=0x%02x entries=%u\n",
           hdr.version, hdr.flags, hdr.count);

    for (uint32_t i = 0; i < hdr.count; i++) {
        ArkEnt e;
        if (read_entry(f, &e, hdr.flags) != 0) {
            fprintf(stderr, "Error: corrupt entry %u\n", i);
            fclose(f); return 1;
        }
        printf("ENTRY[%u]: path=\"%s\" type=%s mode=%04o mtime=%lld size=%u",
               i, e.path,
               e.type == ETYPE_DIR ? "dir" : "file",
               e.mode & 07777,
               (long long)e.mtime, e.size);
        if (hdr.flags & FLAG_CKSUM)
            printf(" cksum=0x%08x", e.cksum);
        printf("\n");
        free_entry(&e);
    }

    char ftr[8];
    if (fread(ftr, 1, 8, f) == 8 && memcmp(ftr, FOOTER, 8) == 0)
        printf("FOOTER: ARKV_END\n");
    else
        printf("FOOTER: <missing or corrupt>\n");

    fclose(f);
    return 0;
}

/* ==== HELP ==== */
static void show_help(void) {
    printf("Usage: arkv <command> [args...]\n\n"
           "Commands:\n"
           "  create <archive> <files...>  Create a new archive\n"
           "  list <archive>              List archive contents\n"
           "  extract <archive> [dir]     Extract archive contents\n"
           "\nOptions:\n"
           "  --help     Show this message\n"
           "  --version  Show version\n");
}

/* ==== MAIN ==== */
int main(int argc, char **argv) {
    if (argc < 2) { show_help(); return 1; }

    if (strcmp(argv[1], "--help") == 0)    { show_help(); return 0; }
    if (strcmp(argv[1], "--version") == 0) { printf("arkv 2.1.0\n"); return 0; }

    if (strcmp(argv[1], "create") == 0)  return cmd_create(argc - 2, argv + 2);
    if (strcmp(argv[1], "list") == 0)    return cmd_list(argc - 2, argv + 2);
    if (strcmp(argv[1], "extract") == 0) return cmd_extract(argc - 2, argv + 2);
    if (strcmp(argv[1], "info") == 0)    return cmd_info(argc - 2, argv + 2);
    if (strcmp(argv[1], "verify") == 0)  return cmd_verify(argc - 2, argv + 2);
    if (strcmp(argv[1], "dump") == 0)    return cmd_dump(argc - 2, argv + 2);

    fprintf(stderr, "Error: unknown command '%s'\n", argv[1]);
    return 1;
}
