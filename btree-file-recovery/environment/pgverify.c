/*
 * pgverify.c - B+Tree Database Structural Verifier
 *
 * Validates a BYODB_TBENCH_V1 database file for full structural
 * integrity: meta-page CRC, B+tree invariants (key ordering,
 * balanced depth, separator-key consistency, pointer validity),
 * and page reachability.
 *
 * Usage:  pgverify <database.db>
 * Exit:   0 = valid,  1 = integrity error,  2 = usage / IO error
 * Stdout: "PASS pages=<N> kvs=<M>" or "FAIL <reason>"
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdarg.h>

#define PGSZ 4096u
#define TY_INT  1
#define TY_LEAF 2

static const uint8_t MAGIC[16] = {
    'B','Y','O','D','B','_','T','B','E','N','C','H','_','V','1','\0'
};

/* ---- CRC-32 (zlib / ISO 3309, polynomial 0xEDB88320) ---- */

static uint32_t ctab[256];

static void crc_init(void) {
    for (unsigned i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int j = 0; j < 8; j++)
            c = (c & 1) ? ((c >> 1) ^ 0xEDB88320u) : (c >> 1);
        ctab[i] = c;
    }
}

static uint32_t crc32(const uint8_t *p, size_t n) {
    uint32_t c = ~(uint32_t)0;
    for (size_t i = 0; i < n; i++)
        c = (c >> 8) ^ ctab[(c ^ p[i]) & 0xFF];
    return ~c;
}

/* ---- little-endian readers ---- */

static inline uint16_t r16(const uint8_t *p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}
static inline uint32_t r32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static inline uint64_t r64(const uint8_t *p) {
    return (uint64_t)r32(p) | ((uint64_t)r32(p + 4) << 32);
}

/* ---- globals ---- */

static uint8_t *G;           /* file buffer                    */
static uint64_t Gpg;         /* total pages in file            */
static int     *Gvis;        /* per-page visited flag          */
static int      Gkv;         /* accumulated leaf KV count      */
static char     Emsg[512];   /* first error message            */

static void efmt(const char *fmt, ...) {
    if (Emsg[0]) return;          /* keep only the first error */
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(Emsg, sizeof Emsg, fmt, ap);
    va_end(ap);
}

/* key accessor: pointer to key bytes; length written to *kl */
static const uint8_t *nkey(const uint8_t *pg, uint16_t nk, int i,
                           uint16_t *kl) {
    uint16_t ob   = 4 + nk * 8;
    uint16_t prev = (i == 0) ? 0 : r16(pg + ob + (i - 1) * 2);
    const uint8_t *e = pg + (4 + nk * 10) + prev;
    *kl = r16(e);
    return e + 4;
}

static int kcmp(const uint8_t *a, uint16_t al,
                const uint8_t *b, uint16_t bl) {
    int n = al < bl ? al : bl;
    int c = memcmp(a, b, n);
    return c ? c : (int)al - (int)bl;
}

/*
 * Recursive DFS traversal.
 * Returns leaf depth (from root = 0) or -1 on error.
 * Writes the subtree's smallest key pointer/length into *fk / *fl.
 */
