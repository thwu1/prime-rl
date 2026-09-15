 *
 * codesearch_solution.c — Complete suffix-array-based code search.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <sys/stat.h>

#define MAX_FILES 1024
#define MAX_RESULTS 100000

typedef struct {
    char *text;
    int *sa;
    int n;
    int nfiles;
    char filenames[MAX_FILES][256];
    int file_starts[MAX_FILES];
    int file_ends[MAX_FILES];
} Index;

typedef struct {
    int file_id;
    int line;
    int pos;
} Result;

/* ======== Corpus Loading ======== */

int load_corpus(Index *idx, const char *dir_path) {
    DIR *dir = opendir(dir_path);
    if (!dir) { perror("opendir"); return -1; }

    struct dirent *ent;
    idx->nfiles = 0;
    while ((ent = readdir(dir)) != NULL) {
        if (ent->d_name[0] == '.') continue;
        char path[512];
        snprintf(path, sizeof(path), "%s/%s", dir_path, ent->d_name);
        struct stat st;
        if (stat(path, &st) == 0 && S_ISREG(st.st_mode)) {
            strncpy(idx->filenames[idx->nfiles], ent->d_name, 255);
            idx->filenames[idx->nfiles][255] = '\0';
            idx->nfiles++;
            if (idx->nfiles >= MAX_FILES) break;
        }
    }
    closedir(dir);

    for (int i = 0; i < idx->nfiles - 1; i++)
        for (int j = i + 1; j < idx->nfiles; j++)
            if (strcmp(idx->filenames[i], idx->filenames[j]) > 0) {
                char tmp[256];
                strcpy(tmp, idx->filenames[i]);
                strcpy(idx->filenames[i], idx->filenames[j]);
                strcpy(idx->filenames[j], tmp);
            }

    int total = 0;
    for (int i = 0; i < idx->nfiles; i++) {
        char path[512];
        snprintf(path, sizeof(path), "%s/%s", dir_path, idx->filenames[i]);
        struct stat st;
        stat(path, &st);
        total += (int)st.st_size;
    }
    total += idx->nfiles;

    idx->text = calloc(total, 1);
    idx->sa = calloc(total, sizeof(int));
    idx->n = total;

    int offset = 0;
    for (int i = 0; i < idx->nfiles; i++) {
        char path[512];
        snprintf(path, sizeof(path), "%s/%s", dir_path, idx->filenames[i]);
        FILE *f = fopen(path, "r");
        if (!f) { perror(path); return -1; }
        struct stat st;
        stat(path, &st);
        idx->file_starts[i] = offset;
        fread(idx->text + offset, 1, (size_t)st.st_size, f);
        offset += (int)st.st_size;
        idx->file_ends[i] = offset;
        fclose(f);
        idx->text[offset] = '\0';
        offset++;
    }

    return 0;
}

/* ======== Position Mapping ======== */

int pos_to_file(Index *idx, int pos) {
    for (int i = 0; i < idx->nfiles; i++)
        if (pos >= idx->file_starts[i] && pos < idx->file_ends[i])
            return i;
    return -1;
}

int pos_to_line(Index *idx, int file_id, int pos) {
    int line = 1;
    for (int i = idx->file_starts[file_id]; i < pos; i++)
        if (idx->text[i] == '\n') line++;
    return line;
}

int crosses_boundary(Index *idx, int pos, int plen) {
    for (int i = pos; i < pos + plen && i < idx->n; i++)
        if (idx->text[i] == '\0') return 1;
    return 0;
}

/* ======== Result Helpers ======== */

static int result_cmp(const void *a, const void *b) {
    const Result *ra = a, *rb = b;
    if (ra->file_id != rb->file_id) return ra->file_id - rb->file_id;
    if (ra->line != rb->line) return ra->line - rb->line;
    return ra->pos - rb->pos;
}

int dedup_results(Result *results, int count) {
    if (count <= 1) return count;
    qsort(results, count, sizeof(Result), result_cmp);
    int out = 1;
    for (int i = 1; i < count; i++)
        if (results[i].file_id != results[out-1].file_id ||
            results[i].line != results[out-1].line)
            results[out++] = results[i];
    return out;
}

/* ======== Suffix Array Construction (O(n log^2 n)) ======== */

static int *_cmp_rank;
static int _cmp_k, _cmp_n;

static int sa_pair_cmp(const void *a, const void *b) {
    int i = *(const int *)a, j = *(const int *)b;
    if (_cmp_rank[i] != _cmp_rank[j])
        return _cmp_rank[i] - _cmp_rank[j];
    int ri = (i + _cmp_k < _cmp_n) ? _cmp_rank[i + _cmp_k] : -1;
    int rj = (j + _cmp_k < _cmp_n) ? _cmp_rank[j + _cmp_k] : -1;
    return ri - rj;
}

