/*
 *
 * Sparse matrix symbolic Cholesky analysis using CXSparse.
 * Loads Matrix Market files, runs cs_schol for natural and AMD orderings,
 * outputs structured data for downstream processing.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <cs.h>

/* Load a Matrix Market coordinate file into CXSparse CSC format.
 * Handles the %%MatrixMarket header that cs_load cannot parse.
 * Stores only the lower triangle (what cs_schol/cs_symperm expects).
 * Sets *out_nnz_lower to the number of stored entries. */
cs *load_mm(const char *filename, int *out_nnz_lower) {
    FILE *f = fopen(filename, "r");
    if (!f) { fprintf(stderr, "Cannot open %s\n", filename); exit(1); }

    char line[1024];

    /* Skip comment lines (starting with %) */
    while (fgets(line, sizeof(line), f)) {
        if (line[0] != '%') break;
    }

    /* Parse dimension line: rows cols nnz */
    int nrow, ncol, nnz;
    if (sscanf(line, "%d %d %d", &nrow, &ncol, &nnz) != 3) {
        fprintf(stderr, "Bad dimension line in %s\n", filename);
        exit(1);
    }
    *out_nnz_lower = nnz;

    /* Create triplet matrix — lower triangle only */
    cs *T = cs_spalloc(nrow, ncol, nnz, 1, 1);
    if (!T) { fprintf(stderr, "cs_spalloc failed\n"); exit(1); }

    int r, c;
    double v;
    while (fscanf(f, "%d %d %lf", &r, &c, &v) == 3) {
        cs_entry(T, r - 1, c - 1, v);
    }
    fclose(f);

    cs *A = cs_compress(T);
    cs_spfree(T);
    return A;
}

/* Compute elimination tree height from parent array.
 * In SuiteSparse 7.x, the cs_di variant uses int for indices. */
int etree_height(const int *parent, int n) {
    int max_d = 0;
    for (int i = 0; i < n; i++) {
        int d = 0;
        int j = i;
        while (parent[j] >= 0) {
            j = parent[j];
            d++;
            if (d > n) break;  /* safety */
        }
        if (d > max_d) max_d = d;
    }
    return max_d + 1;
}

/* Compute flop count from column pointers of L.
 * cp[j+1]-cp[j] = column count including diagonal.
 * subdiag count c_j = (cp[j+1]-cp[j]) - 1.
 * flops = sum of c_j * (c_j + 1). */
long long flop_count(const int *cp, int n) {
    long long f = 0;
    for (int j = 0; j < n; j++) {
        long long cj = (long long)(cp[j + 1] - cp[j]) - 1;
        if (cj > 0) f += cj * (cj + 1);
    }
    return f;
}

void analyze_matrix(const char *filepath) {
    int nnz_lower;
    cs *A = load_mm(filepath, &nnz_lower);
    int n = (int)A->n;

    /* Extract base name (strip path and .mtx extension) */
    const char *base = strrchr(filepath, '/');
    base = base ? base + 1 : filepath;
    char name[256];
    strncpy(name, base, sizeof(name) - 1);
    name[sizeof(name) - 1] = '\0';
    char *dot = strrchr(name, '.');
    if (dot) *dot = '\0';

    printf("BEGIN %s\n", name);
    printf("n %d\n", n);
    printf("nnz_lower %d\n", nnz_lower);

    /* --- Natural ordering (order=0) --- */
    css *S0 = cs_schol(0, A);
    if (!S0) { fprintf(stderr, "cs_schol(0) failed for %s\n", name); exit(1); }
    printf("nat_nnz %d\n", (int)S0->lnz);
    printf("nat_height %d\n", etree_height(S0->parent, n));
    printf("nat_flops %lld\n", flop_count(S0->cp, n));

    /* --- AMD ordering (order=1) --- */
    css *S1 = cs_schol(1, A);
    if (!S1) { fprintf(stderr, "cs_schol(1) failed for %s\n", name); exit(1); }
    printf("amd_nnz %d\n", (int)S1->lnz);
    printf("amd_height %d\n", etree_height(S1->parent, n));
    printf("amd_flops %lld\n", flop_count(S1->cp, n));

    /* Recover AMD permutation vector: ordering[new] = old
     * S1->pinv holds the inverse permutation: pinv[old] = new */
    int *amd_perm = (int *)malloc(n * sizeof(int));
    if (!amd_perm) { fprintf(stderr, "malloc failed\n"); exit(1); }
    for (int old_idx = 0; old_idx < n; old_idx++) {
        amd_perm[(int)S1->pinv[old_idx]] = old_idx;
    }
    printf("amd_perm");
    for (int i = 0; i < n; i++) {
        printf(" %d", amd_perm[i]);
    }
    printf("\n");
    free(amd_perm);

    printf("END\n");

    cs_sfree(S0);
    cs_sfree(S1);
    cs_spfree(A);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s matrix1.mtx [matrix2.mtx ...]\n", argv[0]);
        return 1;
    }
    for (int i = 1; i < argc; i++) {
        analyze_matrix(argv[i]);
    }
    return 0;
}