static int walk(uint64_t pn, int dep,
                const uint8_t **fk, uint16_t *fl) {
    if (Emsg[0]) return -1;

    if (pn < 1 || pn >= Gpg) {
        efmt("ptr %lu out of range [1,%lu)",
             (unsigned long)pn, (unsigned long)Gpg);
        return -1;
    }
    if (Gvis[pn]) {
        efmt("page %lu visited twice (cycle)", (unsigned long)pn);
        return -1;
    }
    Gvis[pn] = 1;

    const uint8_t *pg = G + pn * PGSZ;
    uint16_t nt = r16(pg);
    uint16_t nk = r16(pg + 2);

    /* type & nkeys sanity */
    if (nt != TY_INT && nt != TY_LEAF) {
        efmt("page %lu: bad node type %u", (unsigned long)pn, nt);
        return -1;
    }
    if (nk == 0) {
        efmt("page %lu: nkeys=0", (unsigned long)pn);
        return -1;
    }
    if (4u + (uint32_t)nk * 10 > PGSZ) {
        efmt("page %lu: nkeys=%u overflows page", (unsigned long)pn, nk);
        return -1;
    }

    /* validate cumulative offsets and KV bounds */
    uint16_t ob  = 4 + nk * 8;
    uint16_t kva = 4 + nk * 10;
    uint16_t prev = 0;
    for (int i = 0; i < nk; i++) {
        uint16_t cum = r16(pg + ob + i * 2);
        if (i > 0 && cum <= prev) {
            efmt("page %lu: offset[%d] not increasing", (unsigned long)pn, i);
            return -1;
        }
        uint16_t s = kva + prev;
        if (s + 4 > PGSZ) {
            efmt("page %lu: kv%d header OOB", (unsigned long)pn, i);
            return -1;
        }
        uint16_t kl = r16(pg + s);
        uint16_t vl = r16(pg + s + 2);
        if (s + 4 + kl + vl > PGSZ) {
            efmt("page %lu: kv%d data OOB", (unsigned long)pn, i);
            return -1;
        }
        if ((uint16_t)(4 + kl + vl) != cum - prev) {
            efmt("page %lu: kv%d size mismatch", (unsigned long)pn, i);
            return -1;
        }
        prev = cum;
    }

    /* key sort order: strictly ascending */
    for (int i = 1; i < nk; i++) {
        uint16_t al, bl;
        const uint8_t *a = nkey(pg, nk, i - 1, &al);
        const uint8_t *b = nkey(pg, nk, i, &bl);
        if (kcmp(a, al, b, bl) >= 0) {
            efmt("page %lu: keys not ascending at index %d",
                 (unsigned long)pn, i);
            return -1;
        }
    }

    /* set output: first key of this subtree */
    *fk = nkey(pg, nk, 0, fl);

    if (nt == TY_LEAF) {
        /* leaf: pointer slots must all be zero */
        for (int i = 0; i < nk; i++) {
            if (r64(pg + 4 + i * 8) != 0) {
                efmt("page %lu: leaf ptr[%d] nonzero", (unsigned long)pn, i);
                return -1;
            }
        }
        Gkv += nk;
        return dep;
    }

    /* internal node: recurse into children */
    int ld = -1;
    for (int i = 0; i < nk; i++) {
        uint64_t ch = r64(pg + 4 + i * 8);
        const uint8_t *cfk;
        uint16_t cfl;
        int cd = walk(ch, dep + 1, &cfk, &cfl);
        if (cd < 0) return -1;

        /* balanced depth */
        if (ld < 0)
            ld = cd;
        else if (cd != ld) {
            efmt("page %lu: depth mismatch child %d (%d vs %d)",
                 (unsigned long)pn, i, cd, ld);
            return -1;
        }

        /* separator key must equal the child subtree's first key */
        uint16_t skl;
        const uint8_t *sk = nkey(pg, nk, i, &skl);
        if (kcmp(sk, skl, cfk, cfl) != 0) {
            efmt("page %lu: separator[%d] != child first key",
                 (unsigned long)pn, i);
            return -1;
        }
    }
    return ld;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <database.db>\n", argv[0]);
        return 2;
    }
    crc_init();

    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 2; }
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    rewind(f);

    if (sz <= 0 || sz % PGSZ != 0) {
        printf("FAIL file size %ld not page-aligned\n", sz);
        fclose(f);
        return 1;
    }

    G = malloc((size_t)sz);
    if (!G || fread(G, 1, (size_t)sz, f) != (size_t)sz) {
        fclose(f);
        return 2;
    }
    fclose(f);
    Gpg = (uint64_t)sz / PGSZ;

    /* ---- meta page ---- */
    if (memcmp(G, MAGIC, 16) != 0) {
        printf("FAIL bad magic\n");
        free(G);
        return 1;
    }
    uint64_t rp = r64(G + 16);
    uint64_t np = r64(G + 24);
    uint32_t sc = r32(G + 32);
    uint32_t cc = crc32(G, 32);

    if (sc != cc) {
        printf("FAIL meta CRC stored=0x%08X computed=0x%08X\n", sc, cc);
        free(G);
        return 1;
    }
    if (np != Gpg) {
        printf("FAIL num_pages=%lu file_pages=%lu\n",
               (unsigned long)np, (unsigned long)Gpg);
        free(G);
        return 1;
    }

    /* ---- tree walk ---- */
    Gvis = calloc((size_t)Gpg, sizeof *Gvis);
    if (!Gvis) { free(G); return 2; }
    Gvis[0] = 1;   /* meta page counts as visited */

    const uint8_t *fk;
    uint16_t fl;
    walk(rp, 0, &fk, &fl);

    if (Emsg[0]) {
        printf("FAIL %s\n", Emsg);
        free(Gvis);
        free(G);
        return 1;
    }

    /* ---- orphan check ---- */
    for (uint64_t i = 0; i < Gpg; i++) {
        if (!Gvis[i]) {
            printf("FAIL orphan page %lu\n", (unsigned long)i);
            free(Gvis);
            free(G);
            return 1;
        }
    }

    printf("PASS pages=%lu kvs=%d\n", (unsigned long)Gpg, Gkv);
    free(Gvis);
    free(G);
    return 0;
}
