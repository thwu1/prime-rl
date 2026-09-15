 *
 * codesearch.c — Suffix-array-based code search tool.
 *
 * Indexes a directory of source files by building a suffix array over
 * the concatenated content (files separated by NUL bytes), then answers
 * substring queries via binary search on the suffix array.
 *
 * Usage:
 *   ./codesearch <corpus_dir> <pattern>
 *   ./codesearch --validate <corpus_dir>
 *
 * Output: filename:line_number (sorted, deduplicated)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <sys/stat.h>

#define MAX_FILES 1024
#define MAX_RESULTS 100000

typedef struct {
    char *text;     /* Concatenated file contents with NUL separators */
    int *sa;        /* Suffix array: sa[i] = starting position of i-th smallest suffix */
    int n;          /* Total length of text (including NUL separators) */
    int nfiles;
    char filenames[MAX_FILES][256];
    int file_starts[MAX_FILES];   /* Start offset of each file in text[] */
    int file_ends[MAX_FILES];     /* End offset (exclusive) of each file */
} Index;

typedef struct {
    int file_id;
    int line;
    int pos;        /* Position in concatenated text */
} Result;

/* ================================================================
 * PROVIDED FUNCTIONS — DO NOT MODIFY
 * ================================================================ */

/*
 * Load all regular files from dir_path into a single concatenated buffer.
 * Files are separated by NUL bytes and sorted alphabetically by name.
 * A trailing NUL is appended as a sentinel.
 */
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

    /* Sort filenames for deterministic output order */
    for (int i = 0; i < idx->nfiles - 1; i++)
        for (int j = i + 1; j < idx->nfiles; j++)
            if (strcmp(idx->filenames[i], idx->filenames[j]) > 0) {
                char tmp[256];
                strcpy(tmp, idx->filenames[i]);
                strcpy(idx->filenames[i], idx->filenames[j]);
                strcpy(idx->filenames[j], tmp);
            }

    /* Compute total size: sum of file sizes + one NUL after each file */
    int total = 0;
    for (int i = 0; i < idx->nfiles; i++) {
        char path[512];
        snprintf(path, sizeof(path), "%s/%s", dir_path, idx->filenames[i]);
        struct stat st;
        stat(path, &st);
        total += (int)st.st_size;
    }
    total += idx->nfiles; /* one NUL separator after each file */

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
        idx->text[offset] = '\0'; /* NUL separator */
        offset++;
    }

    return 0;
}

/* Map a position in concatenated text to the file index it belongs to.
 * Returns -1 if the position is on a NUL separator. */
int pos_to_file(Index *idx, int pos) {
    for (int i = 0; i < idx->nfiles; i++)
        if (pos >= idx->file_starts[i] && pos < idx->file_ends[i])
            return i;
    return -1;
}

/* Compute the 1-based line number of position pos within file file_id. */
int pos_to_line(Index *idx, int file_id, int pos) {
    int line = 1;
    for (int i = idx->file_starts[file_id]; i < pos; i++)
        if (idx->text[i] == '\n') line++;
    return line;
}

/* Return 1 if the range [pos, pos+plen) contains a NUL byte
 * (i.e., spans a file boundary). */
int crosses_boundary(Index *idx, int pos, int plen) {
    for (int i = pos; i < pos + plen && i < idx->n; i++)
        if (idx->text[i] == '\0') return 1;
    return 0;
}

static int result_cmp(const void *a, const void *b) {
    const Result *ra = a, *rb = b;
    if (ra->file_id != rb->file_id) return ra->file_id - rb->file_id;
    if (ra->line != rb->line) return ra->line - rb->line;
    return ra->pos - rb->pos;
}

/* Sort results by (file, line) and remove duplicates on the same line. */
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

/* Validate suffix array: check permutation property and sorted order. */
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

/* ================================================================
 * IMPLEMENT THESE FUNCTIONS
 * ================================================================ */

/*
 * Construct the suffix array for idx->text of length idx->n.
 * Store the result in idx->sa[] (already allocated, zeroed).
 *
 * After construction, sa[] must be a permutation of [0, n) such that:
 *   text[sa[0]..] < text[sa[1]..] < ... < text[sa[n-1]..]
 * in lexicographic order using unsigned byte comparison.
 *
 * The text contains NUL bytes ('\0') as file separators. NUL has byte
 * value 0, so it sorts before all other characters.
 *
 * Recommended: O(n log^2 n) rank-doubling algorithm.
 *   1. Initialize rank[i] = (unsigned char)text[i] for all i.
 *   2. Sort suffix indices by the pair (rank[i], rank[i+k]) for k=1,2,4,...
 *      using the pair as a composite sort key. If i+k >= n, use -1.
 *   3. After each sort, recompute ranks: assign consecutive integers
 *      to distinct sort keys (0 for smallest pair, 1 for next distinct, etc.).
 *   4. Stop when all ranks are unique (max rank == n-1).
 *
 * You may allocate temporary arrays as needed.
 * A naive O(n^2 log n) approach (qsort with strcmp) will be too slow
 * for the performance test (~500 KB corpus).
 */
void build_suffix_array(Index *idx) {
    /* TODO: Implement suffix array construction */
}

/*
 * Binary search on the suffix array for the FIRST index i where the
 * suffix text[sa[i]..] starts with `pattern` (or is lexicographically
 * greater than pattern).
 *
 * Compare the first plen bytes of each suffix against pattern using
 * unsigned byte comparison. If the suffix has fewer than plen bytes
 * remaining before end-of-text, treat it as less than the pattern.
 *
 * Return the smallest such index, or idx->n if none exists.
 */
int sa_lower_bound(Index *idx, const char *pattern, int plen) {
    /* TODO: Implement binary search lower bound */
    return idx->n;
}

/*
 * Binary search on the suffix array for the FIRST index i where the
 * suffix text[sa[i]..] does NOT start with `pattern` and is
 * lexicographically GREATER than any string with that prefix.
 *
 * The range [sa_lower_bound, sa_upper_bound) identifies exactly the
 * suffix array entries whose suffixes begin with `pattern`.
 *
 * Return idx->n if all suffixes from lower_bound onward match.
 */
int sa_upper_bound(Index *idx, const char *pattern, int plen) {
    /* TODO: Implement binary search upper bound */
    return idx->n;
}

/*
 * Find all occurrences of `pattern` in the indexed text.
 *
 * 1. Use sa_lower_bound() and sa_upper_bound() to find the range
 *    [lo, hi) of suffix array positions that match.
 * 2. For each position i in [lo, hi):
 *    a. Get the text position: pos = sa[i]
 *    b. Skip if the match crosses a file boundary (use crosses_boundary())
 *    c. Find which file this position belongs to (use pos_to_file())
 *    d. Find the line number within that file (use pos_to_line())
 *    e. Store the result in results[]
 * 3. Return the number of results found (up to max_results).
 *
 * Do not deduplicate here — the caller handles that via dedup_results().
 */
int search(Index *idx, const char *pattern, Result *results, int max_results) {
    /* TODO: Implement search using suffix array */
    return 0;
}

/* ================================================================
 * MAIN — DO NOT MODIFY
 * ================================================================ */

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
