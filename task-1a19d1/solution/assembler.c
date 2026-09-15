/*
 * De Bruijn graph genome assembler.
 * Reads a k-mer file, builds a hash table, traverses from start nodes
 * (backward extension == 'F'), and outputs sorted contigs.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sys/stat.h>

#define MAX_K 64
#define HT_BITS 21
#define HT_SIZE (1 << HT_BITS)
#define HT_MASK (HT_SIZE - 1)
#define MAX_CONTIG_LEN (1024 * 1024)

static int K;

/* ---------- hash table with separate chaining ---------- */

typedef struct Entry {
    char kmer[MAX_K];
    char fwd;
    char bwd;
    struct Entry *next;
} Entry;

static Entry *ht[HT_SIZE];

static uint32_t hash_kmer(const char *s) {
    /* djb2 variant */
    uint32_t h = 5381;
    for (int i = 0; i < K; i++)
        h = ((h << 5) + h) ^ (uint32_t)(unsigned char)s[i];
    return h & HT_MASK;
}

static void ht_insert(const char *kmer, char fwd, char bwd) {
    uint32_t h = hash_kmer(kmer);
    Entry *e = (Entry *)malloc(sizeof(Entry));
    if (!e) { fprintf(stderr, "OOM\n"); exit(1); }
    memcpy(e->kmer, kmer, K);
    e->kmer[K] = '\0';
    e->fwd = fwd;
    e->bwd = bwd;
    e->next = ht[h];
    ht[h] = e;
}

static Entry *ht_lookup(const char *kmer) {
    uint32_t h = hash_kmer(kmer);
    Entry *e = ht[h];
    while (e) {
        if (memcmp(e->kmer, kmer, K) == 0) return e;
        e = e->next;
    }
    return NULL;
}

/* ---------- dynamic arrays ---------- */

static char **start_kmers;
static int n_starts, starts_cap;

static void add_start(const char *kmer) {
    if (n_starts >= starts_cap) {
        starts_cap = starts_cap ? starts_cap * 2 : 2048;
        start_kmers = (char **)realloc(start_kmers, (size_t)starts_cap * sizeof(char *));
    }
    start_kmers[n_starts] = (char *)malloc(K + 1);
    memcpy(start_kmers[n_starts], kmer, K);
    start_kmers[n_starts][K] = '\0';
    n_starts++;
}

typedef struct { char *data; int len; } Contig;

static Contig *contigs;
static int n_contigs, contigs_cap;

static void add_contig(const char *data, int len) {
    if (n_contigs >= contigs_cap) {
        contigs_cap = contigs_cap ? contigs_cap * 2 : 2048;
        contigs = (Contig *)realloc(contigs, (size_t)contigs_cap * sizeof(Contig));
    }
    contigs[n_contigs].data = (char *)malloc(len + 1);
    memcpy(contigs[n_contigs].data, data, len);
    contigs[n_contigs].data[len] = '\0';
    contigs[n_contigs].len = len;
    n_contigs++;
}

static int contig_cmp(const void *a, const void *b) {
    return strcmp(((const Contig *)a)->data, ((const Contig *)b)->data);
}

/* ---------- main ---------- */

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <kmers.txt>\n", argv[0]);
        return 1;
    }

    FILE *fin = fopen(argv[1], "r");
    if (!fin) { fprintf(stderr, "Cannot open %s\n", argv[1]); return 1; }

    /* read k */
    char line[256];
    if (!fgets(line, sizeof(line), fin)) { fclose(fin); return 1; }
    K = atoi(line);
    if (K <= 0 || K >= MAX_K) {
        fprintf(stderr, "Invalid K=%d\n", K);
        return 1;
    }

    /* read k-mers */
    char kmer_buf[MAX_K], fwd_buf[4], bwd_buf[4];
    int n_loaded = 0;
    while (fscanf(fin, "%s %s %s", kmer_buf, fwd_buf, bwd_buf) == 3) {
        ht_insert(kmer_buf, fwd_buf[0], bwd_buf[0]);
        if (bwd_buf[0] == 'F') {
            add_start(kmer_buf);
        }
        n_loaded++;
    }
    fclose(fin);
    fprintf(stderr, "Loaded %d k-mers, %d start nodes (K=%d)\n",
            n_loaded, n_starts, K);

    /* traverse from each start node */
    char *buf = (char *)malloc(MAX_CONTIG_LEN);
    if (!buf) { fprintf(stderr, "OOM\n"); return 1; }

    for (int i = 0; i < n_starts; i++) {
        memcpy(buf, start_kmers[i], K);
        int len = K;

        Entry *e = ht_lookup(start_kmers[i]);
        char cur_fwd = e ? e->fwd : 'F';

        while (cur_fwd != 'F') {
            if (len >= MAX_CONTIG_LEN - 1) break;  /* safety */
            buf[len++] = cur_fwd;

            /* look up the last K bases as the next k-mer */
            e = ht_lookup(buf + len - K);
            if (!e) break;
            cur_fwd = e->fwd;
        }

        add_contig(buf, len);
    }
    free(buf);

    fprintf(stderr, "Assembled %d contigs\n", n_contigs);

    /* sort lexicographically */
    qsort(contigs, (size_t)n_contigs, sizeof(Contig), contig_cmp);

    /* write output */
    mkdir("/app/output", 0755);
    FILE *fout = fopen("/app/output/contigs.txt", "w");
    if (!fout) { fprintf(stderr, "Cannot open output\n"); return 1; }

    for (int i = 0; i < n_contigs; i++) {
        fputs(contigs[i].data, fout);
        fputc('\n', fout);
    }
    fclose(fout);

    /* cleanup */
    for (int i = 0; i < n_starts; i++) free(start_kmers[i]);
    free(start_kmers);
    for (int i = 0; i < n_contigs; i++) free(contigs[i].data);
    free(contigs);
    for (int i = 0; i < HT_SIZE; i++) {
        Entry *e = ht[i];
        while (e) { Entry *next = e->next; free(e); e = next; }
    }

    return 0;
}
