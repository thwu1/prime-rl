/*
 * trec_eval - Minimal TREC-style evaluation tool
 * Computes reciprocal rank (MRR) for ranked retrieval evaluation.
 *
 * Usage: trec_eval [options] <qrel_file> <run_file>
 * Options:
 *   -q              Print per-query scores
 *   -m metric.K     Set metric and cutoff (default: recip_rank.10)
 *
 * Input formats:
 *   qrels: qid iter docid rel  (whitespace-separated, rel > 0 = relevant)
 *   runs:  qid Q0 docid rank score runid  (whitespace-separated)
 *
 * Output: recip_rank  <qid|all>  <score>
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define INIT_CAP 256
#define MAX_LINE 4096

typedef struct { int *d; int n, cap; } IVec;
static void iv_init(IVec *v) { v->n = 0; v->cap = 16; v->d = malloc(16 * sizeof(int)); }
static void iv_push(IVec *v, int x) {
    if (v->n >= v->cap) { v->cap *= 2; v->d = realloc(v->d, v->cap * sizeof(int)); }
    v->d[v->n++] = x;
}
static int iv_has(IVec *v, int x) {
    for (int i = 0; i < v->n; i++) if (v->d[i] == x) return 1;
    return 0;
}

typedef struct { int qid; IVec rel; } QE;
static QE *qe_arr = NULL;
static int qe_n = 0, qe_cap = 0;

static QE *qe_find(int qid) {
    for (int i = 0; i < qe_n; i++) if (qe_arr[i].qid == qid) return &qe_arr[i];
    return NULL;
}
static QE *qe_get(int qid) {
    QE *e = qe_find(qid);
    if (e) return e;
    if (qe_n >= qe_cap) {
        qe_cap = qe_cap ? qe_cap * 2 : INIT_CAP;
        qe_arr = realloc(qe_arr, qe_cap * sizeof(QE));
    }
    e = &qe_arr[qe_n++];
    e->qid = qid;
    iv_init(&e->rel);
    return e;
}

typedef struct { int docid; int rank; } DR;
typedef struct { int qid; DR *docs; int n, cap; } RE;
static RE *re_arr = NULL;
static int re_n = 0, re_cap = 0;

static RE *re_find(int qid) {
    for (int i = 0; i < re_n; i++) if (re_arr[i].qid == qid) return &re_arr[i];
    return NULL;
}
static RE *re_get(int qid) {
    RE *e = re_find(qid);
    if (e) return e;
    if (re_n >= re_cap) {
        re_cap = re_cap ? re_cap * 2 : INIT_CAP;
        re_arr = realloc(re_arr, re_cap * sizeof(RE));
    }
    e = &re_arr[re_n++];
    e->qid = qid;
    e->n = 0; e->cap = 128;
    e->docs = malloc(128 * sizeof(DR));
    return e;
}
static void re_add(RE *e, int docid, int rank) {
    if (e->n >= e->cap) { e->cap *= 2; e->docs = realloc(e->docs, e->cap * sizeof(DR)); }
    e->docs[e->n].docid = docid;
    e->docs[e->n].rank = rank;
    e->n++;
}

static int dr_cmp(const void *a, const void *b) {
    return ((const DR *)a)->rank - ((const DR *)b)->rank;
}

static void load_qrels(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "Error: cannot open qrels '%s'\n", path); exit(1); }
    char line[MAX_LINE];
    int qid, iter, docid, rel;
    while (fgets(line, sizeof(line), f)) {
        if (sscanf(line, "%d %d %d %d", &qid, &iter, &docid, &rel) == 4 && rel > 0) {
            QE *e = qe_get(qid);
            if (!iv_has(&e->rel, docid)) iv_push(&e->rel, docid);
        }
    }
    fclose(f);
}

static void load_run(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "Error: cannot open run '%s'\n", path); exit(1); }
    char line[MAX_LINE];
    int qid, docid, rank;
    while (fgets(line, sizeof(line), f)) {
        if (sscanf(line, "%d %*s %d %d", &qid, &docid, &rank) == 3) {
            RE *e = re_get(qid);
            re_add(e, docid, rank);
        }
    }
    fclose(f);
    for (int i = 0; i < re_n; i++)
        qsort(re_arr[i].docs, re_arr[i].n, sizeof(DR), dr_cmp);
}

int main(int argc, char **argv) {
    int per_query = 0, cutoff = 10, argi = 1;
    while (argi < argc && argv[argi][0] == '-') {
        if (!strcmp(argv[argi], "-q")) { per_query = 1; argi++; }
        else if (!strcmp(argv[argi], "-m") && argi + 1 < argc) {
            argi++;
            char *dot = strchr(argv[argi], '.');
            if (dot) cutoff = atoi(dot + 1);
            argi++;
        } else argi++;
    }
    if (argc - argi < 2) {
        fprintf(stderr, "Usage: trec_eval [-q] [-m recip_rank.K] <qrels> <run>\n");
        return 1;
    }
    load_qrels(argv[argi]);
    load_run(argv[argi + 1]);

    double sum_rr = 0.0;
    for (int i = 0; i < qe_n; i++) {
        QE *q = &qe_arr[i];
        RE *r = re_find(q->qid);
        double rr = 0.0;
        if (r) {
            int lim = r->n < cutoff ? r->n : cutoff;
            for (int j = 0; j < lim; j++) {
                if (iv_has(&q->rel, r->docs[j].docid)) {
                    rr = 1.0 / (j + 1);
                    break;
                }
            }
        }
        if (per_query) printf("recip_rank\t%d\t%.6f\n", q->qid, rr);
        sum_rr += rr;
    }
    printf("recip_rank\tall\t%.6f\n", qe_n > 0 ? sum_rr / qe_n : 0.0);
    return 0;
}
