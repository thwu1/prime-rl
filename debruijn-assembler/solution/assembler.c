
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define MAX_K 64

static int K;
static int KMER_BYTES;

/* 2-bit DNA encoding: A=0, C=1, G=2, T=3 */
static void encode_kmer(const char *seq, uint8_t *out) {
    static const uint8_t enc[256] = {
        ['A'] = 0, ['a'] = 0,
        ['C'] = 1, ['c'] = 1,
        ['G'] = 2, ['g'] = 2,
        ['T'] = 3, ['t'] = 3
    };
    memset(out, 0, KMER_BYTES);
    for (int i = 0; i < K; i++)
        out[i >> 2] |= enc[(unsigned char)seq[i]] << ((3 - (i & 3)) << 1);
}

static void decode_kmer(const uint8_t *enc_data, char *out) {
    for (int i = 0; i < K; i++)
        out[i] = "ACGT"[(enc_data[i >> 2] >> ((3 - (i & 3)) << 1)) & 3];
    out[K] = '\0';
}

/* FNV-1a 64-bit hash */
static uint64_t hash_kmer(const uint8_t *data, int len) {
    uint64_t h = 14695981039346656037ULL;
    for (int i = 0; i < len; i++) {
        h ^= data[i];
        h *= 1099511628211ULL;
    }
    return h;
}

/* Open-addressing hash table with flat parallel arrays */
static unsigned ht_cap;
static uint8_t *ht_keys;   /* cap * KMER_BYTES */
static char *ht_fwd;       /* cap */
static char *ht_bwd;       /* cap */
static uint8_t *ht_occ;    /* cap */

static void ht_init(int n) {
    ht_cap = 1;
    while (ht_cap < (unsigned)n * 2)
        ht_cap <<= 1;
    ht_keys = calloc(ht_cap, KMER_BYTES);
    ht_fwd = calloc(ht_cap, 1);
    ht_bwd = calloc(ht_cap, 1);
    ht_occ = calloc(ht_cap, 1);
    if (!ht_keys || !ht_fwd || !ht_bwd || !ht_occ) {
        fprintf(stderr, "Failed to allocate hash table\n");
        exit(1);
    }
}

static void ht_insert(const uint8_t *k, char f, char b) {
    unsigned mask = ht_cap - 1;
    unsigned idx = (unsigned)(hash_kmer(k, KMER_BYTES) & mask);
    while (ht_occ[idx])
        idx = (idx + 1) & mask;
    memcpy(ht_keys + (size_t)idx * KMER_BYTES, k, KMER_BYTES);
    ht_fwd[idx] = f;
    ht_bwd[idx] = b;
    ht_occ[idx] = 1;
}

static int ht_find(const uint8_t *k) {
    unsigned mask = ht_cap - 1;
    unsigned idx = (unsigned)(hash_kmer(k, KMER_BYTES) & mask);
    while (ht_occ[idx]) {
        if (memcmp(ht_keys + (size_t)idx * KMER_BYTES, k, KMER_BYTES) == 0)
            return (int)idx;
        idx = (idx + 1) & mask;
    }
    return -1;
}

/* Shift k-mer left by 1 base and append extension character */
static void advance_kmer(const uint8_t *cur, char ext, uint8_t *nxt) {
    char buf[MAX_K + 1];
    decode_kmer(cur, buf);
    memmove(buf, buf + 1, K - 1);
    buf[K - 1] = ext;
    encode_kmer(buf, nxt);
}

/* Dynamic contig list */
static char **contigs;
static int n_contigs, contigs_cap;

static void push_contig(const char *s) {
    if (n_contigs >= contigs_cap) {
        contigs_cap = contigs_cap ? contigs_cap * 2 : 256;
        contigs = realloc(contigs, contigs_cap * sizeof(char *));
    }
    contigs[n_contigs++] = strdup(s);
}

static int cmpstr(const void *a, const void *b) {
    return strcmp(*(const char **)a, *(const char **)b);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <kmers_file>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "r");
    if (!f) {
        perror(argv[1]);
        return 1;
    }

    int n;
    if (fscanf(f, "%d %d", &K, &n) != 2) {
        fprintf(stderr, "Invalid header\n");
        return 1;
    }
    KMER_BYTES = (K + 3) / 4;

    ht_init(n);

    /* Start nodes: dynamically sized */
    int st_cap = 256, n_starts = 0;
    uint8_t *st_keys = malloc((size_t)st_cap * KMER_BYTES);
    char *st_fwd = malloc(st_cap);

    char kbuf[MAX_K + 1];
    char fc, bc;
    uint8_t enc[MAX_K / 4 + 2];

    for (int i = 0; i < n; i++) {
        if (fscanf(f, " %s %c %c", kbuf, &fc, &bc) != 3) {
            fprintf(stderr, "Parse error at k-mer %d\n", i);
            return 1;
        }
        encode_kmer(kbuf, enc);
        ht_insert(enc, fc, bc);

        if (bc == 'F') {
            if (n_starts >= st_cap) {
                st_cap *= 2;
                st_keys = realloc(st_keys, (size_t)st_cap * KMER_BYTES);
                st_fwd = realloc(st_fwd, st_cap);
            }
            memcpy(st_keys + (size_t)n_starts * KMER_BYTES, enc, KMER_BYTES);
            st_fwd[n_starts] = fc;
            n_starts++;
        }
    }
    fclose(f);

    /* Traverse de Bruijn graph */
    int cbuf_cap = 4096;
    char *cbuf = malloc(cbuf_cap);
    uint8_t cur[MAX_K / 4 + 2], nxt[MAX_K / 4 + 2];

    for (int i = 0; i < n_starts; i++) {
        memcpy(cur, st_keys + (size_t)i * KMER_BYTES, KMER_BYTES);
        decode_kmer(cur, cbuf);
        int len = K;
        char fext = st_fwd[i];

        while (fext != 'F') {
            if (len + 2 >= cbuf_cap) {
                cbuf_cap *= 2;
                cbuf = realloc(cbuf, cbuf_cap);
            }
            cbuf[len++] = fext;
            advance_kmer(cur, fext, nxt);
            memcpy(cur, nxt, KMER_BYTES);
            int idx = ht_find(cur);
            if (idx < 0) break;
            fext = ht_fwd[idx];
        }
        cbuf[len] = '\0';
        push_contig(cbuf);
    }

    /* Sort and output */
    qsort(contigs, n_contigs, sizeof(char *), cmpstr);
    for (int i = 0; i < n_contigs; i++)
        puts(contigs[i]);

    /* Cleanup */
    free(ht_keys); free(ht_fwd); free(ht_bwd); free(ht_occ);
    free(st_keys); free(st_fwd); free(cbuf);
    for (int i = 0; i < n_contigs; i++) free(contigs[i]);
    free(contigs);

    return 0;
}
