/*
 *
 * Counting Quotient Filter — complete implementation.
 */

#include "cqf.h"
#include "cqf_hash.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>

/* ------------------------------------------------------------------ */
/*  Internal struct                                                    */
/* ------------------------------------------------------------------ */

struct cqf {
    int       q_bits;
    int       r_bits;
    uint32_t  seed;
    int       size;         /* 2^q_bits                              */
    int       r_mask;       /* (1 << r_bits) - 1                     */
    int      *remainders;   /* per-slot remainder                    */
    int      *counts;       /* per-slot count                        */
    uint8_t  *is_occupied;  /* quotient-index property               */
    uint8_t  *is_runend;    /* physical-slot property                */
    int       n_distinct;
    int       n_total;
};

/* ------------------------------------------------------------------ */
/*  Lifecycle                                                          */
/* ------------------------------------------------------------------ */

cqf_t *cqf_create(int q_bits, int r_bits, uint32_t seed) {
    if (q_bits < 2 || r_bits < 1) return NULL;

    cqf_t *qf = calloc(1, sizeof(cqf_t));
    if (!qf) return NULL;

    qf->q_bits = q_bits;
    qf->r_bits = r_bits;
    qf->seed   = seed;
    qf->size   = 1 << q_bits;
    qf->r_mask = (1 << r_bits) - 1;

    qf->remainders  = calloc((size_t)qf->size, sizeof(int));
    qf->counts      = calloc((size_t)qf->size, sizeof(int));
    qf->is_occupied = calloc((size_t)qf->size, sizeof(uint8_t));
    qf->is_runend   = calloc((size_t)qf->size, sizeof(uint8_t));

    if (!qf->remainders || !qf->counts || !qf->is_occupied || !qf->is_runend) {
        cqf_destroy(qf);
        return NULL;
    }
    return qf;
}

void cqf_destroy(cqf_t *qf) {
    if (!qf) return;
    free(qf->remainders);
    free(qf->counts);
    free(qf->is_occupied);
    free(qf->is_runend);
    free(qf);
}

/* ------------------------------------------------------------------ */
/*  Slot / cluster / run helpers                                       */
/* ------------------------------------------------------------------ */

static inline int slot_empty(const cqf_t *qf, int idx) {
    return qf->counts[idx % qf->size] == 0;
}

static int find_cluster_start(const cqf_t *qf, int pos) {
    int j = pos % qf->size;
    for (int i = 0; i < qf->size; i++) {
        int prev = (j - 1 + qf->size) % qf->size;
        if (slot_empty(qf, prev)) return j;
        j = prev;
    }
    return j;  /* entire array is one cluster */
}

static int find_run_start(const cqf_t *qf, int quotient) {
    int q = quotient % qf->size;
    if (!qf->is_occupied[q]) return -1;

    int cs = find_cluster_start(qf, q);
    if (cs == q) return q;

    /* Count occupied quotients in [cs, q) */
    int num_prior = 0;
    int pos = cs;
    while (pos != q) {
        if (qf->is_occupied[pos]) num_prior++;
        pos = (pos + 1) % qf->size;
    }

    /* Skip past num_prior run-end markers, starting from cluster_start */
    pos = cs;
    int ended = 0;
    for (int i = 0; i < qf->size; i++) {
        if (ended >= num_prior) break;
        if (qf->is_runend[pos]) ended++;
        pos = (pos + 1) % qf->size;
    }
    return pos;
}

static int find_run_end(const cqf_t *qf, int quotient) {
    int start = find_run_start(qf, quotient);
    if (start < 0) return -1;
    int pos = start;
    for (int i = 0; i < qf->size; i++) {
        if (qf->is_runend[pos]) return pos;
        pos = (pos + 1) % qf->size;
    }
    return start;
}

static int find_first_empty(const cqf_t *qf, int start) {
    int pos = start % qf->size;
    for (int i = 0; i < qf->size; i++) {
        if (slot_empty(qf, pos)) return pos;
        pos = (pos + 1) % qf->size;
    }
    return -1;  /* full */
}

/* ------------------------------------------------------------------ */
/*  Shift                                                              */
/* ------------------------------------------------------------------ */

static void shift_slots_right(cqf_t *qf, int from_pos, int to_pos) {
    int pos = to_pos;
    while (pos != from_pos) {
        int prev = (pos - 1 + qf->size) % qf->size;
        qf->remainders[pos]  = qf->remainders[prev];
        qf->counts[pos]      = qf->counts[prev];
        qf->is_runend[pos]   = qf->is_runend[prev];
        pos = prev;
    }
    qf->remainders[from_pos] = 0;
    qf->counts[from_pos]     = 0;
    qf->is_runend[from_pos]  = 0;
}