void build_suffix_array(Index *idx) {
    int n = idx->n;
    int *sa = idx->sa;
    int *rank = malloc(n * sizeof(int));
    int *tmp = malloc(n * sizeof(int));

    for (int i = 0; i < n; i++) {
        sa[i] = i;
        rank[i] = (unsigned char)idx->text[i];
    }

    _cmp_rank = rank;
    _cmp_n = n;

    for (int k = 1; k < n; k *= 2) {
        _cmp_k = k;
        qsort(sa, n, sizeof(int), sa_pair_cmp);

        tmp[sa[0]] = 0;
        for (int i = 1; i < n; i++) {
            tmp[sa[i]] = tmp[sa[i-1]];
            if (rank[sa[i]] != rank[sa[i-1]] ||
                ((sa[i]+k < n ? rank[sa[i]+k] : -1) !=
                 (sa[i-1]+k < n ? rank[sa[i-1]+k] : -1)))
                tmp[sa[i]]++;
        }
        memcpy(rank, tmp, n * sizeof(int));
        if (rank[sa[n-1]] == n - 1) break;
    }

    free(rank);
    free(tmp);
}

/* ======== Binary Search ======== */

static int suffix_pattern_cmp(const char *text, int n, const int *sa,
                               int mid, const char *pat, int plen) {
    int pos = sa[mid];
    for (int i = 0; i < plen; i++) {
        if (pos + i >= n) return -1;
        int d = (unsigned char)text[pos + i] - (unsigned char)pat[i];
        if (d != 0) return d;
    }
    return 0;
}

int sa_lower_bound(Index *idx, const char *pattern, int plen) {
    int lo = 0, hi = idx->n;
    while (lo < hi) {
        int mid = lo + (hi - lo) / 2;
        if (suffix_pattern_cmp(idx->text, idx->n, idx->sa, mid, pattern, plen) < 0)
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo;
}

int sa_upper_bound(Index *idx, const char *pattern, int plen) {
    int lo = 0, hi = idx->n;
    while (lo < hi) {
        int mid = lo + (hi - lo) / 2;
        if (suffix_pattern_cmp(idx->text, idx->n, idx->sa, mid, pattern, plen) <= 0)
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo;
}

/* ======== Search ======== */

int search(Index *idx, const char *pattern, Result *results, int max_results) {
    int plen = (int)strlen(pattern);
    if (plen == 0) return 0;

    int lo = sa_lower_bound(idx, pattern, plen);
    int hi = sa_upper_bound(idx, pattern, plen);

    int count = 0;
    for (int i = lo; i < hi && count < max_results; i++) {
        int pos = idx->sa[i];
        if (crosses_boundary(idx, pos, plen)) continue;
        int fid = pos_to_file(idx, pos);
        if (fid < 0) continue;
        results[count].file_id = fid;
        results[count].line = pos_to_line(idx, fid, pos);
        results[count].pos = pos;
        count++;
    }
    return count;
}

/* ======== Validation ======== */

int validate_sa(Index *idx) {
    int n = idx->n;
    char *seen = calloc(n, 1);
    for (int i = 0; i < n; i++) {
        if (idx->sa[i] < 0 || idx->sa[i] >= n || seen[idx->sa[i]]) {
            free(seen);
            fprintf(stderr, "SA is not a valid permutation at index %d (value %d)\n",
                    i, idx->sa[i]);
            return 0;
        }
        seen[idx->sa[i]] = 1;
    }
    free(seen);
    for (int i = 1; i < n; i++) {
        int a = idx->sa[i-1], b = idx->sa[i];
        int la = n - a, lb = n - b;
        int ml = la < lb ? la : lb;
        int cmp = memcmp(idx->text + a, idx->text + b, ml);
        if (cmp > 0 || (cmp == 0 && la > lb)) {
            fprintf(stderr, "SA not sorted at index %d: sa[%d]=%d vs sa[%d]=%d\n",
                    i, i-1, a, i, b);
            return 0;
        }
    }
    return 1;
}

/* ======== Main ======== */

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <corpus_dir> <pattern>\n", argv[0]);
        fprintf(stderr, "       %s --validate <corpus_dir>\n", argv[0]);
        return 1;
    }

    int validate_mode = (strcmp(argv[1], "--validate") == 0);
    const char *corpus_dir = validate_mode ? argv[2] : argv[1];

    Index idx;
    memset(&idx, 0, sizeof(idx));

    if (load_corpus(&idx, corpus_dir) != 0) {
        fprintf(stderr, "Failed to load corpus\n");
        return 1;
    }

    if (idx.nfiles == 0) {
        fprintf(stderr, "No files found in %s\n", corpus_dir);
        return 1;
    }

    build_suffix_array(&idx);

    if (validate_mode) {
        if (validate_sa(&idx)) {
            printf("VALID\n");
            free(idx.text); free(idx.sa);
            return 0;
        } else {
            printf("INVALID\n");
            free(idx.text); free(idx.sa);
            return 1;
        }
    }

    const char *pattern = argv[2];
    Result results[MAX_RESULTS];
    int count = search(&idx, pattern, results, MAX_RESULTS);
    count = dedup_results(results, count);

    for (int i = 0; i < count; i++)
        printf("%s:%d\n", idx.filenames[results[i].file_id], results[i].line);

    free(idx.text);
    free(idx.sa);
    return 0;
}