/* ------------------------------------------------------------------ */
/*  Core insert                                                        */
/* ------------------------------------------------------------------ */

static int insert_internal(cqf_t *qf, int q, int r, int count) {
    q = q % qf->size;
    qf->n_total += count;

    if (!qf->is_occupied[q]) {
        /* New quotient — start a new single-element run. */
        qf->is_occupied[q] = 1;
        qf->n_distinct++;

        if (slot_empty(qf, q)) {
            qf->remainders[q] = r;
            qf->counts[q]     = count;
            qf->is_runend[q]  = 1;
            return 0;
        }

        /* Canonical slot holds shifted data from another run.           */
        int insert_pos = find_run_start(qf, q);
        if (insert_pos < 0) insert_pos = q;
        int empty = find_first_empty(qf, insert_pos);
        if (empty < 0) return -1;
        if (empty != insert_pos)
            shift_slots_right(qf, insert_pos, empty);

        qf->remainders[insert_pos] = r;
        qf->counts[insert_pos]     = count;
        qf->is_runend[insert_pos]  = 1;
        return 0;
    }

    /* Quotient already present — locate the existing run. */
    int run_start = find_run_start(qf, q);
    int run_end   = find_run_end(qf, q);

    int pos = run_start;
    int insert_before = -1;

    while (1) {
        if (qf->remainders[pos] == r) {
            /* Already present — accumulate count. */
            qf->counts[pos] += count;
            return 0;
        }
        if (qf->remainders[pos] > r) {
            insert_before = pos;
            break;
        }
        if (pos == run_end) {
            /* r is larger than everything — append after run end. */
            insert_before = (run_end + 1) % qf->size;
            break;
        }
        pos = (pos + 1) % qf->size;
    }

    /* New distinct element. */
    qf->n_distinct++;
    int empty = find_first_empty(qf, insert_before);
    if (empty < 0) return -1;
    if (empty != insert_before)
        shift_slots_right(qf, insert_before, empty);

    qf->remainders[insert_before] = r;
    qf->counts[insert_before]     = count;

    if (insert_before == (run_end + 1) % qf->size) {
        /* Appended at end — new run-end. */
        qf->is_runend[insert_before] = 1;
        qf->is_runend[run_end]       = 0;
    } else {
        /* Inserted mid-run — not a run-end. */
        qf->is_runend[insert_before] = 0;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Query helper                                                       */
/* ------------------------------------------------------------------ */

static int query_internal(const cqf_t *qf, int q, int r) {
    q = q % qf->size;
    if (!qf->is_occupied[q]) return 0;

    int run_start = find_run_start(qf, q);
    if (run_start < 0) return 0;

    int pos = run_start;
    for (int i = 0; i < qf->size; i++) {
        if (qf->remainders[pos] == r) return qf->counts[pos];
        if (qf->remainders[pos] > r || qf->is_runend[pos]) return 0;
        pos = (pos + 1) % qf->size;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Public API                                                         */
/* ------------------------------------------------------------------ */

int cqf_insert(cqf_t *qf, const char *item, int count) {
    if (!qf || !item || count <= 0) return -1;
    int q, r;
    cqf_hash(item, qf->q_bits, qf->r_bits, qf->seed, &q, &r);
    return insert_internal(qf, q, r, count);
}

int cqf_insert_raw(cqf_t *qf, int quotient, int remainder, int count) {
    if (!qf || count <= 0) return -1;
    return insert_internal(qf, quotient, remainder, count);
}

int cqf_query(const cqf_t *qf, const char *item) {
    if (!qf || !item) return 0;
    int q, r;
    cqf_hash(item, qf->q_bits, qf->r_bits, qf->seed, &q, &r);
    return query_internal(qf, q, r);
}

int cqf_query_raw(const cqf_t *qf, int quotient, int remainder) {
    if (!qf) return 0;
    return query_internal(qf, quotient, remainder);
}

int cqf_delete(cqf_t *qf, const char *item, int count) {
    if (!qf || !item || count <= 0) return -1;
    int q, r;
    cqf_hash(item, qf->q_bits, qf->r_bits, qf->seed, &q, &r);

    q = q % qf->size;
    if (!qf->is_occupied[q]) return -1;

    int run_start = find_run_start(qf, q);
    if (run_start < 0) return -1;

    int pos = run_start;
    for (int i = 0; i < qf->size; i++) {
        if (qf->remainders[pos] == r) {
            int removed = count < qf->counts[pos] ? count : qf->counts[pos];
            qf->counts[pos] -= removed;
            qf->n_total -= removed;
            if (qf->counts[pos] <= 0) {
                qf->counts[pos] = 0;
                qf->n_distinct--;
            }
            return 0;
        }
        if (qf->remainders[pos] > r || qf->is_runend[pos]) return -1;
        pos = (pos + 1) % qf->size;
    }
    return -1;
}

/* ------------------------------------------------------------------ */
/*  Iteration helper                                                   */
/* ------------------------------------------------------------------ */

typedef struct { int q, r, count; } entry_t;

static int collect_entries(const cqf_t *qf, entry_t **out, int *n_out) {
    *out = malloc((size_t)qf->size * sizeof(entry_t));
    if (!*out) return -1;
    *n_out = 0;

    for (int q = 0; q < qf->size; q++) {
        if (!qf->is_occupied[q]) continue;
        int rs = find_run_start(qf, q);
        if (rs < 0) continue;
        int pos = rs;
        for (int i = 0; i < qf->size; i++) {
            if (qf->counts[pos] > 0) {
                (*out)[*n_out].q     = q;
                (*out)[*n_out].r     = qf->remainders[pos];
                (*out)[*n_out].count = qf->counts[pos];
                (*n_out)++;
            }
            if (qf->is_runend[pos]) break;
            pos = (pos + 1) % qf->size;
        }
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Merge                                                              */
/* ------------------------------------------------------------------ */

cqf_t *cqf_merge(const cqf_t *a, const cqf_t *b) {
    if (!a || !b) return NULL;
    if (a->q_bits != b->q_bits || a->r_bits != b->r_bits ||
        a->seed != b->seed) return NULL;

    cqf_t *result = cqf_create(a->q_bits, a->r_bits, a->seed);
    if (!result) return NULL;

    entry_t *ea = NULL, *eb = NULL;
    int na = 0, nb = 0;
    collect_entries(a, &ea, &na);
    collect_entries(b, &eb, &nb);

    for (int i = 0; i < na; i++)
        insert_internal(result, ea[i].q, ea[i].r, ea[i].count);
    for (int i = 0; i < nb; i++)
        insert_internal(result, eb[i].q, eb[i].r, eb[i].count);

    free(ea);
    free(eb);
    return result;
}

/* ------------------------------------------------------------------ */
/*  Resize                                                             */
/* ------------------------------------------------------------------ */

int cqf_resize(cqf_t *qf) {
    if (!qf || qf->r_bits <= 1) return -1;

    entry_t *entries = NULL;
    int n = 0;
    collect_entries(qf, &entries, &n);
    int old_r_bits = qf->r_bits;

    qf->q_bits++;
    qf->r_bits--;
    int new_size = 1 << qf->q_bits;
    qf->r_mask = (1 << qf->r_bits) - 1;

    free(qf->remainders);
    free(qf->counts);
    free(qf->is_occupied);
    free(qf->is_runend);

    qf->size        = new_size;
    qf->remainders  = calloc((size_t)new_size, sizeof(int));
    qf->counts      = calloc((size_t)new_size, sizeof(int));
    qf->is_occupied = calloc((size_t)new_size, sizeof(uint8_t));
    qf->is_runend   = calloc((size_t)new_size, sizeof(uint8_t));
    qf->n_distinct  = 0;
    qf->n_total     = 0;

    for (int i = 0; i < n; i++) {
        int new_q = (entries[i].q << 1) | (entries[i].r >> (old_r_bits - 1));
        int new_r = entries[i].r & qf->r_mask;
        insert_internal(qf, new_q, new_r, entries[i].count);
    }

    free(entries);
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Serialization                                                      */
/* ------------------------------------------------------------------ */

int cqf_serialize(const cqf_t *qf, const char *path) {
    if (!qf || !path) return -1;
    FILE *f = fopen(path, "wb");
    if (!f) return -1;

    /* Header: magic, q_bits, r_bits, seed, n_distinct, n_total */
    uint32_t magic = 0x43514631;  /* "CQF1" */
    fwrite(&magic,          sizeof(uint32_t), 1, f);
    fwrite(&qf->q_bits,    sizeof(int),      1, f);
    fwrite(&qf->r_bits,    sizeof(int),      1, f);
    fwrite(&qf->seed,      sizeof(uint32_t), 1, f);
    fwrite(&qf->n_distinct, sizeof(int),     1, f);
    fwrite(&qf->n_total,   sizeof(int),      1, f);

    /* Slot arrays */
    fwrite(qf->remainders,  sizeof(int),     (size_t)qf->size, f);
    fwrite(qf->counts,      sizeof(int),     (size_t)qf->size, f);
    fwrite(qf->is_occupied, sizeof(uint8_t), (size_t)qf->size, f);
    fwrite(qf->is_runend,   sizeof(uint8_t), (size_t)qf->size, f);

    fclose(f);
    return 0;
}

cqf_t *cqf_deserialize(const char *path) {
    if (!path) return NULL;
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;

    uint32_t magic;
    int q_bits, r_bits, n_distinct, n_total;
    uint32_t seed;

    if (fread(&magic,      sizeof(uint32_t), 1, f) != 1) { fclose(f); return NULL; }
    if (magic != 0x43514631) { fclose(f); return NULL; }
    if (fread(&q_bits,     sizeof(int),      1, f) != 1) { fclose(f); return NULL; }
    if (fread(&r_bits,     sizeof(int),      1, f) != 1) { fclose(f); return NULL; }
    if (fread(&seed,       sizeof(uint32_t), 1, f) != 1) { fclose(f); return NULL; }
    if (fread(&n_distinct, sizeof(int),      1, f) != 1) { fclose(f); return NULL; }
    if (fread(&n_total,    sizeof(int),      1, f) != 1) { fclose(f); return NULL; }

    cqf_t *qf = cqf_create(q_bits, r_bits, seed);
    if (!qf) { fclose(f); return NULL; }

    qf->n_distinct = n_distinct;
    qf->n_total    = n_total;

    fread(qf->remainders,  sizeof(int),     (size_t)qf->size, f);
    fread(qf->counts,      sizeof(int),     (size_t)qf->size, f);
    fread(qf->is_occupied, sizeof(uint8_t), (size_t)qf->size, f);
    fread(qf->is_runend,   sizeof(uint8_t), (size_t)qf->size, f);

    fclose(f);
    return qf;
}

/* ------------------------------------------------------------------ */
/*  Vector operations                                                  */
/* ------------------------------------------------------------------ */

int64_t cqf_inner_product(const cqf_t *a, const cqf_t *b) {
    if (!a || !b) return 0;
    if (a->q_bits != b->q_bits || a->r_bits != b->r_bits ||
        a->seed != b->seed) return 0;

    int64_t total = 0;
    for (int q = 0; q < a->size; q++) {
        if (!a->is_occupied[q]) continue;
        int rs = find_run_start(a, q);
        if (rs < 0) continue;
        int pos = rs;
        for (int i = 0; i < a->size; i++) {
            if (a->counts[pos] > 0) {
                int cb = query_internal(b, q, a->remainders[pos]);
                total += (int64_t)a->counts[pos] * cb;
            }
            if (a->is_runend[pos]) break;
            pos = (pos + 1) % a->size;
        }
    }
    return total;
}

double cqf_cosine_similarity(const cqf_t *a, const cqf_t *b) {
    if (!a || !b) return 0.0;
    int64_t ip    = cqf_inner_product(a, b);
    int64_t mag_a = cqf_inner_product(a, a);
    int64_t mag_b = cqf_inner_product(b, b);
    if (mag_a == 0 || mag_b == 0) return 0.0;
    return (double)ip / sqrt((double)mag_a * (double)mag_b);
}

/* ------------------------------------------------------------------ */
/*  Accessors                                                          */
/* ------------------------------------------------------------------ */

int cqf_get_q_bits(const cqf_t *qf)     { return qf ? qf->q_bits    : 0; }
int cqf_get_r_bits(const cqf_t *qf)     { return qf ? qf->r_bits    : 0; }
int cqf_count_distinct(const cqf_t *qf) { return qf ? qf->n_distinct : 0; }

int cqf_get_entries(const cqf_t *qf, int *quotients, int *remainders,
                    int *counts, int max_entries) {
    if (!qf || !quotients || !remainders || !counts || max_entries <= 0)
        return 0;

    int written = 0;
    for (int q = 0; q < qf->size && written < max_entries; q++) {
        if (!qf->is_occupied[q]) continue;
        int rs = find_run_start(qf, q);
        if (rs < 0) continue;
        int pos = rs;
        for (int i = 0; i < qf->size && written < max_entries; i++) {
            if (qf->counts[pos] > 0) {
                quotients[written]  = q;
                remainders[written] = qf->remainders[pos];
                counts[written]     = qf->counts[pos];
                written++;
            }
            if (qf->is_runend[pos]) break;
            pos = (pos + 1) % qf->size;
        }
    }
    return written;
}
